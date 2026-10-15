#Requires -Version 5.1
function Save-InfraEnvironment {
    param([string[]]$Names)
    # 호출부가 지정한 변수만 보관·해제해 작업별 인증 격리 범위를 유지한다.
    $saved = @{}
    foreach ($name in $Names) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    return $saved
}
function Restore-InfraEnvironment {
    param([string[]]$Names, [hashtable]$Saved)
    foreach ($name in $Names) {
        [Environment]::SetEnvironmentVariable($name, $Saved[$name], 'Process')
    }
}
function Invoke-InfraCapturedCommand {
    param([string]$Command, [string[]]$Arguments)
    # Windows PowerShell의 stderr도 수집한다. 성공·허용 오류 판단은 호출부가 맡는다.
    $ErrorActionPreference = 'Continue'
    $lines = & $Command @Arguments 2>&1
    $code = $LASTEXITCODE
    $text = ($lines | ForEach-Object { $_.ToString() }) -join "`n"
    return [pscustomobject]@{ ExitCode = $code; Text = $text }
}
function Read-InfraTerraformPlan {
    param([string]$Command, [string]$Directory, [string]$Path, [string]$FailureMessage)
    # 검사 시점마다 다시 읽어 Plan·Apply 사이의 재검증을 유지한다.
    $lines = & $Command "-chdir=$Directory" show -json $Path
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
    return (($lines -join "`n") | ConvertFrom-Json)
}
function Read-InfraJson {
    param([string]$Path)
    return ([IO.File]::ReadAllText($Path) | ConvertFrom-Json)
}
function Get-InfraFileHash {
    param([string]$Path)
    # 별도 PowerShell 모듈 없이 저장 계획과 코드의 SHA-256을 구한다.
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','') }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
function Write-InfraJson {
    param([string]$Path, $Value)
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 30), (New-Object Text.UTF8Encoding($false)))
}
function Invoke-InfraTerraform {
    param([string]$Command, [string]$Directory, [string[]]$Arguments)
    & $Command "-chdir=$Directory" @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Terraform $($Arguments[0]) 실패: 종료 코드 $LASTEXITCODE" }
}
function Assert-InfraConfiguration {
    param($Topology, $Traffic)
    $accounts = @($Topology.accounts.PSObject.Properties)
    if ((($accounts.Name | Sort-Object) -join ',') -ne 'account1,account2,account3,account4,account5') {
        throw 'topology에는 account1~account5를 정의하세요.'
    }
    if (@($accounts.Value.id | Select-Object -Unique).Count -ne 5 -or
        @($accounts.Value.profile | Select-Object -Unique).Count -ne 5 -or
        @($accounts.Value.vpc_cidr | Select-Object -Unique).Count -ne 5) {
        throw '계정 ID·프로필·VPC CIDR은 계정마다 달라야 합니다.'
    }
    foreach ($account in $accounts) {
        if ($account.Value.id -notmatch '^\d{12}$' -or -not $account.Value.profile) { throw '계정 ID·프로필이 올바르지 않습니다.' }
        if ($account.Value.vpc_cidr -notmatch '^(\d{1,3})\.(\d{1,3})\.0\.0/16$' -or
            [int]$Matches[1] -gt 255 -or [int]$Matches[2] -gt 255) { throw '서로 겹치지 않는 IPv4 /16 VPC CIDR을 지정하세요.' }
        if ($account.Value.egress -notin @('proxy','nat','none') -or
            ($account.Value.egress -eq 'nat' -and -not $account.Value.public_subnets)) { throw 'NAT에는 퍼블릭 서브넷이 필요합니다.' }
    }
    # HTTP 공개 범위도 동일한 IPv4 CIDR 검사를 적용한다.
    $httpCidrs = if ($Traffic.PSObject.Properties['public_http_cidrs']) { @($Traffic.public_http_cidrs) } else { @() }
    foreach ($cidr in @($Traffic.admin_public_cidrs) + @($Traffic.game_client_cidrs) + $httpCidrs) {
        if ($cidr -notmatch '^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/(\d{1,2})$') { throw "잘못된 IPv4 CIDR: $cidr" }
        $octets = @([int]$Matches[1],[int]$Matches[2],[int]$Matches[3],[int]$Matches[4])
        $prefix = [int]$Matches[5]
        if (@($octets | Where-Object { $_ -gt 255 }).Count -or $prefix -gt 32) { throw "잘못된 IPv4 CIDR: $cidr" }
        $address = [uint64]$octets[0] * 16777216 + [uint64]$octets[1] * 65536 + [uint64]$octets[2] * 256 + $octets[3]
        if (($address % [math]::Pow(2, 32 - $prefix)) -ne 0) { throw "CIDR은 네트워크 주소로 입력하세요: $cidr" }
    }
    if ('0.0.0.0/0' -in $Traffic.admin_public_cidrs) { throw '관리자 SSH에 0.0.0.0/0은 허용하지 않습니다.' }
    foreach ($port in $Traffic.ports.PSObject.Properties) {
        if ($port.Value -lt 1 -or $port.Value -gt 65535 -or [math]::Floor($port.Value) -ne $port.Value) {
            throw "TCP 포트 범위 오류: $($port.Name)"
        }
    }
}
function Assert-InfraBackend {
    param($Backend, $Topology)
    if ($Backend.bucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$' -or
        $Backend.key_prefix -notmatch '^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$' -or
        -not $Backend.region -or
        $Backend.profile -notin @($Topology.accounts.PSObject.Properties.Value.profile)) {
        throw 'infra/config/backend.json에 기존 버전 관리 S3 버킷·리전·등록 계정의 프로필·key_prefix를 채우세요.'
    }
}
function Get-InfraWorkPath {
    param([string]$Root, [string]$Account, [string]$Stage, [string]$ConfigurationDirectory)
    $basePath = Join-Path $Root '.local'
    $configurationPath = if ($ConfigurationDirectory) { [IO.Path]::GetFullPath($ConfigurationDirectory).TrimEnd('\','/') } else { '' }
    if ($configurationPath -and $configurationPath -ne (Join-Path $Root 'config')) {
        # 구성 이름이 같아도 경로가 다르면 저장 Plan을 공유하지 않는다. 원격 상태는 기존 경로를 유지한다.
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try {
            $bytes = [Text.Encoding]::UTF8.GetBytes($configurationPath.ToLowerInvariant())
            $profileId = ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace('-','').Substring(0,16)
        } finally { $algorithm.Dispose() }
        $basePath = Join-Path $basePath "profiles/$profileId"
    }
    return Join-Path $basePath "$Account/$Stage"
}
function Get-InfraFingerprint {
    param([string]$Root, [string]$PublicKeyPath, [string]$ConfigurationDirectory)
    # 로컬 캐시·계획·문서는 제외하고 실행 코드와 모든 공통 설정을 비교한다.
    $files = @(
        Get-ChildItem -LiteralPath (Join-Path $Root 'config') -File -Filter '*.json'
        Get-ChildItem -LiteralPath (Join-Path $Root 'terraform') -Recurse -File |
            Where-Object { $_.FullName -notmatch '[\\/]\.terraform[\\/]' -and ($_.Extension -eq '.tf' -or $_.Name -eq '.terraform.lock.hcl') }
        Get-Item -LiteralPath (Join-Path $Root 'scripts/infra.ps1')
        Get-Item -LiteralPath (Join-Path $Root 'scripts/bastion.ps1')
        Get-Item -LiteralPath (Join-Path $Root 'scripts/destroy-all.ps1')
        Get-ChildItem -LiteralPath (Join-Path $Root 'scripts/lib') -File -Filter '*.ps1'
    )
    $lines = @($files | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($Root.Length) + ':' + (Get-InfraFileHash $_.FullName)
    })
    if ($PublicKeyPath -and (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) {
        $lines += 'ssh_public_key:' + (Get-InfraFileHash $PublicKeyPath)
    }
    if ($ConfigurationDirectory) {
        foreach ($name in @('topology.tfvars.json','traffic.tfvars.json')) {
            $path = [IO.Path]::GetFullPath((Join-Path $ConfigurationDirectory $name))
            $lines += 'selected_configuration:' + $path + ':' + (Get-InfraFileHash $path)
        }
    }
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))))).Replace('-','') }
    finally { $algorithm.Dispose() }
}

