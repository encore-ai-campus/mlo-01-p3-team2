#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../scripts/lib/infra-common.ps1')
$shell = (Get-Process -Id $PID).Path
$testRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ('../.local/tests/common-' + [Guid]::NewGuid().ToString('N'))))
$null = New-Item -ItemType Directory -Path $testRoot -Force

function Assert-Test {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

# 실패 경로에서도 기존 값과 원래 없던 변수를 정확히 복원한다.
$names = @('INFRA_REFACTOR_EXISTING', 'INFRA_REFACTOR_ABSENT')
$original = @{}
foreach ($name in $names) { $original[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    [Environment]::SetEnvironmentVariable($names[0], 'before', 'Process')
    [Environment]::SetEnvironmentVariable($names[1], $null, 'Process')
    $saved = Save-InfraEnvironment $names
    Assert-Test ($saved[$names[0]] -eq 'before' -and [string]::IsNullOrEmpty($saved[$names[1]])) '환경 스냅샷 불일치'
    foreach ($name in $names) { Assert-Test ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name, 'Process'))) '환경 해제 실패' }
    try {
        [Environment]::SetEnvironmentVariable($names[0], 'during', 'Process')
        [Environment]::SetEnvironmentVariable($names[1], 'during', 'Process')
        throw 'expected'
    } catch {
        Assert-Test ($_.Exception.Message -eq 'expected') '예상하지 못한 예외'
    } finally { Restore-InfraEnvironment $names $saved }
    Assert-Test ([Environment]::GetEnvironmentVariable($names[0], 'Process') -eq 'before') '기존 환경 복원 실패'
    Assert-Test ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($names[1], 'Process'))) '없는 변수 복원 실패'
} finally { Restore-InfraEnvironment $names $original }
Write-Host 'PASS: environment isolation and restoration after failure'

# 실제 AWS 대신 별도 PowerShell 프로세스로 stdout·stderr·종료 코드를 확인한다.
$result = Invoke-InfraCapturedCommand $shell @('-NoProfile','-Command','[Console]::Out.WriteLine(''out''); [Console]::Error.WriteLine(''err''); exit 7')
Assert-Test ($result.ExitCode -eq 7 -and $result.Text -match 'out' -and $result.Text -match 'err') 'CLI 오류 수집 실패'
Assert-Test ($ErrorActionPreference -eq 'Stop') '호출자의 오류 정책이 변경됨'
$result = Invoke-InfraCapturedCommand $shell @('-NoProfile','-Command','exit 0')
Assert-Test ($result.ExitCode -eq 0 -and $result.Text -eq '') '빈 출력 처리 실패'
Write-Host 'PASS: native stdout/stderr, failure code and empty success'

# 저장 계획을 두 번 읽을 때 변경된 JSON이 보여야 한다. 실패 메시지도 호출부의 값을 유지한다.
$fake = Join-Path $testRoot 'terraform.cmd'
$plan = Join-Path $testRoot 'plan.json'
[IO.File]::WriteAllText($fake, ("@echo off`r`ntype `"" + $plan + "`"`r`n"), [Text.Encoding]::ASCII)
Write-InfraJson $plan @{ version = 1 }
$first = Read-InfraTerraformPlan $fake $testRoot $plan 'plan read failed'
Write-InfraJson $plan @{ version = 2 }
$second = Read-InfraTerraformPlan $fake $testRoot $plan 'plan read failed'
Assert-Test ($first.version -eq 1 -and $second.version -eq 2) '저장 계획을 다시 읽지 않음'
[IO.File]::WriteAllText($fake, "@echo off`r`nexit /b 9`r`n", [Text.Encoding]::ASCII)
$message = ''
try { $null = Read-InfraTerraformPlan $fake $testRoot $plan 'plan read failed' }
catch { $message = $_.Exception.Message }
Assert-Test ($message -eq 'plan read failed') '저장 계획 오류 메시지 변경'
Write-Host 'PASS: fresh plan reads and caller-specific failure message'
