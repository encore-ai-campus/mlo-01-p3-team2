#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('account1','account2','account3','account4','account5','shared')]
    [string]$Account = 'account1',
    [Parameter(Mandatory)]
    [ValidateSet('foundation','connectivity','workload')]
    [string]$Stage,
    [Parameter(Mandatory)]
    [ValidateSet('Validate','Test','Plan','Apply','Output')]
    [string]$Action,
    # 오프라인 검증 시 이미 설치된 provider 디렉터리를 사용할 수 있다.
    [string]$PluginDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib/infra-common.ps1')
# 설정·Terraform·로컬 작업 파일은 실행 폴더의 상위인 infra를 기준으로 찾는다.
$infraRoot = Split-Path -Parent $PSScriptRoot

if (($Stage -eq 'connectivity') -ne ($Account -eq 'shared')) {
    throw 'connectivity는 -Account shared, 나머지 단계는 account1~account5를 지정하세요.'
}
$stackPath = Join-Path $infraRoot "terraform/stacks/$Stage"
$workPath = Join-Path $infraRoot ".local/$Account/$Stage"
$null = New-Item -ItemType Directory -Path $workPath -Force
$planPath = Join-Path $workPath 'saved.tfplan'
$manifestPath = Join-Path $workPath 'saved-plan.json'
# 새 계획 시도가 실패했을 때 이전 계획을 잘못 적용하지 않게 한다.
if ($Action -eq 'Plan') {
    foreach ($path in @($planPath, $manifestPath)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
}
$topologyPath = Join-Path $infraRoot 'config/topology.tfvars.json'
$trafficPath = Join-Path $infraRoot 'config/traffic.tfvars.json'
$backendPath = Join-Path $infraRoot 'config/backend.json'
$topology = (Read-InfraJson $topologyPath).topology
$traffic = (Read-InfraJson $trafficPath).traffic
$backend = Read-InfraJson $backendPath
Assert-InfraConfiguration $topology $traffic
$stateKey = "$($backend.key_prefix)/$Account/$Stage/terraform.tfstate"
$publicKeyPath = $null
$publicKey = ''
if ($Account -ne 'shared' -and $Stage -eq 'workload') {
    $accountConfig = $topology.accounts.$Account
    if ($accountConfig.ssh_public_key_path) {
        $publicKeyPath = $accountConfig.ssh_public_key_path
        if (-not [IO.Path]::IsPathRooted($publicKeyPath)) {
            $publicKeyPath = Join-Path $infraRoot $publicKeyPath
        }
        if (Test-Path -LiteralPath $publicKeyPath -PathType Leaf) {
            $publicKey = [IO.File]::ReadAllText($publicKeyPath).Trim()
            if ($publicKey -notmatch '^(ssh-rsa|ssh-ed25519) [A-Za-z0-9+/=]+(?:\s|$)') {
                throw 'ssh_public_key_path에는 OpenSSH 공개키(.pub)만 지정하세요.'
            }
        }
    }
}
$isOnline = $Action -in @('Plan','Apply','Output')
if ($isOnline) {
    Assert-InfraBackend $backend $topology
    if ($Stage -eq 'workload' -and $Action -in @('Plan','Apply')) {
        if ($accountConfig.ami_id -notmatch '^ami-[0-9a-f]+$') { throw "$Account 의 ami_id를 채우세요." }
        if (-not $publicKey) { throw "$Account 의 ssh_public_key_path에 존재하는 공개키 파일을 지정하세요." }
        if ($topology.alb.enabled -and $topology.alb.account -eq $Account -and
            $topology.alb.certificate_arn -notmatch "^arn:aws:acm:$($topology.region):$($accountConfig.id):certificate/") {
            throw 'ALB 계정·리전에 맞는 ACM certificate_arn을 채우세요.'
        }
    }
}
$fingerprint = Get-InfraFingerprint $infraRoot $publicKeyPath
if ($Action -eq 'Apply') {
    if (-not (Test-Path -LiteralPath $manifestPath) -or -not (Test-Path -LiteralPath $planPath)) {
        throw '이 계정·단계의 저장 계획이 없습니다. 먼저 Plan을 실행하세요.'
    }
    $manifest = Read-InfraJson $manifestPath
    if ($manifest.account -ne $Account -or $manifest.stage -ne $Stage -or
        $manifest.state_key -ne $stateKey -or $manifest.fingerprint -ne $fingerprint -or
        $manifest.plan_sha256 -ne (Get-InfraFileHash $planPath)) {
        throw '저장 계획 이후 설정·코드·공개키·대상이 변경되었습니다. Plan을 다시 실행하세요.'
    }
}
$terraformCommand = (Get-Command terraform -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$environmentNames = @(
    'AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_SECURITY_TOKEN',
    'AWS_PROFILE','AWS_DEFAULT_PROFILE','AWS_REGION','AWS_DEFAULT_REGION',
    'AWS_ROLE_ARN','AWS_WEB_IDENTITY_TOKEN_FILE','AWS_ROLE_SESSION_NAME',
    'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI','AWS_CONTAINER_CREDENTIALS_FULL_URI',
    'AWS_CONTAINER_AUTHORIZATION_TOKEN','AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE',
    'AWS_EC2_METADATA_DISABLED','AWS_PAGER','TF_DATA_DIR','TF_WORKSPACE',
    'TF_INPUT','TF_IN_AUTOMATION','TF_CLI_ARGS','TF_CLI_ARGS_init','TF_CLI_ARGS_plan',
    'TF_CLI_ARGS_apply','TF_CLI_ARGS_output','TF_CLI_ARGS_validate','TF_CLI_ARGS_test'
)
$savedEnvironment = @{}
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
try {
    $env:AWS_EC2_METADATA_DISABLED = 'true'
    $env:AWS_PAGER = ''
    $env:TF_INPUT = '0'
    $env:TF_IN_AUTOMATION = '1'
    $env:TF_WORKSPACE = 'default'
    $env:TF_DATA_DIR = Join-Path $workPath $(if ($isOnline) { 'terraform' } else { 'validate-terraform' })
    if ($isOnline) {
        $awsCommand = (Get-Command aws -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
        $targetNames = if ($Account -eq 'shared') { @($topology.accounts.PSObject.Properties.Name) } else { @($Account) }
        # backend 프로필도 등록된 계정에 대응시켜 별도로 검증한다.
        $backendAccount = @($topology.accounts.PSObject.Properties | Where-Object { $_.Value.profile -eq $backend.profile })[0].Name
        foreach ($target in @(@($targetNames) + @($backendAccount) | Select-Object -Unique)) {
            $targetConfig = $topology.accounts.$target
            $identityText = & $awsCommand sts get-caller-identity --profile $targetConfig.profile --region $topology.region --output json --no-cli-pager
            if ($LASTEXITCODE -ne 0) { throw "$target 프로필 인증에 실패했습니다. aws configure --profile $($targetConfig.profile) 설정을 확인하세요." }
            $identity = ($identityText -join "`n") | ConvertFrom-Json
            if ($identity.Account -ne $targetConfig.id) {
                throw "$target 프로필의 실제 계정 $($identity.Account)이 설정 $($targetConfig.id)과 다릅니다."
            }
        }
        $versionText = & $awsCommand s3api get-bucket-versioning --bucket $backend.bucket --profile $backend.profile --region $backend.region --output json --no-cli-pager
        if ($LASTEXITCODE -ne 0) { throw '상태 버킷에 접근할 수 없습니다.' }
        $versioning = ($versionText -join "`n") | ConvertFrom-Json
        if (-not $versioning.PSObject.Properties['Status'] -or $versioning.Status -ne 'Enabled') {
            throw '상태 버킷의 S3 버전 관리를 먼저 활성화하세요.'
        }
    }
    $initArgs = @('init','-input=false','-no-color')
    if ($PluginDirectory) {
        $pluginPath = (Resolve-Path -LiteralPath $PluginDirectory).Path.Replace('\','/')
        $initArgs += "-plugin-dir=$pluginPath"
    }
    if ($isOnline) {
        $initArgs += @('-reconfigure', "-backend-config=bucket=$($backend.bucket)",
            "-backend-config=key=$stateKey", "-backend-config=region=$($backend.region)",
            "-backend-config=profile=$($backend.profile)", '-backend-config=encrypt=true', '-backend-config=use_lockfile=true')
    } else { $initArgs += '-backend=false' }
    Invoke-InfraTerraform $terraformCommand $stackPath $initArgs
    if ($Action -eq 'Validate') {
        Invoke-InfraTerraform $terraformCommand $stackPath @('validate','-no-color')
    } elseif ($Action -eq 'Test') {
        Invoke-InfraTerraform $terraformCommand $stackPath @('test','-no-color')
    } elseif ($Action -eq 'Plan') {
        $inputsPath = Join-Path $workPath 'runtime.tfvars.json'
        Write-InfraJson $inputsPath @{
            account_key = $(if ($Account -eq 'shared') { 'account1' } else { $Account })
            state_backend = $backend
            ssh_public_key = $publicKey
        }
        Invoke-InfraTerraform $terraformCommand $stackPath @(
            'plan','-input=false','-no-color','-lock-timeout=60s',
            "-var-file=$topologyPath", "-var-file=$trafficPath", "-var-file=$inputsPath", "-out=$planPath"
        )
        Write-InfraJson $manifestPath @{
            account = $Account; stage = $Stage; state_key = $stateKey
            fingerprint = (Get-InfraFingerprint $infraRoot $publicKeyPath)
            plan_sha256 = (Get-InfraFileHash $planPath)
            created_at = [DateTime]::UtcNow.ToString('o')
        }
        Write-Host "저장 계획: $planPath"
        Write-Host "검토 후 같은 대상에 -Action Apply를 실행하세요."
    } elseif ($Action -eq 'Apply') {
        # Terraform 저장 계획을 적용한다. 별도 자동 계획을 만들지 않는다.
        Invoke-InfraTerraform $terraformCommand $stackPath @('apply','-input=false','-no-color','-lock-timeout=60s',$planPath)
        Remove-Item -LiteralPath $planPath, $manifestPath
    } elseif ($Action -eq 'Output') {
        $outputText = & $terraformCommand "-chdir=$stackPath" output -json -no-color
        if ($LASTEXITCODE -ne 0) { throw 'Terraform 출력 조회에 실패했습니다.' }
        $outputPath = Join-Path $workPath 'outputs.json'
        [IO.File]::WriteAllText($outputPath, ($outputText -join "`n"), (New-Object Text.UTF8Encoding($false)))
        Write-Host "출력 저장: $outputPath"
    }
} finally {
    # 다른 PowerShell 작업에 인증·backend 환경을 남기지 않는다.
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