function Assert-InfraBastionPlan {
    param($Plan, [ValidateSet('Create','Delete')][string]$Mode, [string]$Account, [string]$Project)
    # 다른 상태의 자원이나 의도하지 않은 교체 작업을 저장 계획으로 적용하지 않는다.
    $allowed = @('module.model.terraform_data.configuration', 'module.bastion.aws_instance.this',
        'module.bastion.aws_key_pair.this', 'module.bastion.aws_eip.this', 'module.bastion.aws_eip_association.this')
    $modules = @()
    if ($Plan.PSObject.Properties['planned_values'] -and $Plan.planned_values.PSObject.Properties['root_module']) {
        $modules += $Plan.planned_values.root_module
    }
    if ($Plan.PSObject.Properties['prior_state'] -and $Plan.prior_state -and
        $Plan.prior_state.PSObject.Properties['values'] -and $Plan.prior_state.values.PSObject.Properties['root_module']) {
        $modules += $Plan.prior_state.values.root_module
    }
    while ($modules.Count -gt 0) {
        $current = $modules[0]
        $modules = @($modules | Select-Object -Skip 1)
        if ($current.PSObject.Properties['child_modules']) { $modules += @($current.child_modules) }
        if ($current.PSObject.Properties['resources']) {
            foreach ($resource in $current.resources) {
                if ($resource.mode -eq 'managed' -and $resource.address -notin $allowed) {
                    throw "Bastion 전용 상태 밖의 자원이 포함되어 있습니다: $($resource.address)"
                }
            }
        }
    }
    if ($Plan.PSObject.Properties['deferred_changes'] -and @($Plan.deferred_changes).Count -gt 0) {
        throw '확정되지 않은 Bastion 변경이 있습니다. Plan을 다시 확인하세요.'
    }
    if (-not $Plan.PSObject.Properties['resource_changes']) { return }
    foreach ($resource in $Plan.resource_changes) {
        if ($resource.mode -ne 'managed') { continue }
        if ($resource.address -notin $allowed) { throw "Bastion 외의 변경은 허용하지 않습니다: $($resource.address)" }
        $actions = @($resource.change.actions)
        $permitted = if ($Mode -eq 'Delete') { @('no-op','delete') } else { @('no-op','create','update') }
        if (@($actions | Where-Object { $_ -notin $permitted }).Count -gt 0 -or
            ($resource.change.PSObject.Properties['importing'] -and $resource.change.importing)) {
            throw "Bastion $Mode 계획에 허용되지 않은 생성·삭제·교체·가져오기가 있습니다: $($resource.address)"
        }
        # 삭제 전 기존 자원도 전용 단계의 태그를 가져야 한다. 기존 workload 자원을 자동 이관하지 않는다.
        if ($resource.type -in @('aws_instance','aws_key_pair','aws_eip') -and $resource.change.before) {
            $before = $resource.change.before
            if (-not $before.PSObject.Properties['tags_all'] -or -not $before.tags_all -or
                -not $before.tags_all.PSObject.Properties['Stage'] -or $before.tags_all.Stage -ne 'bastion' -or
                -not $before.tags_all.PSObject.Properties['Account'] -or $before.tags_all.Account -ne $Account -or
                -not $before.tags_all.PSObject.Properties['Project'] -or $before.tags_all.Project -ne $Project) {
                throw "Bastion 전용 자원의 계정·프로젝트·Stage 태그가 일치하지 않습니다: $($resource.address)"
            }
        }
    }
}
