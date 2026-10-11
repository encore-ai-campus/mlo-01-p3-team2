#Requires -Version 5.1
param([string]$PluginDirectory, [switch]$Terraform)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $root 'scripts/lib/infra-common.ps1')
. (Join-Path $root 'scripts/lib/test-isolation.ps1')
. (Join-Path $root 'scripts/lib/infra-destroy.ps1')
Assert-TestIsolation $root
$topology = (Read-InfraJson (Join-Path $root 'config/topology.tfvars.json')).topology
$traffic = (Read-InfraJson (Join-Path $root 'config/traffic.tfvars.json')).traffic
Assert-InfraConfiguration $topology $traffic
# 모든 PowerShell 진입점의 구문을 검사한다.
Get-ChildItem -LiteralPath (Join-Path $root 'scripts') -Recurse -Filter *.ps1 | ForEach-Object {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
}
function Expect-Rejection([scriptblock]$Action, [string]$Label) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw "거부되지 않았습니다: $Label" }
}
# 입력을 메모리에서만 바꿔 기존 상태 prefix의 차단을 검사한다.
$realReader = ${function:Read-InfraJson}
$script:badPrefix = $true
function Read-InfraJson([string]$Path) {
    $value = & $realReader $Path
    if ($script:badPrefix -and $Path.EndsWith('backend.json')) { $value.key_prefix = 'aws-infra-v2' }
    return $value
}
Expect-Rejection { Assert-TestIsolation $root } '기존 상태 prefix'
Set-Item Function:Read-InfraJson $realReader
# 기존 프로젝트의 태그를 가진 자원, 교체 계획, 범위 밖 자원을 삭제하지 않는다.
$plan = ('{"planned_values":{},"resource_changes":[{"mode":"managed","address":"module.compute.aws_instance.this[\"game-server\"]","type":"aws_instance","change":{"actions":["delete"],"before":{"id":"i-0123456789abcdef0","tags_all":{"Project":"aws-infra","Account":"account1","ManagedBy":"Terraform","Layout":"v2"}}}}]}' | ConvertFrom-Json)
Expect-Rejection { Assert-InfraDeletePlan $plan workload account1 $topology -DeleteDataVolumes } '기존 프로젝트 자원'
$plan.resource_changes[0].change.before.tags_all.Project = 'aws-infra-test'
$allowed = @(Assert-InfraDeletePlan $plan workload account1 $topology -DeleteDataVolumes)
if ($allowed.Count -ne 1) { throw '정상 테스트 자원이 삭제 허용되지 않았습니다.' }
$plan.resource_changes[0].change.actions = @('delete','create')
Expect-Rejection { Assert-InfraDeletePlan $plan workload account1 $topology -DeleteDataVolumes } '교체 포함 삭제'
$plan.resource_changes[0].change.actions = @('delete')
$plan.resource_changes[0].address = 'aws_s3_bucket.unrelated'
Expect-Rejection { Assert-InfraDeletePlan $plan workload account1 $topology -DeleteDataVolumes } '범위 밖 삭제'
$targets = @(Get-InfraDestroyTargets)
if ($targets.Count -ne 12 -or $targets[0].stage -ne 'bastion' -or $targets[6].stage -ne 'connectivity' -or $targets[-1].stage -ne 'foundation') { throw '삭제 순서 오류' }
Write-Host 'PASS: PowerShell 구문·구성·상태 분리·삭제 소유권·삭제 순서'
if ($Terraform) {
    foreach ($stage in @('foundation','connectivity','workload','bastion')) {
        $account = if ($stage -eq 'connectivity') { 'shared' } else { 'account1' }
        & (Join-Path $root 'scripts/infra.ps1') -Account $account -Stage $stage -Action Validate -PluginDirectory $PluginDirectory
        & (Join-Path $root 'scripts/infra.ps1') -Account $account -Stage $stage -Action Test -PluginDirectory $PluginDirectory
    }
}
