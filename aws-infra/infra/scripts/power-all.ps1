#Requires -Version 5.1
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory)][ValidateSet('Stop','Start')][string]$Action,
    [string]$ProfileDirectory,
    [ValidateRange(1,3600)][int]$TimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib/infra-common.ps1')
$infraRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ProfileDirectory)) {
    # PowerShell 5.1의 -File 진입에서는 매개변수 기본값 평가 시 PSScriptRoot가 비어 있을 수 있다.
    $ProfileDirectory = Join-Path $PSScriptRoot '../config/profiles/current'
}
$ProfileDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ProfileDirectory)
$topology = (Read-InfraJson (Join-Path $ProfileDirectory 'topology.tfvars.json')).topology
$accounts = @($topology.accounts.PSObject.Properties | Sort-Object Name)
$nodes = @($topology.nodes.PSObject.Properties)
if (($accounts.Name -join ',') -ne 'account1,account2,account3,account4,account5' -or
    @($accounts.Value.id | Select-Object -Unique).Count -ne 5 -or
    @($accounts.Value.profile | Select-Object -Unique).Count -ne 5 -or
    $topology.project -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$' -or
    $topology.region -ne 'ap-northeast-2' -or $nodes.Count -eq 0) {
    throw '구성의 account1~account5, 고유 계정·프로필, 프로젝트·서울 리전을 확인하세요.'
}
foreach ($node in $nodes) {
    if ($node.Name -notmatch '^[A-Za-z0-9_-]+$' -or $node.Value.account -notin $accounts.Name -or
        $node.Value.role -notmatch '^[A-Za-z0-9_-]+$') { throw "잘못된 노드 구성: $($node.Name)" }
}
$bastions = @($nodes | Where-Object { $_.Value.role -eq 'bastion' })
if ($bastions.Count -ne 1 -or $bastions[0].Name -ne 'bastion') { throw 'bastion 노드가 정확히 1대 필요합니다.' }

