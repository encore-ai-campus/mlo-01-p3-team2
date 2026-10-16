#Requires -Version 5.1
# 실제 AWS 없이 EIP 생성·삭제 허용 범위와 잔존 검사를 확인한다.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../scripts/lib/infra-common.ps1')
. (Join-Path $PSScriptRoot '../scripts/lib/infra-destroy.ps1')
$topology = [pscustomobject]@{
    project = 'test-project'; region = 'ap-northeast-2'
    accounts = [pscustomobject]@{ account1 = [pscustomobject]@{ profile = 'mock' } }
}
function New-EipPlan {
    param([string]$Type, [string[]]$Actions, [string]$Account = 'account1')
    $before = [pscustomobject]@{ id = 'eipalloc-test' }
    if ($Type -eq 'aws_eip') {
        $before | Add-Member tags_all ([pscustomobject]@{
            Project = 'test-project'; Account = $Account; Stage = 'bastion'; ManagedBy = 'Terraform'; Layout = 'v2'
        })
    }
    return [pscustomobject]@{
        planned_values = [pscustomobject]@{ root_module = [pscustomobject]@{} }
        resource_changes = @([pscustomobject]@{
            address = "module.bastion.$Type.this"; type = $Type; mode = 'managed'
            change = [pscustomobject]@{ actions = $Actions; before = $(if ($Actions -contains 'create' -and $Actions.Count -eq 1) { $null } else { $before }) }
        })
    }
}
function Assert-Rejected {
    param([scriptblock]$Action)
    $rejected = $false
    try { & $Action } catch { $rejected = $true }
    if (-not $rejected) { throw '허용하면 안 되는 계획을 허용했습니다.' }
}
foreach ($type in @('aws_eip','aws_eip_association')) {
    Assert-InfraBastionPlan (New-EipPlan $type @('create')) Create account1 test-project
    $plan = New-EipPlan $type @('delete')
    Assert-InfraBastionPlan $plan Delete account1 test-project
    $summary = @(Assert-InfraDeletePlan $plan bastion account1 $topology -DeleteDataVolumes)
    if ($summary.Count -ne 1 -or $summary[0].type -ne $type) { throw 'EIP 삭제 요약 누락' }
    Assert-Rejected { Assert-InfraBastionPlan (New-EipPlan $type @('delete','create')) Create account1 test-project }
}
Assert-Rejected { Assert-InfraBastionPlan (New-EipPlan 'aws_eip' @('no-op') 'account2') Create account1 test-project }
Assert-Rejected { Assert-InfraBastionPlan (New-EipPlan 'aws_eip_other' @('create')) Create account1 test-project }
Assert-Rejected { Assert-InfraDeletePlan (New-EipPlan 'aws_eip_other' @('delete')) bastion account1 $topology -DeleteDataVolumes }
Write-Host 'PASS: Bastion EIP create/delete, replacement rejection, ownership and address boundaries'

# EIP가 AWS 조회에 남으면 삭제 완료로 판정하지 않는다.
function Invoke-InfraDestroyAws {
    param($Command, $Arguments, $AbsentErrors)
    if ($Arguments[1] -ne 'describe-addresses' -or $Arguments[2] -ne '--allocation-ids') { throw 'EIP 조회 인수 오류' }
    return [pscustomobject]@{ Addresses = @([pscustomobject]@{ AllocationId = 'eipalloc-test' }) }
}
$resource = [pscustomobject]@{ type = 'aws_eip'; id = 'eipalloc-test'; account = 'account1' }
if (@(Test-InfraDeletedResources 'mock' $topology @($resource)).Count -ne 1) { throw '남은 EIP를 탐지하지 못했습니다.' }
Write-Host 'PASS: remaining EIP blocks deletion completion'
