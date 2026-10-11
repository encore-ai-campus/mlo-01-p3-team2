#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProfileDirectory,
    [ValidateSet('NewProfile','Plan','Apply','Deploy','Inventory','Proxy')]
    [string]$Action = 'Plan',
    [ValidateSet('foundation','connectivity','workload','bastion')][string]$Stage,
    [ValidateSet('all','account1','account2','account3','account4','account5')]
    [string]$Account = 'all',
    [string]$Limit = 'all'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib/infra-common.ps1')
$infraRoot = Split-Path -Parent $PSScriptRoot
$platformRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $infraRoot)) 'aws-platform/platform'
$runner = Join-Path $PSScriptRoot 'infra.ps1'
$ProfileDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ProfileDirectory)

if ($Action -eq 'NewProfile') {
    # 기존 구성을 복사할 뿐 사양이나 계정 배치를 임의로 바꾸지 않는다.
    $profileName = Split-Path -Leaf $ProfileDirectory
    if ($profileName -notmatch '^[A-Za-z0-9_-]+$') { throw '구성 폴더 이름에는 영문·숫자·하이픈·밑줄을 사용하세요.' }
    $names = @('topology.tfvars.json','traffic.tfvars.json','platform.json')
    foreach ($name in $names) {
        if (Test-Path -LiteralPath (Join-Path $ProfileDirectory $name)) { throw "기존 구성은 덮어쓰지 않습니다: $name" }
    }
    $null = New-Item -ItemType Directory -Path $ProfileDirectory -Force
    foreach ($name in @('topology.tfvars.json','traffic.tfvars.json')) {
        Copy-Item -LiteralPath (Join-Path $infraRoot "config/$name") -Destination (Join-Path $ProfileDirectory $name)
    }
    $keyPaths = [ordered]@{}
    $sourceTopology = (Read-InfraJson (Join-Path $ProfileDirectory 'topology.tfvars.json')).topology
    foreach ($key in @($sourceTopology.accounts.PSObject.Properties.Name | Sort-Object)) {
        $filename = if ($key -eq 'account1') { 'project-bastion.pem' } else { "$key.pem" }
        $keyPaths[$key] = "{{ lookup('env', 'HOME') }}/.ssh/project-key/$filename"
    }
    Write-InfraJson (Join-Path $ProfileDirectory 'platform.json') ([ordered]@{
        inventory_name = "hosts.$profileName.yml"
        ssh_user = 'ubuntu'
        ssh_keys = $keyPaths
        role_groups = @{ mongo = 'mongodb' }
        wsl_distribution = 'Ubuntu'
        ansible_venv = '~/.venvs/platform'
    })
    Write-Host "구성 생성: $ProfileDirectory"
    Write-Host 'topology의 nodes에서 account·instance_type·노드 항목·디스크를 편집한 뒤 Plan을 실행하세요.'
    return
}

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
$inventoryPath = Join-Path $platformRoot "inventory/$($platform.inventory_name)"
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
        & $runner -ConfigurationDirectory $ProfileDirectory -Account $target -Stage $SelectedStage -Action $SelectedAction | Out-Host
    }
}

function Read-DeploymentOutput {
    param([string]$TargetAccount, [string]$TargetStage)
    & $runner -ConfigurationDirectory $ProfileDirectory -Account $TargetAccount -Stage $TargetStage -Action Output | Out-Host
    $workPath = Get-InfraWorkPath $infraRoot $TargetAccount $TargetStage $ProfileDirectory
    return Read-InfraJson (Join-Path $workPath 'outputs.json')
}

function Get-DeploymentTag {
    param($Instance, [string]$Name)
    return (@($Instance.Tags | Where-Object { $_.Key -eq $Name } | ForEach-Object { $_.Value }) -join '')
}

function Write-DeploymentInventory {
    $records = @()
    foreach ($key in $accountNames) {
        if (-not $platform.ssh_keys.PSObject.Properties[$key]) { throw "platform.json에 $key 의 WSL 개인키 경로를 지정하세요." }
        $output = Read-DeploymentOutput $key 'workload'
        $instances = @($output.inventory.value.instances.PSObject.Properties)
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
    $inventory = @{ all = @{ vars = @{ ansible_user = $platform.ssh_user; users = @(); proxy_enabled = $true }; children = @{} } }
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
        if ($record.Role -eq 'edge') {
            if (-not $instance.PSObject.Properties['PublicIpAddress'] -or -not $instance.PublicIpAddress) { throw '진입 서버의 EIP가 없습니다.' }
            $hostVars.public_ip = $instance.PublicIpAddress
            $hostVars.edge_https_allowed_cidrs = @($traffic.game_client_cidrs)
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

switch ($Action) {
    { $_ -in @('Plan','Apply') } {
        if (-not $Stage) { throw 'Plan·Apply에는 -Stage를 지정하세요.' }
        Invoke-DeploymentStage $Stage $Action
    }
    'Inventory' { Write-DeploymentInventory }
    'Proxy' { Invoke-DeploymentProxy }
    'Deploy' {
        if ($Stage -or $Account -ne 'all') { throw 'Deploy는 전체 단계·모든 계정에 사용합니다. 일부 단계는 Plan·Apply를 사용하세요.' }
        # 하위 단계는 상위 단계의 원격 출력을 읽으므로 단계별 계획과 적용을 순서대로 진행한다.
        foreach ($deploymentStage in @('foundation','connectivity','workload','bastion')) {
            Invoke-DeploymentStage $deploymentStage 'Plan'
            $answer = Read-Host "$deploymentStage 계획을 검토하세요. 적용하려면 APPLY, 중단하려면 다른 값을 입력하세요"
            if ($answer -cne 'APPLY') { throw '요청에 따라 적용 전 중단했습니다. 앞 단계에서 적용한 자원은 유지됩니다.' }
            Invoke-DeploymentStage $deploymentStage 'Apply'
        }
        Write-DeploymentInventory
        Invoke-DeploymentProxy
    }
}