# 로컬 배포 출력에 저장된 ID만 사용한다. 태그 검색으로 다른 환경의 서버를 대신 선택하지 않는다.
$targets = @()
foreach ($account in $accounts) {
    if ($account.Value.id -notmatch '^\d{12}$' -or [string]::IsNullOrWhiteSpace($account.Value.profile)) {
        throw "계정 ID·AWS 프로필을 확인하세요: $($account.Name)"
    }
    $records = @()
    foreach ($stage in @('workload','bastion')) {
        $expected = @($nodes | Where-Object {
            $_.Value.account -eq $account.Name -and (($_.Value.role -eq 'bastion') -eq ($stage -eq 'bastion'))
        })
        if ($stage -eq 'bastion' -and $expected.Count -eq 0) { continue }
        $workPath = Get-InfraWorkPath $infraRoot $account.Name $stage $ProfileDirectory
        $outputPath = Join-Path $workPath 'outputs.json'
        if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
            throw "배포 출력이 없습니다: $outputPath. 해당 구성으로 infra.ps1 -Action Output을 실행하세요."
        }
        $output = Read-InfraJson $outputPath
        $value = if ($stage -eq 'bastion') { $output.bastion.value } else { $output.inventory.value }
        if ($value.account -ne $account.Name -or $value.account_id -ne $account.Value.id -or $value.region -ne $topology.region) {
            throw "저장된 출력의 계정·리전이 구성과 다릅니다: $outputPath"
        }
        if ($stage -eq 'workload' -and
            ((@($value.instances.PSObject.Properties.Name | Sort-Object) -join ',') -ne
             (@($expected.Name | Sort-Object) -join ','))) {
            throw "$($account.Name)의 저장된 노드 목록과 구성이 다릅니다. 배포 출력과 구성 경로를 확인하세요."
        }
        foreach ($node in $expected) {
            $id = if ($stage -eq 'bastion') { $value.id } else { $value.instances.($node.Name).id }
            if ($id -notmatch '^i-[0-9a-f]{8}(?:[0-9a-f]{9})?$') { throw "잘못된 EC2 ID: $($node.Name)" }
            $records += [pscustomobject]@{ Name = $node.Name; Role = $node.Value.role; Id = $id }
        }
    }
    if ($records.Count -eq 0) { continue }
    $targets += [pscustomobject]@{
        Account = $account.Name; AccountId = $account.Value.id; Profile = $account.Value.profile
        Project = $topology.project; Region = $topology.region; Nodes = $records
    }
}
$allIds = @($targets | ForEach-Object { $_.Nodes } | ForEach-Object { $_.Id })
if ($allIds.Count -ne $nodes.Count -or @($allIds | Select-Object -Unique).Count -ne $allIds.Count) {
    throw '대상 EC2 ID에 중복이나 누락이 있습니다.'
}
$awsCommand = (Get-Command aws -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$workerPath = Join-Path $PSScriptRoot 'lib/infra-power.ps1'

function Invoke-PowerPhase {
    param([ValidateSet('Check','Change')][string]$Phase)
    # 미리보기에서도 읽기 전용 작업 프로세스는 실제 생성·정리한다. 전원 변경은 바깥 ShouldProcess가 제어한다.
    $WhatIfPreference = $false
    $jobs = @()
    $rows = @()
    $failures = @()
    try {
        # 계정마다 독립 프로세스를 사용해 AWS 환경 변수와 전원 요청을 분리한다.
        foreach ($target in $targets) {
            $job = Start-Job -ScriptBlock {
                param($WorkerPath, $AwsCommand, $TargetJson, $Operation, $Mode, $Timeout)
                & $WorkerPath -AwsCommand $AwsCommand -TargetJson $TargetJson -Operation $Operation -Mode $Mode -TimeoutSeconds $Timeout
            } -ArgumentList $workerPath,$awsCommand,($target | ConvertTo-Json -Depth 10 -Compress),$Action,$Phase,$TimeoutSeconds
            $jobs += [pscustomobject]@{ Account = $target.Account; Job = $job }
        }
        # 한 계정이 실패해도 이미 시작한 다른 계정의 결과를 모두 수집한다.
        foreach ($entry in $jobs) {
            try {
                $result = @(Receive-Job -Job $entry.Job -Wait -ErrorAction Stop)
                if ($entry.Job.State -ne 'Completed' -or $result.Count -eq 0) { throw '작업 결과가 없습니다.' }
                $rows += $result
                Write-Host "[$Phase] $($entry.Account): 완료 ($($result.Count)대)"
            } catch {
                $failures += "$($entry.Account): $($_.Exception.Message)"
            }
        }
    } finally {
        foreach ($entry in $jobs) {
            if ($entry.Job.State -in @('Running','NotStarted','Blocked')) { Stop-Job -Job $entry.Job }
            Remove-Job -Job $entry.Job -Force
        }
    }
    if ($failures.Count -gt 0) {
        $rows | Sort-Object Account,Name | Format-Table Account,Name,Id,State,PublicIp -AutoSize | Out-Host
        $context = if ($Phase -eq 'Check') { '사전 확인 실패: 실제 전원 변경 요청은 보내지 않았습니다.' } else {
            '일부 계정은 이미 변경되었을 수 있습니다. 원인을 해결한 뒤 같은 명령을 재실행하세요.'
        }
        throw ($context + "`n" + ($failures -join "`n"))
    }
    return $rows
}

Write-Host "구성: $ProfileDirectory / $($nodes.Count)대 / $Action"
$before = @(Invoke-PowerPhase -Phase Check)
$before | Sort-Object Account,Name | Format-Table Account,Name,Id,State,PublicIp -AutoSize | Out-Host
# 전체 계정의 소유자·태그·전원 권한 검사를 통과한 뒤에만 실제 변경을 시작한다.
if (-not $PSCmdlet.ShouldProcess("$($topology.project), $($nodes.Count) EC2 instances", $Action)) { return }
$after = @(Invoke-PowerPhase -Phase Change)
$after | Sort-Object Account,Name | Format-Table Account,Name,Id,State,PrivateIp,PublicIp -AutoSize | Out-Host
Write-Host "$Action 완료: $($after.Count)대. EC2 전원 상태를 확인했습니다."
if ($Action -eq 'Start') {
    Write-Host '현재 공인 IP를 확인하세요. Ansible 접속 전 deploy.ps1 -ProfileDirectory <동일 구성 경로> -Action Inventory로 주소를 갱신하세요.'
    Write-Host 'DB·Kafka·Spark의 클러스터 상태는 별도로 확인해야 합니다. 이 스크립트는 클러스터 복구를 실행하지 않습니다.'
}
