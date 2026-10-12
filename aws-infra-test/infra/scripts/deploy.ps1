#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProfileDirectory,
    [ValidateSet('Plan','Apply','Deploy','Inventory','Proxy','Front','Install','All')]
    [string]$Action = 'Plan',
    [ValidateSet('foundation','connectivity','workload','bastion')][string]$Stage,
    [ValidateSet('all','account1','account2','account3','account4','account5')]
    [string]$Account = 'all',
    [string]$Limit = 'all',
    [string]$VaultFile,
    [string]$StaticDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib/infra-common.ps1')
$infraRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib/test-isolation.ps1')
Assert-TestIsolation $infraRoot
$platformRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $infraRoot)) 'aws-platform/platform'
$runner = Join-Path $PSScriptRoot 'infra.ps1'
if ($ProfileDirectory) { throw '테스트 config는 고정 경로입니다. ProfileDirectory를 지정하지 마세요.' }
$ProfileDirectory = Join-Path $infraRoot 'config'

foreach ($name in @('topology.tfvars.json','traffic.tfvars.json','platform.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProfileDirectory $name) -PathType Leaf)) { throw "구성 파일이 없습니다: $name" }
}
$topology = (Read-InfraJson (Join-Path $ProfileDirectory 'topology.tfvars.json')).topology
$traffic = (Read-InfraJson (Join-Path $ProfileDirectory 'traffic.tfvars.json')).traffic
$platform = Read-InfraJson (Join-Path $ProfileDirectory 'platform.json')
Assert-InfraConfiguration $topology $traffic
$bastionNodes = @($topology.nodes.PSObject.Properties | Where-Object { $_.Value.role -eq 'bastion' })
if ($bastionNodes.Count -ne 1 -or $bastionNodes[0].Name -ne 'bastion' -or $bastionNodes[0].Value.account -ne 'account1') {
    throw '현재 인프라는 account1의 bastion 노드 1대를 사용합니다. 서비스 노드는 계정 간에 배치할 수 있습니다.'
}
if ($platform.inventory_name -notmatch '^hosts\.[A-Za-z0-9_-]+\.yml$') {
    throw 'inventory_name은 hosts.구성이름.yml 형식이어야 합니다. 기존 hosts.yml은 별도로 유지합니다.'
}
$inventoryPath = Join-Path $infraRoot "bootstrap/inventory/$($platform.inventory_name)"
$null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $inventoryPath)
$accountNames = @($topology.accounts.PSObject.Properties.Name | Sort-Object)

function Get-DeploymentTargets {
    param([string]$SelectedStage)
    if ($SelectedStage -eq 'connectivity') {
        if ($Account -ne 'all') { throw 'connectivity는 모든 계정의 공통 단계이므로 -Account all을 사용하세요.' }
        return 'shared'
    }
    if ($SelectedStage -eq 'bastion') {
        $bastionAccount = $topology.nodes.bastion.account
        if ($Account -ne 'all' -and $Account -ne $bastionAccount) { throw '선택한 계정에 배스천이 없습니다.' }
        return $bastionAccount
    }
    if ($Account -eq 'all') { return $accountNames }
    return $Account
}

function Invoke-DeploymentStage {
    param([string]$SelectedStage, [string]$SelectedAction)
    foreach ($target in @(Get-DeploymentTargets $SelectedStage)) {
        Write-Host "[$SelectedAction] $target / $SelectedStage / $ProfileDirectory"
        & $runner -Account $target -Stage $SelectedStage -Action $SelectedAction | Out-Host
    }
}

function Read-DeploymentOutput {
    param([string]$TargetAccount, [string]$TargetStage)
    & $runner -Account $TargetAccount -Stage $TargetStage -Action Output | Out-Host
    $workPath = Get-InfraWorkPath $infraRoot $TargetAccount $TargetStage
    return Read-InfraJson (Join-Path $workPath 'outputs.json')
}

function Get-DeploymentTag {
    param($Instance, [string]$Name)
    return (@($Instance.Tags | Where-Object { $_.Key -eq $Name } | ForEach-Object { $_.Value }) -join '')
}

