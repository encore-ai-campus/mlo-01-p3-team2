#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Plan','Apply','Status','Verify','Destroy')]
    [string]$Action,
    [ValidatePattern('^[0-9a-f]{32}$')]
    [string]$RunId,
    [switch]$DeleteDataVolumes,
    [switch]$DisableDataVolumeProtection,
    [string]$PluginDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib/infra-common.ps1')
. (Join-Path $PSScriptRoot 'lib/infra-destroy.ps1')
$infraRoot = Split-Path -Parent $PSScriptRoot
$runsRoot = Join-Path $infraRoot '.local/destroy-all'
if ($DisableDataVolumeProtection -and $Action -ne 'Destroy') {
    throw '-DisableDataVolumeProtection은 -Action Destroy에서만 사용할 수 있습니다.'
}
if ($Action -in @('Plan','Apply','Destroy') -and -not $DeleteDataVolumes) {
    throw '전체 삭제에는 데이터 EBS도 포함됩니다. -DeleteDataVolumes를 명시하세요.'
}
if ($Action -in @('Plan','Destroy')) {
    if ($RunId) { throw 'Plan·Destroy는 새 실행 ID를 생성합니다. -RunId를 생략하세요.' }
    $RunId = [Guid]::NewGuid().ToString('N')
} elseif (-not $RunId) { throw 'Plan에서 출력한 -RunId를 지정하세요.' }
$runPath = Join-Path $runsRoot $RunId
$runFile = Join-Path $runPath 'run.json'
$run = $null
if ($Action -notin @('Plan','Destroy')) {
    $run = Read-InfraJson $runFile
    if ($run.run_id -ne $RunId) { throw '실행 ID가 일치하지 않습니다.' }
    if ($Action -eq 'Status') {
        Write-Host "실행 ID: $RunId / 상태: $($run.status)"
        $run.steps | Select-Object account,stage,status,delete_count
        if ($run.error) { Write-Warning $run.error }
        return
    }
}
$topology = (Read-InfraJson (Join-Path $infraRoot 'config/topology.tfvars.json')).topology
$traffic = (Read-InfraJson (Join-Path $infraRoot 'config/traffic.tfvars.json')).traffic
$backend = Read-InfraJson (Join-Path $infraRoot 'config/backend.json')
Assert-InfraConfiguration $topology $traffic
Assert-InfraBackend $backend $topology
$awsCommand = (Get-Command aws -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$null = New-Item -ItemType Directory -Path $runsRoot -Force
# 같은 PC에서 계획·삭제 작업이 겹치지 않게 한다. S3 상태 잠금은 Terraform이 별도로 사용한다.
$operationLock = [IO.File]::Open((Join-Path $runsRoot 'operation.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$savedEnvironment = @{}
$names = @('AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_SECURITY_TOKEN',
    'AWS_PROFILE','AWS_DEFAULT_PROFILE','AWS_REGION','AWS_DEFAULT_REGION','AWS_ROLE_ARN','AWS_WEB_IDENTITY_TOKEN_FILE',
    'AWS_ROLE_SESSION_NAME','AWS_CONTAINER_CREDENTIALS_RELATIVE_URI','AWS_CONTAINER_CREDENTIALS_FULL_URI',
    'AWS_CONTAINER_AUTHORIZATION_TOKEN','AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE','AWS_EC2_METADATA_DISABLED',
    'AWS_ENDPOINT_URL','AWS_ENDPOINT_URL_EC2','AWS_ENDPOINT_URL_STS','AWS_ENDPOINT_URL_S3','AWS_ENDPOINT_URL_ELASTIC_LOAD_BALANCING_V2',
    'AWS_IGNORE_CONFIGURED_ENDPOINT_URLS','AWS_PAGER','AWS_CLI_AUTO_PROMPT','AWS_MAX_ATTEMPTS')
foreach ($name in $names) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
function Save-DestroyRun {
    # 중단되더라도 마지막으로 완성된 진행 기록을 읽을 수 있게 교체한다.
    $temporary = Join-Path $runPath 'run.tmp.json'
    Write-InfraJson $temporary $run
    if (Test-Path -LiteralPath $runFile) { [IO.File]::Replace($temporary, $runFile, (Join-Path $runPath 'run.previous.json')) }
    else { [IO.File]::Move($temporary, $runFile) }
}
function Set-DestroyDataProtection {
    # 지원하는 데이터 EBS 선언 하나만 변경하고 원본 바이트를 실행 폴더에 보관한다.
    $source = Join-Path $infraRoot 'terraform/modules/compute/main.tf'
    $original = [IO.File]::ReadAllBytes($source)
    $encoding = New-Object Text.UTF8Encoding($false, $true)
    $text = $encoding.GetString($original)
    $blocks = [regex]::Matches($text, '(?ms)^resource\s+"aws_ebs_volume"\s+"data"\s*\{.*?(?=^resource\s|\z)')
    if ($blocks.Count -ne 1) { throw '데이터 EBS 선언을 하나로 식별할 수 없어 보호 설정을 변경하지 않습니다.' }
    $settings = [regex]::Matches($blocks[0].Value, '(?m)^[ \t]*lifecycle[ \t]*\{[ \t]*prevent_destroy[ \t]*=[ \t]*(?<value>true|false)[ \t]*\}[ \t]*\r?$')
    if ($settings.Count -ne 1) { throw '지원하는 데이터 EBS lifecycle 형식이 아니므로 보호 설정을 변경하지 않습니다.' }
    $originalHash = Get-InfraFileHash $source
    $originalFingerprint = Get-InfraFingerprint $infraRoot $null
    if ($settings[0].Groups['value'].Value -eq 'false') {
        $run.data_protection = [pscustomobject]@{ state = 'AlreadyDisabled'; restore_required = $false }
        Save-DestroyRun
        return
    }
    $offset = $blocks[0].Index + $settings[0].Groups['value'].Index
    $modified = $encoding.GetBytes($text.Substring(0, $offset) + 'false' + $text.Substring($offset + 4))
    $backup = Join-Path $runPath 'data-protection.original.tf'
    $temporary = Join-Path $runPath 'data-protection.tmp'
    [IO.File]::WriteAllBytes($backup, $original)
    [IO.File]::WriteAllBytes($temporary, $modified)
    $run.data_protection = [pscustomobject]@{
        state = 'Prepared'; restore_required = $true; original_sha256 = $originalHash
        disabled_sha256 = (Get-InfraFileHash $temporary); original_fingerprint = $originalFingerprint
    }
    # 변경 전에 복구 정보를 저장한다. 강제 종료 후에도 원본 위치를 찾을 수 있다.
    Save-DestroyRun
    if ((Get-InfraFileHash $source) -ne $originalHash) { throw '보호 해제 준비 중 원본이 변경됐습니다.' }
    [IO.File]::Replace($temporary, $source, (Join-Path $runPath 'data-protection.replaced.tf'))
    $run.data_protection.state = 'Disabled'
    Save-DestroyRun
}
function Restore-DestroyDataProtection {
    if ($null -eq $run -or -not $run.PSObject.Properties['data_protection'] -or
        $null -eq $run.data_protection -or -not $run.data_protection.restore_required) { return }
    $source = Join-Path $infraRoot 'terraform/modules/compute/main.tf'
    $backup = Join-Path $runPath 'data-protection.original.tf'
    if ((Get-InfraFileHash $backup) -ne $run.data_protection.original_sha256) {
        throw "보호 설정 원본 사본이 변경됐습니다: $backup"
    }
    $currentHash = Get-InfraFileHash $source
    if ($currentHash -eq $run.data_protection.disabled_sha256) {
        $temporary = Join-Path $runPath 'data-protection.restore.tmp'
        [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($backup))
        [IO.File]::Replace($temporary, $source, (Join-Path $runPath 'data-protection.disabled.tf'))
    } elseif ($currentHash -ne $run.data_protection.original_sha256) {
        # 실행 중 다른 사람이 수정한 파일을 원본 사본으로 덮어쓰지 않는다.
        throw "보호 설정 파일에 외부 변경이 있어 자동 복원하지 않습니다. 원본 사본: $backup"
    }
    if ((Get-InfraFileHash $source) -ne $run.data_protection.original_sha256) { throw '데이터 EBS 보호 설정 복원 검사에 실패했습니다.' }
    $run.data_protection.state = 'Restored'
    $run.data_protection.restore_required = $false
    # 저장 Plan의 fingerprint는 유지하고 읽기 전용 Verify에만 복원 전 기준을 사용한다.
    $run.verification_fingerprint = $run.data_protection.original_fingerprint
    Save-DestroyRun
    if ((Get-InfraFingerprint $infraRoot $null) -ne $run.verification_fingerprint) {
        throw '보호 설정은 복원됐지만 실행 중 다른 코드·설정이 변경됐습니다.'
    }
}
try {
    $env:AWS_EC2_METADATA_DISABLED = 'true'
    $env:AWS_IGNORE_CONFIGURED_ENDPOINT_URLS = 'true'
    $env:AWS_PAGER = ''
    $env:AWS_CLI_AUTO_PROMPT = 'off'
    $env:AWS_MAX_ATTEMPTS = '2'
    foreach ($account in $topology.accounts.PSObject.Properties) {
        $identity = Invoke-InfraDestroyAws $awsCommand @('sts','get-caller-identity','--profile',$account.Value.profile,'--region',$topology.region)
        if ($identity.Account -ne $account.Value.id) { throw "$($account.Name)의 실제 계정이 설정과 다릅니다." }
    }
    $versioning = Invoke-InfraDestroyAws $awsCommand @('s3api','get-bucket-versioning','--bucket',$backend.bucket,'--profile',$backend.profile,'--region',$backend.region)
    if (-not $versioning.PSObject.Properties['Status'] -or $versioning.Status -ne 'Enabled') { throw '상태 버킷의 버전 관리가 Enabled여야 합니다.' }
    if ($Action -in @('Plan','Destroy')) {
        $null = New-Item -ItemType Directory -Path $runPath -Force
        $run = [pscustomobject]@{
            version = 1; run_id = $RunId; status = 'Planning'; error = ''
            created_at = [DateTime]::UtcNow.ToString('o'); fingerprint = (Get-InfraFingerprint $infraRoot $null)
            data_protection = $null; verification_fingerprint = ''
            delete_data_volumes = $true; steps = @(Get-InfraDestroyTargets | ForEach-Object {
                [pscustomobject]@{ account = $_.account; stage = $_.stage; status = 'Pending'; delete_count = 0
                    state_key = "$($backend.key_prefix)/$($_.account)/$($_.stage)/terraform.tfstate"
                    state_sha256 = ''; plan_sha256 = ''; manifest_sha256 = ''; summary_sha256 = '' }
            })
        }
        Save-DestroyRun
        Write-Host "전체 삭제 실행 ID: $RunId"
        if ($DisableDataVolumeProtection) {
            Set-DestroyDataProtection
            $run.fingerprint = Get-InfraFingerprint $infraRoot $null
            Save-DestroyRun
            Write-Host '데이터 EBS 보호를 명시적으로 해제하고 종료 시 원래 설정으로 복원합니다.'
        } else {
            Write-Host '데이터 디스크까지 삭제하는 계획입니다. prevent_destroy 설정은 변경하지 않습니다.'
        }
        foreach ($step in $run.steps) {
            $directory = Join-Path $runPath "$($step.account)/$($step.stage)"
            $state = Get-InfraDestroyState $awsCommand $backend $step.account $step.stage $directory
            $step.state_sha256 = $state.sha256
            if ($state.managed_count -eq 0) {
                $step.status = 'Skipped'
            } else {
                Write-Host "삭제 계획: $($step.account)/$($step.stage)"
                & (Join-Path $PSScriptRoot 'infra.ps1') -Account $step.account -Stage $step.stage -Action Plan `
                    -PlanMode Delete -DestroyRunId $RunId -DeleteDataVolumes -PluginDirectory $PluginDirectory
                $after = Get-InfraDestroyState $awsCommand $backend $step.account $step.stage $directory
                if ($after.sha256 -ne $step.state_sha256) { throw 'Plan 중 원격 상태가 변경됐습니다. 새 Plan이 필요합니다.' }
                $step.plan_sha256 = Get-InfraFileHash (Join-Path $directory 'saved.tfplan')
                $step.manifest_sha256 = Get-InfraFileHash (Join-Path $directory 'saved-plan.json')
                $step.summary_sha256 = Get-InfraFileHash (Join-Path $directory 'delete-summary.json')
                $summary = Read-InfraJson (Join-Path $directory 'delete-summary.json')
                $step.delete_count = @($summary.resources).Count
                $step.status = 'Planned'
            }
            Save-DestroyRun
        }
        Assert-InfraDestroyArtifacts $infraRoot $RunId $run $backend
        $run.status = 'Ready'
        Save-DestroyRun
        $run.steps | Select-Object account,stage,status,delete_count | Format-Table -AutoSize | Out-Host
        Write-Host "단계별 saved.tfplan과 delete-summary.json을 검토하세요: $runPath"
        if ($Action -eq 'Plan') {
            Write-Host ".\infra\scripts\destroy-all.ps1 -Action Apply -RunId $RunId -DeleteDataVolumes"
            return
        }
        Write-Host '모든 삭제 계획 검사를 통과했습니다. 지정한 데이터 삭제 선택에 따라 자동 적용합니다.'
    }
    if ($Action -in @('Apply','Destroy')) {
        if ($run.status -ne 'Ready') { throw '검토 가능한 전체 Plan이 아닙니다. 실패·중단 후에는 새 Plan을 만드세요.' }
        # 복원이 불가능한 상태임을 알면서 삭제를 시작하지 않도록 원본 사본도 검사한다.
        if ($Action -eq 'Destroy' -and $null -ne $run.data_protection -and $run.data_protection.restore_required -and
            (Get-InfraFileHash (Join-Path $runPath 'data-protection.original.tf')) -ne $run.data_protection.original_sha256) {
            throw '첫 삭제 전 보호 설정 원본 사본의 변조를 발견했습니다.'
        }
        Assert-InfraDestroyArtifacts $infraRoot $RunId $run $backend
        # 첫 삭제 전에 모든 상태와 계획을 검사한다. 뒤 단계 오류를 알고도 앞 단계를 지우지 않는다.
        foreach ($step in $run.steps) {
            $state = Get-InfraDestroyState $awsCommand $backend $step.account $step.stage (Join-Path $runPath "$($step.account)/$($step.stage)")
            if ($state.sha256 -ne $step.state_sha256) { throw "$($step.account)/$($step.stage) 상태가 Plan 이후 변경됐습니다." }
        }
        $run.status = 'Applying'
        Save-DestroyRun
        foreach ($step in $run.steps) {
            if ($step.status -eq 'Skipped') { continue }
            $directory = Join-Path $runPath "$($step.account)/$($step.stage)"
            $step.status = 'Applying'
            Save-DestroyRun
            & (Join-Path $PSScriptRoot 'infra.ps1') -Account $step.account -Stage $step.stage -Action Apply `
                -PlanMode Delete -DestroyRunId $RunId -DeleteDataVolumes -PluginDirectory $PluginDirectory
            $state = Get-InfraDestroyState $awsCommand $backend $step.account $step.stage $directory
            if ($state.managed_count -ne 0) { throw "$($step.account)/$($step.stage) 상태에 관리 자원이 남았습니다." }
            $step.status = 'Deleted'
            Save-DestroyRun
        }
        $run.status = 'Verifying'
        Save-DestroyRun
    } elseif ($run.status -notin @('Verifying','VerificationFailed','Complete')) {
        throw 'Verify는 모든 삭제 단계가 끝난 실행에서만 가능합니다.'
    }
    $verificationFingerprint = $run.fingerprint
    if ($Action -eq 'Verify' -and $run.PSObject.Properties['verification_fingerprint'] -and $run.verification_fingerprint) {
        $verificationFingerprint = $run.verification_fingerprint
    }
    if ($verificationFingerprint -ne (Get-InfraFingerprint $infraRoot $null)) { throw '검증 대상의 코드·설정이 변경됐습니다.' }
    $resources = @()
    foreach ($step in $run.steps) {
        $directory = Join-Path $runPath "$($step.account)/$($step.stage)"
        $state = Get-InfraDestroyState $awsCommand $backend $step.account $step.stage $directory
        if ($state.managed_count -ne 0) { throw "$($step.account)/$($step.stage) 상태가 비어 있지 않습니다." }
        if ($step.status -eq 'Deleted') {
            $summaryPath = Join-Path $directory 'delete-summary.json'
            if ((Get-InfraFileHash $summaryPath) -ne $step.summary_sha256) { throw '검증할 자원 목록이 변경됐습니다.' }
            $resources += @((Read-InfraJson $summaryPath).resources)
        }
    }
    $remaining = @(Test-InfraDeletedResources $awsCommand $topology $resources)
    Write-InfraJson (Join-Path $runPath 'verification.json') @{ checked_at = [DateTime]::UtcNow.ToString('o'); remaining = $remaining }
    if ($remaining.Count) { throw '삭제 계획에 있던 AWS 자원이 남아 있습니다. verification.json을 확인하세요.' }
    $run.status = 'Complete'
    $run.error = ''
    Save-DestroyRun
} catch {
    if (Test-Path -LiteralPath $runFile) {
        $run.error = $_.Exception.Message
        $run.status = if ($run.status -in @('Verifying','VerificationFailed','Complete')) { 'VerificationFailed' } else { 'Failed' }
        Save-DestroyRun
    }
    throw
} finally {
    $restoreError = $null
    try {
        Restore-DestroyDataProtection
    } catch {
        $restoreError = $_
        if ($null -ne $run) {
            $run.error = ($run.error + "`n보호 복원 오류: " + $_.Exception.Message).Trim()
            $run.status = 'ProtectionRestoreFailed'
            if ($null -ne $run.data_protection) { $run.data_protection.state = 'RestoreFailed' }
            Save-DestroyRun
        }
    } finally {
        foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
        $operationLock.Dispose()
    }
    if ($null -ne $restoreError) { throw $restoreError }
    if ($null -ne $run -and $run.status -eq 'Complete') {
        Write-Host "전체 삭제 검증 완료: $RunId (S3 상태 버킷·이력 유지)"
    }
}
