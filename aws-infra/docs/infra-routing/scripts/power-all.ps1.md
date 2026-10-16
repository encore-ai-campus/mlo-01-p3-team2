# infra/scripts/power-all.ps1

[스크립트 지도](README.md) · [원본](../../../infra/scripts/power-all.ps1) · [사용법](../../operations/ec2-power.md) · [계정별 작업자](lib/infra-power.ps1.md) · [모의 테스트](../tests/power-tests.md)

## 입력과 대상

선택한 구성의 전체 EC2를 계정별 PowerShell 작업으로 병렬 중지·시작한다. 서비스와 Bastion을 모두 포함하며 현재 current 구성은 5개 계정·18대다.

| 입력 | 기본값·제약 |
| --- | --- |
| Action | 필수. Stop 또는 Start만 허용 |
| ProfileDirectory | 스크립트 위치 기준 infra/config/profiles/current. 지정한 상대 경로는 호출 위치 기준으로 절대 경로화 |
| TimeoutSeconds | 계정별 전환 대기 600초, 허용 범위 1~3,600초 |
| WhatIf | 상태·대상·권한을 확인하고 실제 전원 변경 단계는 생략 |

topology의 계정 키 account1~5, 중복 없는 계정 ID·프로필, 서울 리전, 노드명·역할, 정확히 한 대의 bastion을 검사한다. 각 구성 경로에 대응하는 workload·bastion의 로컬 outputs.json에서 ID를 읽고 계정·리전·노드 목록·ID 중복을 대조한다. 대상 ID가 없거나 맞지 않으면 중단한다.

## 실행 흐름

구성·출력 확인 → 전체 계정 Check → ShouldProcess → 전체 계정 Change → 최종 상태·IP 표시 순서다. Check에서 하나라도 실패하면 Change를 시작하지 않는다.

Invoke-PowerPhase(Phase)는 Check 또는 Change마다 계정별 Start-Job을 만들고 [infra-power.ps1](lib/infra-power.ps1.md)에 TargetJson·Operation·Mode·TimeoutSeconds를 전달한다. 실행한 모든 계정의 결과·오류를 수집하며 finally에서 작업을 정리한다. WhatIf에서도 조회 작업은 실제로 실행하고 전원 변경만 생략한다.

Change 도중 일부 계정이 실패하면 성공한 계정의 상태를 되돌리지 않는다. 오류를 해결한 뒤 재실행하면 이미 원하는 상태인 EC2는 건너뛴다. Start 후에는 현재 공인 IP를 확인하고 Inventory를 갱신한다. DB·Kafka·Spark 클러스터 복구와 서비스 정상 여부는 플랫폼에서 별도로 확인한다.

이 실행기는 Terraform Apply·자원 삭제·설치·예약 실행을 호출하지 않는다. 실제 전원 전환과 AWS 권한 검사는 실행 시점의 원격 확인이며 [테스트 구조](../tests/power-tests.md)의 모의 결과와 구분한다.
