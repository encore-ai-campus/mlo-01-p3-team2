#Requires -Version 5.1
[CmdletBinding()]
param([string]$PublicKeyDirectory)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lib/infra-common.ps1')
. (Join-Path $PSScriptRoot 'lib/test-isolation.ps1')
Assert-TestIsolation $root
if (-not $PublicKeyDirectory) {
    $PublicKeyDirectory = Join-Path (Split-Path -Parent (Split-Path -Parent $root)) 'aws-infra/infra/config/keys'
}
# 개인키는 읽지 않는다. 다섯 공개키를 모두 검사한 뒤 없는 파일만 복사한다.
$keys = @{}
foreach ($n in 1..5) {
    $name = "account$n.pub"
    $value = [IO.File]::ReadAllText((Join-Path $PublicKeyDirectory $name)).Trim()
    if ($value -notmatch '^(ssh-rsa|ssh-ed25519) [A-Za-z0-9+/=]+(?:\s|$)') { throw "OpenSSH 공개키가 아닙니다: $name" }
    $destination = Join-Path $root "config/keys/$name"
    if ((Test-Path -LiteralPath $destination) -and [IO.File]::ReadAllText($destination).Trim() -ne $value) {
        throw "다른 공개키가 이미 있습니다. 덮어쓰지 않습니다: $name"
    }
    $keys[$destination] = $value
}
foreach ($path in $keys.Keys) { [IO.File]::WriteAllText($path, $keys[$path]+"`n", [Text.UTF8Encoding]::new($false)) }
Write-Host '테스트 공개키 준비 완료. backend·AMI·관리자 IP·접속 허용 CIDR을 확인한 뒤 Deploy하세요.'