function Write-DeploymentInventory {
    $records = @()
    $volumeMaps = @{}
    foreach ($key in $accountNames) {
        if (-not $platform.ssh_keys.PSObject.Properties[$key]) { throw "platform.json에 $key 의 WSL 개인키 경로를 지정하세요." }
        $output = Read-DeploymentOutput $key 'workload'
        $instances = @($output.inventory.value.instances.PSObject.Properties)
        foreach ($item in $instances) { $volumeMaps[$item.Name] = $item.Value.data_volumes }
        $expected = @($topology.nodes.PSObject.Properties | Where-Object { $_.Value.account -eq $key -and $_.Value.role -ne 'bastion' })
        if ((@($instances | ForEach-Object { $_.Name } | Sort-Object) -join ',') -ne
            (@($expected | ForEach-Object { $_.Name } | Sort-Object) -join ',')) {
            throw "$key 의 실제 상태와 선택한 노드 구성이 다릅니다. 해당 구성의 Plan·Apply를 완료하세요."
        }
        foreach ($node in $expected) {
            $records += [pscustomobject]@{ Name = $node.Name; Account = $key; Role = $node.Value.role; Id = $output.inventory.value.instances.($node.Name).id }
        }
    }
    $bastionAccount = $topology.nodes.bastion.account
    $bastionOutput = Read-DeploymentOutput $bastionAccount 'bastion'
    $records += [pscustomobject]@{ Name = 'bastion'; Account = $bastionAccount; Role = 'bastion'; Id = $bastionOutput.bastion.value.id }

    # Terraform이 소유한 ID로 현재 주소를 다시 조회한다. 중지·시작으로 바뀐 공인 IP도 반영한다.
    $aws = (Get-Command aws -CommandType Application -ErrorAction Stop).Source
    $live = @{}
    foreach ($key in $accountNames) {
        $selected = @($records | Where-Object { $_.Account -eq $key })
        if ($selected.Count -eq 0) { continue }
        $arguments = @('ec2','describe-instances','--instance-ids') + @($selected.Id) +
            @('--profile',$topology.accounts.$key.profile,'--region',$topology.region,'--output','json','--no-cli-pager')
        $result = & $aws @arguments
        if ($LASTEXITCODE -ne 0) { throw "$key EC2 주소 조회에 실패했습니다." }
        $response = ($result -join [Environment]::NewLine) | ConvertFrom-Json
        foreach ($reservation in @($response.Reservations)) {
            if ($reservation.OwnerId -ne $topology.accounts.$key.id) { throw "$key 의 실제 EC2 소유 계정이 다릅니다." }
            foreach ($instance in @($reservation.Instances)) { $live[$instance.InstanceId] = $instance }
        }
    }
    $inventory = @{ all = @{ vars = @{ ansible_user = $platform.ssh_user; users = @(); proxy_enabled = $true; test_project = 'aws-infra-test' }; children = @{} } }
    $bastionHost = 'bastion-01'
    $hostNames = @{}
    foreach ($record in $records) {
        $instance = $live[$record.Id]
        if (-not $instance -or $instance.State.Name -ne 'running') { throw "$($record.Name)이 실행 중이 아닙니다." }
        if ((Get-DeploymentTag $instance 'Node') -ne $record.Name -or
            (Get-DeploymentTag $instance 'Role') -ne $record.Role -or
            (Get-DeploymentTag $instance 'Project') -ne $topology.project) { throw "$($record.Name)의 EC2 태그가 구성과 다릅니다." }
        if ($instance.InstanceType -ne $topology.nodes.($record.Name).instance_type) { throw "$($record.Name)의 사양 변경을 먼저 적용하세요." }
        $hostName = if ($record.Role -eq 'bastion') { $bastionHost } else { $record.Name }
        $group = if ($platform.role_groups.PSObject.Properties[$record.Role]) { $platform.role_groups.($record.Role) } else { $record.Role }
        if ($hostName -notmatch '^[A-Za-z0-9_-]+$' -or $group -notmatch '^[A-Za-z][A-Za-z0-9_]*$' -or $hostName -eq $group) {
            throw "Ansible 호스트·그룹 이름을 확인하세요: $hostName / $group"
        }
        if ($hostNames.ContainsKey($hostName)) { throw "중복된 Ansible 호스트 이름입니다: $hostName" }
        $hostNames[$hostName] = $true
        # host 변수로 기록해 기본 group_vars보다 선택한 구성의 키·CIDR·포트가 우선한다.
        $hostVars = @{
            ip = $instance.PrivateIpAddress
            ansible_host = $instance.PrivateIpAddress
            ansible_user = $platform.ssh_user
            ansible_ssh_private_key_file = $platform.ssh_keys.($record.Account)
            proxy_enabled = $true
            proxy_port = $traffic.ports.proxy
            proxy_client_cidrs = @($accountNames | ForEach-Object { $topology.accounts.$_.vpc_cidr })
        }
        $hostVars.test_data_volumes = if ($volumeMaps.ContainsKey($record.Name)) { $volumeMaps[$record.Name] } else { @{} }
        $hostVars.test_client_cidrs = if ($traffic.PSObject.Properties['public_http_cidrs']) { @($traffic.public_http_cidrs) } else { @($traffic.game_client_cidrs) }
        if ($record.Role -eq 'frontend') {
            $hostVars.public_ip = $instance.PublicIpAddress
            Write-Host "테스트 접속 주소: http://$($instance.PublicIpAddress) (앱 배포 후 사용)"
        }
        if ($record.Role -eq 'bastion') {
            if (-not $instance.PSObject.Properties['PublicIpAddress'] -or -not $instance.PublicIpAddress) { throw '배스천 공인 IP가 없습니다.' }
            $hostVars.public_ip = $instance.PublicIpAddress
            $hostVars.ansible_host = $instance.PublicIpAddress
            $hostVars.ansible_ssh_common_args = ''
        } else {
            # 대상 계정의 키와 배스천 키를 분리해 서버를 다른 계정으로 옮겨도 같은 경유 방식을 쓴다.
            $hostVars.ansible_ssh_common_args = '-o IdentitiesOnly=yes -o ProxyCommand="ssh -W %h:%p -i \"{{ hostvars[''bastion-01''].ansible_ssh_private_key_file }}\" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new {{ hostvars[''bastion-01''].ansible_user }}@{{ hostvars[''bastion-01''].public_ip }}"'
        }
        foreach ($groupName in @($record.Account, $group)) {
            if (-not $inventory.all.children.ContainsKey($groupName)) { $inventory.all.children[$groupName] = @{ hosts = @{} } }
        }
        $inventory.all.children[$record.Account].hosts[$hostName] = $hostVars
        $inventory.all.children[$group].hosts[$hostName] = @{}
    }
    # JSON은 YAML 인벤토리로 읽을 수 있다. 주소와 개인키 경로만 기록하며 키 내용은 읽지 않는다.
    Write-InfraJson $inventoryPath $inventory
    Write-Host "Ansible 인벤토리 갱신: $inventoryPath"
}

