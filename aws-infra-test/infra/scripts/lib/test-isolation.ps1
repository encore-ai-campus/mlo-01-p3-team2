#Requires -Version 5.1
function Assert-TestIsolation {
    param([string]$Root)
    $testTopology = (Read-InfraJson (Join-Path $Root 'config/topology.tfvars.json')).topology
    $testBackend = Read-InfraJson (Join-Path $Root 'config/backend.json')
    if ($testTopology.project -cne 'aws-infra-test' -or $testBackend.key_prefix -cne 'aws-infra-test') {
        throw '테스트 전용 project와 key_prefix는 aws-infra-test여야 합니다. 기존 상태는 사용하지 않습니다.'
    }
    if ($testTopology.alb.enabled -or (@($testTopology.az_ids.PSObject.Properties.Name) -join ',') -cne 'a') {
        throw '테스트 환경은 ALB 없음·A 한 개만 지원합니다.'
    }
    $fronts = @($testTopology.nodes.PSObject.Properties | Where-Object { $_.Value.role -eq 'frontend' })
    if ($fronts.Count -ne 1 -or $fronts[0].Name -ne 'front-a') { throw 'Front는 front-a 한 대여야 합니다.' }
    foreach ($entry in $testTopology.accounts.PSObject.Properties) {
        if ($entry.Value.key_pair_name -cne "aws-infra-test-$($entry.Name)" -or $entry.Value.egress -ne 'proxy') {
            throw '테스트 전용 키페어 이름과 proxy 송신 설정이 필요합니다.'
        }
    }
    foreach ($entry in $testTopology.nodes.PSObject.Properties) {
        if ($entry.Value.az -ne 'a' -or $entry.Value.instance_type -ne 't3a.small') {
            throw '테스트 서버는 모두 A의 t3a.small이어야 합니다.'
        }
    }
    # 형제 원본 설정이 존재하면 상태 경로·자원 이름의 충돌도 검사한다.
    $original = Join-Path (Split-Path -Parent (Split-Path -Parent $Root)) 'aws-infra/infra/config'
    if (Test-Path -LiteralPath (Join-Path $original 'backend.json')) {
        $other = Read-InfraJson (Join-Path $original 'backend.json')
        if ($other.bucket -eq $testBackend.bucket -and $other.key_prefix -eq $testBackend.key_prefix) {
            throw '기존 환경과 S3 상태 경로가 겹칩니다.'
        }
    }
}
