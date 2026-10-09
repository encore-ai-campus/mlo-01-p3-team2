#Requires -Version 5.1
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
    foreach ($cidr in @($Traffic.admin_public_cidrs) + @($Traffic.game_client_cidrs)) {
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
function Get-InfraFingerprint {
    param([string]$Root, [string]$PublicKeyPath)
    # 로컬 캐시·계획·문서는 제외하고 실행 코드와 모든 공통 설정을 비교한다.
    $files = @(
        Get-ChildItem -LiteralPath (Join-Path $Root 'config') -File -Filter '*.json'
        Get-ChildItem -LiteralPath (Join-Path $Root 'terraform') -Recurse -File |
            Where-Object { $_.FullName -notmatch '[\\/]\.terraform[\\/]' -and ($_.Extension -eq '.tf' -or $_.Name -eq '.terraform.lock.hcl') }
        Get-Item -LiteralPath (Join-Path $Root 'scripts/infra.ps1')
        Get-ChildItem -LiteralPath (Join-Path $Root 'scripts/lib') -File -Filter '*.ps1'
    )
    $lines = @($files | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($Root.Length) + ':' + (Get-InfraFileHash $_.FullName)
    })
    if ($PublicKeyPath -and (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) {
        $lines += 'ssh_public_key:' + (Get-InfraFileHash $PublicKeyPath)
    }
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))))).Replace('-','') }
    finally { $algorithm.Dispose() }
}