function Invoke-DeploymentProxy {
    if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) { throw 'Inventory를 먼저 실행하세요.' }
    # 여러 WSL 경로가 조회되어도 명령 검색 순서의 첫 실행 파일만 사용한다.
    $wsl = (Get-Command wsl -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $scriptPath = Join-Path $platformRoot 'scripts/setup-proxy.sh'
    $scriptWsl = & $wsl -d $platform.wsl_distribution --exec wslpath -a $scriptPath
    if ($LASTEXITCODE -ne 0) { throw 'WSL 스크립트 경로 변환에 실패했습니다.' }
    $inventoryWsl = & $wsl -d $platform.wsl_distribution --exec wslpath -a $inventoryPath
    if ($LASTEXITCODE -ne 0) { throw 'WSL 인벤토리 경로 변환에 실패했습니다.' }
    # bash -c에 구성값을 연결하지 않고 스크립트 인수로 전달해 PowerShell의 중첩 따옴표를 피한다.
    $scriptWsl = ($scriptWsl -join '').Trim()
    $inventoryWsl = ($inventoryWsl -join '').Trim()
    & $wsl -d $platform.wsl_distribution --exec bash $scriptWsl --venv $platform.ansible_venv --inventory $inventoryWsl --limit $Limit
    if ($LASTEXITCODE -ne 0) { throw "프록시 준비에 실패했습니다: 종료 코드 $LASTEXITCODE" }
}


