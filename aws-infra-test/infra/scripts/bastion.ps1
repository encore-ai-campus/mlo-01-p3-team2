#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Status','Output','Stop','Start','Restart','PlanCreate','Create','PlanDelete','Delete')]
    [string]$Action,
    [ValidateRange(1,3600)]
    [int]$TimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib/infra-common.ps1')

function Invoke-BastionAws {
    param([string[]]$Arguments, [switch]$DryRun)
    $cliArguments = @($Arguments) + @(
        '--profile', $bastionProfile, '--region', $bastionRegion,
        '--output', 'json', '--no-cli-pager', '--no-cli-auto-prompt',
        '--cli-connect-timeout', '5', '--cli-read-timeout', '20'
    )
    if ($DryRun) { $cliArguments += '--dry-run' }
    # PowerShell 5.1의 네이티브 stderr도 수집한 뒤 AWS 종료 코드로 판정한다.
    $ErrorActionPreference = 'Continue'
    $outputLines = & $awsCommand @cliArguments 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $outputText = ($outputLines | ForEach-Object { $_.ToString() }) -join "`n"
    if ($DryRun) {
        # AWS의 권한 검사 성공은 종료 코드 0이 아닌 DryRunOperation 오류로 온다.
        if ($code -ne 0 -and $outputText -match '\(DryRunOperation\)') { return }
        throw "AWS 권한 검사 실패 ($($Arguments[1])): $outputText"
    }
    if ($code -ne 0) { throw "AWS $($Arguments[0]) $($Arguments[1]) 실패 (종료 코드 $code): $outputText" }
    return ($outputText | ConvertFrom-Json)
}

function Get-BastionInstance {
    param([string]$InstanceId, [switch]$AllowMissing)
    $arguments = @('ec2','describe-instances')
    if ($InstanceId) {
        # 작업 도중에는 최초에 확정한 ID만 사용한다. 다른 서버를 다시 선택하지 않는다.
        $arguments += @('--instance-ids', $InstanceId)
    } else {
        $arguments += @('--filters',
            "Name=tag:Project,Values=$bastionProject",
            "Name=tag:Account,Values=$bastionAccount",
            'Name=tag:Layout,Values=v2', 'Name=tag:ManagedBy,Values=Terraform',
            'Name=tag:Node,Values=bastion', 'Name=tag:Role,Values=bastion',
            'Name=instance-state-name,Values=pending,running,stopping,stopped'
        )
    }
    $response = Invoke-BastionAws -Arguments $arguments
    $instances = @($response.Reservations | ForEach-Object { $_.Instances })
    if ($instances.Count -eq 0 -and $AllowMissing) { return $null }
    if ($instances.Count -ne 1) {
        throw "배스천 대상은 정확히 1대여야 합니다. 조회 결과: $($instances.Count)대. 배포 상태와 v2 태그를 확인하세요."
    }
    $instance = $instances[0]
    if ($instance.InstanceId -notmatch '^i-[0-9a-f]+$' -or
        ($InstanceId -and $instance.InstanceId -ne $InstanceId)) {
        throw '조회한 배스천 인스턴스 ID가 올바르지 않습니다.'
    }
    return [pscustomobject]@{
        Id = $instance.InstanceId
        State = $instance.State.Name
        RootDeviceType = $instance.RootDeviceType
        PublicIp = $(if ($instance.PSObject.Properties['PublicIpAddress']) { $instance.PublicIpAddress } else { $null })
        PrivateIp = $(if ($instance.PSObject.Properties['PrivateIpAddress']) { $instance.PrivateIpAddress } else { $null })
    }
}

function Get-BastionHealth {
    $response = Invoke-BastionAws -Arguments @(
        'ec2','describe-instance-status','--instance-ids',$bastionInstanceId,'--include-all-instances'
    )
    $statuses = @($response.InstanceStatuses)
    if ($statuses.Count -eq 0) {
        return [pscustomobject]@{ System = 'not-reported'; Instance = 'not-reported' }
    }
    if ($statuses.Count -ne 1 -or $statuses[0].InstanceId -ne $bastionInstanceId) {
        throw '배스천 상태 검사 응답의 대상이 일치하지 않습니다.'
    }
    return [pscustomobject]@{
        System = $statuses[0].SystemStatus.Status
        Instance = $statuses[0].InstanceStatus.Status
    }
}

