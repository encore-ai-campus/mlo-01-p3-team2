#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('account1','account2','account3','account4','account5','shared')]
    [string]$Account = 'account1',
    [Parameter(Mandatory)]
    [ValidateSet('foundation','connectivity','workload','bastion')]
    [string]$Stage,
    [Parameter(Mandatory)]
    [ValidateSet('Validate','Test','Plan','Apply','Output')]
    [string]$Action,
    # 오프라인 검증 시 이미 설치된 provider 디렉터리를 사용할 수 있다.
    [string]$PluginDirectory,
    # 전체 삭제는 별도 실행 ID로 일반 배포 계획과 분리한다.
    [ValidateSet('Create','Delete')]
    [string]$PlanMode = 'Create',
    [ValidatePattern('^[0-9a-f]{32}$')]
    [string]$DestroyRunId,
    [switch]$DeleteDataVolumes,
    # 비용별 구성의 topology/traffic만 선택한다. backend와 공개키 상대 경로 기준은 기존 infra다.
    [string]$ConfigurationDirectory,
    [switch]$EdgeBootstrapOnly
)
$ErrorActionPreference = 'Stop'
# 초기 구축 삭제는 전체 삭제 실행 ID와 기존 승인 흐름을 통해서만 허용한다.
if ($EdgeBootstrapOnly -and ($Stage -ne 'workload' -or $Account -ne 'account1' -or $Action -notin @('Plan','Apply') -or
    ($PlanMode -eq 'Delete' -and (-not $DestroyRunId -or -not $DeleteDataVolumes)))) {
    throw 'EdgeBootstrapOnly는 account1 workload 생성 또는 전체 삭제 실행기의 Plan/Apply에만 사용합니다.'
}
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib/infra-common.ps1')
. (Join-Path $PSScriptRoot 'lib/infra-destroy.ps1')
# 설정·Terraform·로컬 작업 파일은 실행 폴더의 상위인 infra를 기준으로 찾는다.
$infraRoot = Split-Path -Parent $PSScriptRoot
if ($ConfigurationDirectory) {
    if ($PlanMode -eq 'Delete' -or $DestroyRunId) { throw '전체 삭제에는 별도 구성 선택을 사용하지 않습니다.' }
    $ConfigurationDirectory = (Resolve-Path -LiteralPath $ConfigurationDirectory -ErrorAction Stop).Path
}
$configurationRoot = if ($ConfigurationDirectory) { $ConfigurationDirectory } else { Join-Path $infraRoot 'config' }
if ($DestroyRunId) { Assert-InfraDestroyInvocation $infraRoot $DestroyRunId $Account $Stage $Action }