function Invoke-TestBootstrap {
    param([string]$Mode)
    if (-not (Test-Path -LiteralPath $inventoryPath)) { throw 'Inventory를 먼저 실행하세요.' }
    if ($Mode -eq 'install' -and (-not $VaultFile -or -not (Test-Path -LiteralPath $VaultFile -PathType Leaf))) {
        throw '클러스터 설치에는 테스트 비밀번호를 준비한 -VaultFile이 필요합니다.'
    }
    $wsl = (Get-Command wsl -CommandType Application | Select-Object -First 1).Source
    function Convert-TestWslPath([string]$Path) {
        $absolute = (Resolve-Path -LiteralPath $Path).Path
        $result = & $wsl -d $platform.wsl_distribution --exec wslpath -a $absolute
        if ($LASTEXITCODE -ne 0) { throw 'WSL 경로 변환에 실패했습니다.' }
        return ($result -join '').Trim()
    }
    $arguments = @('-d', $platform.wsl_distribution, '--exec', 'bash',
        (Convert-TestWslPath (Join-Path $infraRoot 'bootstrap/run.sh')), $Mode,
        (Convert-TestWslPath $platformRoot), (Convert-TestWslPath $inventoryPath), $platform.ansible_venv)
    if ($Mode -eq 'install') { $arguments += Convert-TestWslPath $VaultFile }
    elseif ($StaticDirectory) { $arguments += Convert-TestWslPath $StaticDirectory }
    & $wsl @arguments
    if ($LASTEXITCODE -ne 0) { throw "테스트 $Mode 단계가 실패했습니다: $LASTEXITCODE" }
}

switch ($Action) {
    { $_ -in @('Plan','Apply') } {
        if (-not $Stage) { throw 'Plan·Apply에는 -Stage를 지정하세요.' }
        Invoke-DeploymentStage $Stage $Action
    }
    'Inventory' { Write-DeploymentInventory }
    'Proxy' { Invoke-DeploymentProxy }
    'Front' { Invoke-TestBootstrap 'front' }
    'Install' { Invoke-TestBootstrap 'install' }
    { $_ -in @('Deploy','All') } {
        if ($Stage -or $Account -ne 'all') { throw 'Deploy는 전체 단계·모든 계정에 사용합니다. 일부 단계는 Plan·Apply를 사용하세요.' }
        if ($Action -eq 'All' -and (-not $VaultFile -or -not (Test-Path -LiteralPath $VaultFile -PathType Leaf))) { throw 'All에는 준비한 테스트 VaultFile이 필요합니다.' }
        # 하위 단계는 상위 단계의 원격 출력을 읽으므로 단계별 계획과 적용을 순서대로 진행한다.
        foreach ($deploymentStage in @('foundation','connectivity','workload','bastion')) {
            Invoke-DeploymentStage $deploymentStage 'Plan'
            $answer = Read-Host "$deploymentStage 계획을 검토하세요. 적용하려면 APPLY, 중단하려면 다른 값을 입력하세요"
            if ($answer -cne 'APPLY') { throw '요청에 따라 적용 전 중단했습니다. 앞 단계에서 적용한 자원은 유지됩니다.' }
            Invoke-DeploymentStage $deploymentStage 'Apply'
        }
        Write-DeploymentInventory
        Invoke-DeploymentProxy
        Invoke-TestBootstrap 'front'
        if ($Action -eq 'All') { Invoke-TestBootstrap 'install' }
    }
}
