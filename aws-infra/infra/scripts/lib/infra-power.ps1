#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AwsCommand,
    [Parameter(Mandatory)][string]$TargetJson,
    [Parameter(Mandatory)][ValidateSet('Stop','Start')][string]$Operation,
    [Parameter(Mandatory)][ValidateSet('Check','Change')][string]$Mode,
    [ValidateRange(1,3600)][int]$TimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'infra-common.ps1')
$target = $TargetJson | ConvertFrom-Json
$records = @($target.Nodes)
$desiredState = if ($Operation -eq 'Start') { 'running' } else { 'stopped' }
$sourceState = if ($Operation -eq 'Start') { 'stopped' } else { 'running' }
$verb = if ($Operation -eq 'Start') { 'start-instances' } else { 'stop-instances' }

# 이 파일은 power-all.ps1의 자식 프로세스에서만 실행한다. 부모의 인증 환경은 바꾸지 않는다.
foreach ($name in @(
    'AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_SECURITY_TOKEN',
    'AWS_PROFILE','AWS_DEFAULT_PROFILE','AWS_REGION','AWS_DEFAULT_REGION',
    'AWS_ROLE_ARN','AWS_WEB_IDENTITY_TOKEN_FILE','AWS_ROLE_SESSION_NAME',
    'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI','AWS_CONTAINER_CREDENTIALS_FULL_URI',
    'AWS_CONTAINER_AUTHORIZATION_TOKEN','AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE',
    'AWS_ENDPOINT_URL','AWS_ENDPOINT_URL_EC2','AWS_ENDPOINT_URL_STS'
)) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
$env:AWS_EC2_METADATA_DISABLED = 'true'
$env:AWS_IGNORE_CONFIGURED_ENDPOINT_URLS = 'true'
$env:AWS_CLI_AUTO_PROMPT = 'off'
$env:AWS_PAGER = ''
$env:AWS_MAX_ATTEMPTS = '2'

function Invoke-PowerAws {
    param([string[]]$Arguments, [switch]$DryRun)
    $cliArguments = @($Arguments) + @(
        '--profile',$target.Profile,'--region',$target.Region,'--output','json',
        '--no-cli-pager','--no-cli-auto-prompt','--cli-connect-timeout','5','--cli-read-timeout','20'
    )
    if ($DryRun) { $cliArguments += '--dry-run' }
    # Windows PowerShell의 stderr 처리를 우회하고 AWS CLI 종료 코드로 판정한다.
    $result = Invoke-InfraCapturedCommand $AwsCommand $cliArguments
    $code = $result.ExitCode
    $outputText = $result.Text
    if ($DryRun) {
        if ($code -ne 0 -and $outputText -match '\(DryRunOperation\)') { return }
        throw "전원 권한 검사 실패: $outputText"
    }
    if ($code -ne 0) { throw "AWS $($Arguments[1]) 실패 (종료 코드 $code): $outputText" }
    return ($outputText | ConvertFrom-Json)
}

function Get-PowerInstances {
    $response = Invoke-PowerAws -Arguments (@('ec2','describe-instances','--instance-ids') + @($records.Id))
    $live = @{}
    foreach ($reservation in @($response.Reservations)) {
        if ($reservation.OwnerId -ne $target.AccountId) { throw 'EC2 소유 계정이 구성과 다릅니다.' }
        foreach ($instance in @($reservation.Instances)) {
            if ($instance.InstanceId -notin $records.Id -or $live.ContainsKey($instance.InstanceId)) {
                throw '조회 결과에 요청하지 않은 ID 또는 중복 ID가 있습니다.'
            }
            $live[$instance.InstanceId] = $instance
        }
    }
    foreach ($record in $records) {
        if (-not $live.ContainsKey($record.Id)) { throw "EC2가 없습니다: $($record.Name) / $($record.Id)" }
        $instance = $live[$record.Id]
        $tags = @{}
        foreach ($tag in @($instance.Tags)) { $tags[$tag.Key] = $tag.Value }
        if ($tags['Project'] -ne $target.Project -or $tags['Account'] -ne $target.Account -or
            $tags['ManagedBy'] -ne 'Terraform' -or $tags['Layout'] -ne 'v2' -or
            $tags['Node'] -ne $record.Name -or $tags['Role'] -ne $record.Role -or
            ($record.Role -eq 'bastion' -and $tags['Stage'] -ne 'bastion')) {
            throw "EC2 태그가 구성과 다릅니다: $($record.Name) / $($record.Id)"
        }
        if ($instance.RootDeviceType -ne 'ebs' -or
            $instance.State.Name -notin @('running','stopped','pending','stopping')) {
            throw "중지·시작할 수 없는 EC2입니다: $($record.Name) / $($instance.State.Name) / $($instance.RootDeviceType)"
        }
        [pscustomobject]@{
            Account = $target.Account; Name = $record.Name; Id = $record.Id; State = $instance.State.Name
            PrivateIp = $(if ($instance.PSObject.Properties['PrivateIpAddress']) { $instance.PrivateIpAddress } else { $null })
            PublicIp = $(if ($instance.PSObject.Properties['PublicIpAddress']) { $instance.PublicIpAddress } else { $null })
        }
    }
}

# 사전 검사와 실제 변경 프로세스에서 각각 인증 주체를 확인한다.
$identity = Invoke-PowerAws -Arguments @('sts','get-caller-identity')
if ($identity.Account -ne $target.AccountId) { throw "AWS 프로필 $($target.Profile)의 계정이 구성과 다릅니다." }
$instances = @(Get-PowerInstances)
if ($Mode -eq 'Check') {
    $changes = @($instances | Where-Object { $_.State -ne $desiredState })
    if ($changes.Count -gt 0) {
        Invoke-PowerAws -Arguments (@('ec2',$verb,'--instance-ids') + @($changes.Id)) -DryRun
    }
    return $instances
}

$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$requested = @{}
while ($true) {
    if (@($instances | Where-Object { $_.State -ne $desiredState }).Count -eq 0) { return $instances }
    if ([DateTime]::UtcNow -ge $deadline) {
        $states = ($instances | ForEach-Object { "$($_.Name)=$($_.State)" }) -join ', '
        throw "${Operation} 대기 시간 초과: $states. 강제 중지 없이 종료합니다."
    }
    # 반대 방향으로 전환 중인 서버는 안정 상태가 될 때까지 기다린다. 같은 요청을 반복 전송하지 않는다.
    $changes = @($instances | Where-Object { $_.State -eq $sourceState -and -not $requested.ContainsKey($_.Id) })
    if ($changes.Count -gt 0) {
        # OS의 기본 종료 절차를 사용한다. --force, --skip-os-shutdown, terminate는 사용하지 않는다.
        $null = Invoke-PowerAws -Arguments (@('ec2',$verb,'--instance-ids') + @($changes.Id))
        foreach ($instance in $changes) { $requested[$instance.Id] = $true }
    }
    $delay = [int][Math]::Min(3000, [Math]::Max(1, ($deadline - [DateTime]::UtcNow).TotalMilliseconds))
    Start-Sleep -Milliseconds $delay
    $instances = @(Get-PowerInstances)
}
