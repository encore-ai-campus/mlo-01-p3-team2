# 테스트 코드 탐색

[탐색 시작점](../ROUTING-README.md) · [기존 검증 기록](../../../infra/tests/README.md) · [Python 구조 분석](test_runner.py.md)

이번 작업은 문서 대조이며 아래 배포 테스트를 새로 실행한 기록이 아니다. 테스트의 **존재와 작성된 검사 내용**을 설명한다.

## 파일별 위치

| 파일 | 역할·검사 내용 |
| --- | --- |
| [infra/tests/test_runner.py](../../../infra/tests/test_runner.py) | 모의 AWS/Terraform CLI로 PowerShell 실행기 보호 동작 검사. Python 구조는 AST 스킬 결과 사용 |
| [infra/tests/fixtures.json](../../../infra/tests/fixtures.json) | 가짜 foundation 출력 5개와 가짜 Peering ID 10개. 실제 배포 상태가 아님 |
| [foundation.tftest.hcl](../../../infra/terraform/stacks/foundation/tests/foundation.tftest.hcl) | account1_proxy, account2_private, nat_per_az |
| [connectivity.tftest.hcl](../../../infra/terraform/stacks/connectivity/tests/connectivity.tftest.hcl) | all_pairs, wrong_remote_account |
| [workload.tftest.hcl](../../../infra/terraform/stacks/workload/tests/workload.tftest.hcl) | account1_default_closed, account2_three_nodes, account3_four_nodes, account4_two_nodes, account5_three_nodes, missing_peering |

foundation 테스트는 NAT 0개·서브넷 수·역할 SG와 같은 AZ NAT 연결을 검사한다. connectivity는 10쌍 및 account1-account2 양방향 경로, 잘못된 계정 상태 거부를 검사한다. workload는 계정별 노드 구성, 기본 외부 인바운드 차단, game→Kafka SG 참조, Peering 누락 거부를 검사한다.

Terraform 테스트는 mock_provider를 사용하고, connectivity/workload는 원격 상태를 fixture로 대체한다. workload run들은 state_key를 분리한다. 테스트 파일의 command = apply는 mock 테스트 동작이며 실제 배포 명령의 Apply와 구분한다.

## 현재 기록의 한계

기존 infra/tests/README.md에는 실행기 8개 시나리오 통과, foundation/connectivity 통과 기록이 있다. workload는 state_key 수정 후 재실행 결과가 미확인으로 적혀 있고 prepare-key.sh 실행 검사도 미완료로 적혀 있다. 이를 이번 작업에서 새로 통과한 결과로 바꾸지 않았다.

실제 IAM 권한, AWS 자원 상태, AMI·인증서 유효성, 프로그램 설치, DB 데이터 보존·성능은 이 문서의 구조 검사 범위 밖이다.

## 수정 시 함께 볼 파일

실행기의 계정·환경·계획 처리 변경은 test_runner.py와 [실행기 문서](../scripts/infra.ps1.md)를 함께 본다. Terraform의 출력 형식이나 배치 변경은 세 .tftest.hcl과 fixtures.json을 함께 확인한다. Python 함수 선언을 바꾸면 [Python 구조 문서](test_runner.py.md)를 routing-doc-sync로 다시 대조한다.