function Wait-BastionState {
    param(
        [ValidateSet('Stable','Stopped','Ready')][string]$Condition,
        [DateTime]$Deadline
    )
    $lastState = ''
    while ($true) {
        $instance = Get-BastionInstance -InstanceId $bastionInstanceId
        if ($instance.State -notin @('pending','running','stopping','stopped')) {
            throw "배스천 $bastionInstanceId 은 작업할 수 없는 상태입니다: $($instance.State)"
        }
        if ($instance.State -ne $lastState) {
            Write-Host "배스천 $bastionInstanceId 상태: $($instance.State)"
            $lastState = $instance.State
        }
        if ($Condition -eq 'Stable' -and $instance.State -in @('running','stopped')) { return $instance }
        if ($Condition -eq 'Stopped' -and $instance.State -eq 'stopped') { return $instance }
        $healthText = ''
        if ($Condition -eq 'Ready' -and $instance.State -eq 'running') {
            $health = Get-BastionHealth
            if ($health.System -eq 'ok' -and $health.Instance -eq 'ok') { return $instance }
            $healthText = ", system=$($health.System), instance=$($health.Instance)"
        }
        if ([DateTime]::UtcNow -ge $Deadline) {
            throw "배스천 $bastionInstanceId 대기 시간 초과 ($Condition). 마지막 상태: $($instance.State)$healthText. Status로 다시 확인하세요."
        }
        $delay = [int][Math]::Min(5000, [Math]::Max(1, ($Deadline - [DateTime]::UtcNow).TotalMilliseconds))
        Start-Sleep -Milliseconds $delay
    }
}

function Set-BastionPower {
    param([ValidateSet('Start','Stop')][string]$Operation)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $instance = Wait-BastionState -Condition Stable -Deadline $deadline
    $targetState = if ($Operation -eq 'Start') { 'running' } else { 'stopped' }
    if ($instance.State -ne $targetState) {
        if ([DateTime]::UtcNow -ge $deadline) { throw "배스천 $Operation 대기 시간이 초과되어 변경 요청을 보내지 않았습니다." }
        $verb = if ($Operation -eq 'Start') { 'start-instances' } else { 'stop-instances' }
        # Stop은 AWS의 기본 OS 종료 절차를 사용한다. 강제 종료로 재시도하지 않는다.
        $null = Invoke-BastionAws -Arguments @('ec2',$verb,'--instance-ids',$bastionInstanceId)
    }
    $condition = if ($Operation -eq 'Start') { 'Ready' } else { 'Stopped' }
    return (Wait-BastionState -Condition $condition -Deadline $deadline)
}

function Test-BastionSshPort {
    param([string]$Address, [int]$Port)
    if (-not $Address) { return 'NoPublicIp' }
    $client = New-Object Net.Sockets.TcpClient
    $connection = $null
    try {
        $connection = $client.BeginConnect($Address, $Port, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(3000)) { return 'Unreachable' }
        $client.EndConnect($connection)
        return 'PortOpen'
    } catch {
        return 'Unreachable'
    } finally {
        $client.Close()
        if ($null -ne $connection) { $connection.AsyncWaitHandle.Close() }
    }
}

