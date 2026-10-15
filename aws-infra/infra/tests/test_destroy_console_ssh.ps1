#Requires -Version 5.1
# 실제 AWS·Terraform을 호출하지 않고 전체 삭제 허용 목록의 경계를 검사한다.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../scripts/lib/infra-destroy.ps1')
$testTopology = [pscustomobject]@{ project = 'test-project' }
$testCount = 0

function New-ConsoleDeleteTestPlan {
    param([string]$Address, [string]$Action = 'delete', [string]$Owner = 'account1')
    return [pscustomobject]@{
        complete = $true
        planned_values = [pscustomobject]@{ root_module = [pscustomobject]@{} }
        resource_changes = @([pscustomobject]@{
            address = $Address
            mode = 'managed'
            type = $(if ($Address -like 'aws_vpc_security_group_egress_rule.*') { 'aws_vpc_security_group_egress_rule' } else { 'aws_vpc_security_group_ingress_rule' })
            change = [pscustomobject]@{
                actions = @($Action)
                before = [pscustomobject]@{
                    id = 'sgr-mock-console'
                    tags_all = [pscustomobject]@{
                        Project = $testTopology.project
                        Account = $Owner
                        ManagedBy = 'Terraform'
                        Layout = 'v2'
                    }
                }
                after = $null
            }
        })
    }
}

function Assert-ConsoleDeleteTestAccepted {
    param([string]$Address)
    $plan = New-ConsoleDeleteTestPlan -Address $Address
    $summary = @(Assert-InfraDeletePlan -Plan $plan -Stage workload -Account account1 -Topology $testTopology -DeleteDataVolumes)
    if ($summary.Count -ne 1 -or $summary[0].address -ne $Address) {
        throw "Expected one allowed deletion: $Address"
    }
    $script:testCount++
}

function Assert-ConsoleDeleteTestRejected {
    param($Plan, [string]$ExpectedMessage, [string]$Stage = 'workload')
    $failure = $null
    try {
        $null = @(Assert-InfraDeletePlan -Plan $Plan -Stage $Stage -Account account1 -Topology $testTopology -DeleteDataVolumes)
    } catch {
        $failure = $_.Exception.Message
    }
    if (-not $failure -or $failure -notlike "$ExpectedMessage*") {
        throw "Expected rejection '$ExpectedMessage'; received '$failure'"
    }
    $script:testCount++
}

# 실제 오류 주소와 다른 역할, 기존 Bastion 주소가 삭제 요약에 포함되어야 한다.
foreach ($role in @('ad', 'frontend', 'game', 'mysql', 'mongo', 'kafka', 'spark')) {
    Assert-ConsoleDeleteTestAccepted ('aws_vpc_security_group_ingress_rule.service_console_ssh["' + $role + '"]')
}
Assert-ConsoleDeleteTestAccepted 'aws_vpc_security_group_ingress_rule.bastion_console_ssh[0]'

# 현재 workload가 관리하는 두 Front의 송신 규칙도 삭제할 수 있어야 한다.
foreach ($role in @('game_frontend', 'ad_frontend')) {
    $frontAddress = 'aws_vpc_security_group_egress_rule.front_all["' + $role + '"]'
    Assert-ConsoleDeleteTestAccepted $frontAddress
    Assert-ConsoleDeleteTestRejected (New-ConsoleDeleteTestPlan $frontAddress -Owner account2) '삭제 대상의 프로젝트·계정·관리 태그가 다릅니다:'
    Assert-ConsoleDeleteTestRejected (New-ConsoleDeleteTestPlan $frontAddress -Action update) '삭제 계획에 생성·수정·교체·import가 포함됐습니다:'
    Assert-ConsoleDeleteTestRejected (New-ConsoleDeleteTestPlan $frontAddress) '삭제 단계 밖의 자원입니다:' -Stage foundation
}

# 이름이 비슷한 다른 자원·잘못된 키·추가 주소·다른 단계까지 허용하지 않는다.
foreach ($address in @(
    'aws_vpc_security_group_ingress_rule.service_console_ssh_backup["ad"]',
    'aws_vpc_security_group_ingress_rule.service_console_ssh[0]',
    'aws_vpc_security_group_ingress_rule.service_console_ssh["ad"].unrelated',
    'aws_s3_bucket.unrelated',
    'aws_vpc_security_group_egress_rule.front_all["mysql"]',
    'aws_vpc_security_group_egress_rule.front_all[0]',
    'aws_vpc_security_group_egress_rule.front_all_backup["ad_frontend"]',
    'aws_vpc_security_group_egress_rule.front_all["ad_frontend"].unrelated'
)) {
    Assert-ConsoleDeleteTestRejected (New-ConsoleDeleteTestPlan $address) '삭제 단계 밖의 자원입니다:'
}
$consoleAddress = 'aws_vpc_security_group_ingress_rule.service_console_ssh["ad"]'
Assert-ConsoleDeleteTestRejected (New-ConsoleDeleteTestPlan $consoleAddress) '삭제 단계 밖의 자원입니다:' -Stage foundation
Assert-ConsoleDeleteTestRejected (New-ConsoleDeleteTestPlan $consoleAddress -Owner account2) '삭제 대상의 프로젝트·계정·관리 태그가 다릅니다:'
Assert-ConsoleDeleteTestRejected (New-ConsoleDeleteTestPlan $consoleAddress -Action update) '삭제 계획에 생성·수정·교체·import가 포함됐습니다:'
$importPlan = New-ConsoleDeleteTestPlan $consoleAddress
$importPlan.resource_changes[0].change | Add-Member -NotePropertyName importing -NotePropertyValue ([pscustomobject]@{ id = 'sgr-mock-console' })
Assert-ConsoleDeleteTestRejected $importPlan '삭제 계획에 생성·수정·교체·import가 포함됐습니다:'

Write-Host "PASS: $testCount console SSH deletion boundary checks (no AWS/Terraform calls)"