if (($Stage -eq 'connectivity') -ne ($Account -eq 'shared')) {
    throw 'connectivity는 -Account shared, 나머지 단계는 account1~account5를 지정하세요.'
}
if ($PlanMode -eq 'Delete' -and $Action -notin @('Plan','Apply')) {
    throw 'Delete 계획은 Plan·Apply에서만 사용할 수 있습니다.'
}
if (($DestroyRunId -and ($PlanMode -ne 'Delete' -or -not $DeleteDataVolumes)) -or
    ($PlanMode -eq 'Delete' -and $Stage -ne 'bastion' -and -not $DestroyRunId)) {
    throw '전체 삭제는 destroy-all.ps1의 실행 ID와 데이터 삭제 선택이 필요합니다.'
}
$stackPath = Join-Path $infraRoot "terraform/stacks/$Stage"
$workPath = Get-InfraWorkPath $infraRoot $Account $Stage $ConfigurationDirectory
if ($DestroyRunId) { $workPath = Join-Path $infraRoot ".local/destroy-all/$DestroyRunId/$Account/$Stage" }
$null = New-Item -ItemType Directory -Path $workPath -Force
$planPath = Join-Path $workPath 'saved.tfplan'
$manifestPath = Join-Path $workPath 'saved-plan.json'
# 새 계획 시도가 실패했을 때 이전 계획을 잘못 적용하지 않게 한다.
if ($Action -eq 'Plan') {
    foreach ($path in @($planPath, $manifestPath)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
}
$topologyPath = Join-Path $configurationRoot 'topology.tfvars.json'
$trafficPath = Join-Path $configurationRoot 'traffic.tfvars.json'
$backendPath = Join-Path $infraRoot 'config/backend.json'
$topology = (Read-InfraJson $topologyPath).topology
$traffic = (Read-InfraJson $trafficPath).traffic
$backend = Read-InfraJson $backendPath
Assert-InfraConfiguration $topology $traffic
if ($Stage -eq 'bastion' -and ($Account -ne 'account1' -or $topology.nodes.bastion.account -ne $Account)) {
    throw 'bastion 단계는 topology.nodes.bastion에 지정한 account1에서만 실행하세요.'
}
$stateKey = "$($backend.key_prefix)/$Account/$Stage/terraform.tfstate"
$publicKeyPath = $null
$publicKey = ''
if ($Account -ne 'shared' -and $Stage -in @('workload','bastion')) {
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
    if ($Stage -in @('workload','bastion') -and $PlanMode -eq 'Create' -and $Action -in @('Plan','Apply')) {
        if ($accountConfig.ami_id -notmatch '^ami-[0-9a-f]+$') { throw "$Account 의 ami_id를 채우세요." }
        if (-not $publicKey) { throw "$Account 의 ssh_public_key_path에 존재하는 공개키 파일을 지정하세요." }
    }
    if ($Stage -eq 'bastion' -and $Action -eq 'Plan' -and $PlanMode -eq 'Create' -and @($traffic.admin_public_cidrs).Count -eq 0) {
        Write-Warning 'admin_public_cidrs가 비어 있어 외부 SSH는 허용되지 않습니다. IP 설정과 workload 보안규칙 적용은 별도입니다.'
    }
}
$fingerprint = Get-InfraFingerprint $infraRoot $publicKeyPath $ConfigurationDirectory
if ($Action -eq 'Apply') {
    if (-not (Test-Path -LiteralPath $manifestPath) -or -not (Test-Path -LiteralPath $planPath)) {
        throw '이 계정·단계의 저장 계획이 없습니다. 먼저 Plan을 실행하세요.'
    }
    $manifest = Read-InfraJson $manifestPath
    $savedEdgeMode = $manifest.PSObject.Properties['edge_bootstrap_only'] -and [bool]$manifest.edge_bootstrap_only
    if ([bool]$savedEdgeMode -ne [bool]$EdgeBootstrapOnly) { throw '저장 계획의 EdgeBootstrapOnly 모드가 다릅니다. Plan부터 다시 실행하세요.' }
    if (-not $manifest.PSObject.Properties['plan_mode'] -or $manifest.plan_mode -ne $PlanMode) {
        throw '생성·삭제 계획 종류가 다릅니다. 해당 Plan부터 다시 실행하세요.'
    }
    if ($DestroyRunId -and ($manifest.destroy_run_id -ne $DestroyRunId -or -not $manifest.delete_data_volumes)) {
        throw '전체 삭제 실행 ID 또는 데이터 삭제 선택이 다릅니다.'
    }
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
    'TF_CLI_ARGS_apply','TF_CLI_ARGS_output','TF_CLI_ARGS_validate','TF_CLI_ARGS_test','TF_CLI_ARGS_show',
    'AWS_ENDPOINT_URL','AWS_ENDPOINT_URL_EC2','AWS_ENDPOINT_URL_STS','AWS_ENDPOINT_URL_S3',
    'AWS_IGNORE_CONFIGURED_ENDPOINT_URLS'
)
$savedEnvironment = Save-InfraEnvironment $environmentNames
try {
    $env:AWS_EC2_METADATA_DISABLED = 'true'
    $env:AWS_PAGER = ''
    $env:AWS_IGNORE_CONFIGURED_ENDPOINT_URLS = 'true'
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
    function Get-SavedDeleteSummary {
        $deletePlan = Read-InfraTerraformPlan $terraformCommand $stackPath $planPath '저장된 삭제 계획을 읽지 못했습니다.'
        return @(Assert-InfraDeletePlan $deletePlan $Stage $Account $topology -DeleteDataVolumes:$DeleteDataVolumes)
    }
    # Plan 직후와 Apply 직전에 같은 자원 범위·기존 Bastion 중복 여부를 검사한다.
    function Assert-SavedBastionPlan {
        $plan = Read-InfraTerraformPlan $terraformCommand $stackPath $planPath 'Bastion 저장 계획을 읽지 못했습니다.'
        Assert-InfraBastionPlan $plan $PlanMode $Account $topology.project
        $ownedIds = @()
        if ($plan.PSObject.Properties['resource_changes']) {
            $ownedIds = @($plan.resource_changes | Where-Object {
                $_.address -eq 'module.bastion.aws_instance.this' -and $_.change.before
            } | ForEach-Object { $_.change.before.id })
        }
        $existingText = & $awsCommand ec2 describe-instances --profile $accountConfig.profile --region $topology.region --output json --no-cli-pager --filters `
            "Name=tag:Project,Values=$($topology.project)" "Name=tag:Account,Values=$Account" `
            'Name=tag:Layout,Values=v2' 'Name=tag:ManagedBy,Values=Terraform' `
            'Name=tag:Node,Values=bastion' 'Name=tag:Role,Values=bastion' `
            'Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down'
        if ($LASTEXITCODE -ne 0) { throw '기존 Bastion 확인에 실패했습니다.' }
        $existing = ($existingText -join "`n") | ConvertFrom-Json
        foreach ($instance in @($existing.Reservations | ForEach-Object { $_.Instances })) {
            if ($instance.InstanceId -notin $ownedIds) {
                throw '전용 상태가 소유하지 않은 기존 Bastion이 있습니다. 기존 workload의 Bastion·EIP 처리 계획을 먼저 확인하세요.'
            }
        }
    }
    # 모드가 기존 노드를 제거하는 용도로 사용되지 않도록 Plan과 Apply에서 모두 검사한다.
    function Assert-SavedEdgePlan {
        $edgePlan = Read-InfraTerraformPlan $terraformCommand $stackPath $planPath '진입 서버 저장 계획을 읽지 못했습니다.'
        foreach ($change in @($edgePlan.resource_changes)) {
            if ('delete' -in @($change.change.actions)) { throw '진입 서버 초기 구축에서는 기존 자원 삭제·교체를 허용하지 않습니다.' }
            if ($change.type -eq 'aws_instance' -and ($change.address -ne 'module.compute.aws_instance.this["edge-1"]' -or $change.change.after.instance_type -ne 't3a.small')) {
                throw '진입 서버 초기 구축 계획에 edge-1(t3a.small) 외 EC2가 있습니다.'
            }
        }
    }
    if ($Action -eq 'Validate') {
        Invoke-InfraTerraform $terraformCommand $stackPath @('validate','-no-color')
    } elseif ($Action -eq 'Test') {
        Invoke-InfraTerraform $terraformCommand $stackPath @('test','-no-color')
    } elseif ($Action -eq 'Plan') {
        $inputsPath = Join-Path $workPath 'runtime.tfvars.json'
        $runtimeInputs = @{
            account_key = $(if ($Account -eq 'shared') { 'account1' } else { $Account })
            state_backend = $backend
            ssh_public_key = $publicKey
        }
        if ($Stage -eq 'workload') { $runtimeInputs['edge_bootstrap_only'] = [bool]$EdgeBootstrapOnly }
        Write-InfraJson $inputsPath $runtimeInputs
        $planArgs = @(
            'plan','-input=false','-no-color','-lock-timeout=60s',
            "-var-file=$topologyPath", "-var-file=$trafficPath", "-var-file=$inputsPath", "-out=$planPath"
        )
        if ($PlanMode -eq 'Delete') { $planArgs += '-destroy' }
        Invoke-InfraTerraform $terraformCommand $stackPath $planArgs
        if ($Stage -eq 'bastion') { Assert-SavedBastionPlan }
        if ($EdgeBootstrapOnly -and $PlanMode -eq 'Create') { Assert-SavedEdgePlan }
        if ($PlanMode -eq 'Delete') {
            $deleteSummary = @(Get-SavedDeleteSummary)
            Write-InfraJson (Join-Path $workPath 'delete-summary.json') @{ resources = $deleteSummary }
        }
        Write-InfraJson $manifestPath @{
            account = $Account; stage = $Stage; state_key = $stateKey
            fingerprint = (Get-InfraFingerprint $infraRoot $publicKeyPath $ConfigurationDirectory)
            plan_sha256 = (Get-InfraFileHash $planPath)
            edge_bootstrap_only = [bool]$EdgeBootstrapOnly
            plan_mode = $PlanMode
            destroy_run_id = $DestroyRunId
            delete_data_volumes = [bool]$DeleteDataVolumes
            created_at = [DateTime]::UtcNow.ToString('o')
        }
        Write-Host "저장 계획: $planPath"
        $edgeApplyHint = if ($EdgeBootstrapOnly) { " -EdgeBootstrapOnly" } else { "" }
        Write-Host "검토 후 같은 대상에 -Action Apply -PlanMode $PlanMode$edgeApplyHint 를 실행하세요."
    } elseif ($Action -eq 'Apply') {
        if ($Stage -eq 'bastion') { Assert-SavedBastionPlan }
        if ($EdgeBootstrapOnly -and $PlanMode -eq 'Create') { Assert-SavedEdgePlan }
        if ($PlanMode -eq 'Delete') { $null = @(Get-SavedDeleteSummary) }
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
    Restore-InfraEnvironment $environmentNames $savedEnvironment
}