# 실행 위치와 관계없이 공통 설정을 읽는다. 생성·삭제의 상태 관리는 공통 실행기에 위임한다.
$infraRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib/test-isolation.ps1')
Assert-TestIsolation $infraRoot
$topology = (Read-InfraJson (Join-Path $infraRoot 'config/topology.tfvars.json')).topology
$traffic = (Read-InfraJson (Join-Path $infraRoot 'config/traffic.tfvars.json')).traffic
$bastionAccount = $topology.nodes.bastion.account
$accountConfig = $topology.accounts.$bastionAccount
$bastionProject = $topology.project
$bastionRegion = $topology.region
$bastionProfile = $accountConfig.profile
$sshPort = $traffic.ports.ssh
if ($topology.nodes.bastion.role -ne 'bastion' -or $bastionAccount -notmatch '^account[1-5]$' -or
    $accountConfig.id -notmatch '^\d{12}$' -or [string]::IsNullOrWhiteSpace($bastionProfile) -or
    $bastionRegion -ne 'ap-northeast-2' -or $bastionProject -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$' -or
    $sshPort -lt 1 -or $sshPort -gt 65535 -or [Math]::Floor($sshPort) -ne $sshPort) {
    throw 'topology의 배스천·계정·프로필·서울 리전과 traffic.ports.ssh 설정을 확인하세요.'
}
if ($Action -in @('PlanCreate','Create','PlanDelete','Delete')) {
    $planMode = if ($Action -in @('PlanDelete','Delete')) { 'Delete' } else { 'Create' }
    $infraAction = if ($Action -in @('PlanCreate','PlanDelete')) { 'Plan' } else { 'Apply' }
    if ($Action -eq 'Delete') {
        Write-Warning '검토한 저장 계획으로 Bastion EC2·OS 디스크·전용 키페어를 삭제합니다. SSH·Proxy 연결이 종료됩니다.'
    }
    & (Join-Path $PSScriptRoot 'infra.ps1') -Account $bastionAccount -Stage bastion -Action $infraAction -PlanMode $planMode
    if ($infraAction -eq 'Plan') { return }
    # 적용 이후에는 AWS에서 현재 주소를 조회한다. 이전 Terraform 출력의 주소를 재사용하지 않는다.
}
$awsCommand = (Get-Command aws -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$environmentNames = @(
    'AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_SECURITY_TOKEN',
    'AWS_PROFILE','AWS_DEFAULT_PROFILE','AWS_REGION','AWS_DEFAULT_REGION',
    'AWS_ROLE_ARN','AWS_WEB_IDENTITY_TOKEN_FILE','AWS_ROLE_SESSION_NAME',
    'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI','AWS_CONTAINER_CREDENTIALS_FULL_URI',
    'AWS_CONTAINER_AUTHORIZATION_TOKEN','AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE',
    'AWS_EC2_METADATA_DISABLED','AWS_PAGER','AWS_CLI_AUTO_PROMPT','AWS_MAX_ATTEMPTS',
    'AWS_ENDPOINT_URL','AWS_ENDPOINT_URL_EC2','AWS_ENDPOINT_URL_STS','AWS_IGNORE_CONFIGURED_ENDPOINT_URLS'
)
$savedEnvironment = @{}
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
try {
    $env:AWS_EC2_METADATA_DISABLED = 'true'
    $env:AWS_PAGER = ''
    $env:AWS_CLI_AUTO_PROMPT = 'off'
    $env:AWS_MAX_ATTEMPTS = '2'
    $env:AWS_IGNORE_CONFIGURED_ENDPOINT_URLS = 'true'
    $identity = Invoke-BastionAws -Arguments @('sts','get-caller-identity')
    if ($identity.Account -ne $accountConfig.id) {
        throw "AWS 프로필 $bastionProfile 의 실제 계정 $($identity.Account)이 설정 $($accountConfig.id)과 다릅니다."
    }
    $instance = Get-BastionInstance -AllowMissing
    if (-not $instance) {
        if ($Action -notin @('Status','Output','Delete')) { throw 'Bastion이 없습니다. PlanCreate 검토 후 Create를 실행하세요.' }
        [pscustomobject]@{
            Action = $Action; Account = $bastionAccount; Region = $bastionRegion
            InstanceId = $null; State = 'Absent'; PublicIp = $null; PrivateIp = $null
            SshPort = $sshPort; SshCommand = $null; ProxyEndpoint = $null
        }
        return
    }
    $bastionInstanceId = $instance.Id
    Write-Host "대상: $bastionAccount / $bastionRegion / $bastionInstanceId / $($instance.State)"
    if ($Action -in @('Stop','Start','Restart') -and $instance.RootDeviceType -ne 'ebs') {
        throw '배스천 중지·시작에는 EBS 루트 볼륨이 필요합니다.'
    }
    if ($Action -in @('Stop','Restart')) {
        Write-Warning '배스천 중지는 SSH 세션·터널과 이 서버를 사용하는 Forward Proxy 연결을 끊습니다.'
    }
    if ($Action -eq 'Restart') {
        # 중지한 뒤 시작 권한이 없음을 발견하지 않도록 양쪽 권한을 먼저 확인한다.
        Invoke-BastionAws -Arguments @('ec2','start-instances','--instance-ids',$bastionInstanceId) -DryRun
        Invoke-BastionAws -Arguments @('ec2','stop-instances','--instance-ids',$bastionInstanceId) -DryRun
        $null = Set-BastionPower -Operation Stop
        $instance = Set-BastionPower -Operation Start
    } elseif ($Action -in @('Start','Stop')) {
        $instance = Set-BastionPower -Operation $Action
    }
    $health = Get-BastionHealth
    $sshTcp = 'NotChecked'
    if ($instance.State -eq 'running') {
        # TCP 연결 여부만 확인한다. 키 인증이나 Proxy 서비스 복구를 보증하지 않는다.
        $sshTcp = Test-BastionSshPort -Address $instance.PublicIp -Port $sshPort
        if ($sshTcp -ne 'PortOpen') {
            Write-Warning "EC2 상태와 SSH 도달 여부는 별개입니다. SSH TCP: $sshTcp. 공인 IP·관리자 CIDR·SSH 서비스를 확인하세요."
        }
    }
    [pscustomobject]@{
        Action = $Action; Account = $bastionAccount; Region = $bastionRegion
        InstanceId = $bastionInstanceId; State = $instance.State
        SystemStatus = $health.System; InstanceStatus = $health.Instance
        PublicIp = $instance.PublicIp; PrivateIp = $instance.PrivateIp
        SshPort = $sshPort; SshTcp = $sshTcp
        SshCommand = $(if ($instance.PublicIp) { "ssh -p $sshPort -i <개인키_경로> ubuntu@$($instance.PublicIp)" } else { $null })
        ProxyEndpoint = $(if ($instance.PrivateIp) { "http://$($instance.PrivateIp):$($traffic.ports.proxy)" } else { $null })
    }
} finally {
    # 성공·실패 여부와 관계없이 호출한 PowerShell의 AWS 환경을 복원한다.
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
