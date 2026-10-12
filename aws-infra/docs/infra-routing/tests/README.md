# 테스트 코드 탐색

[탐색 시작점](../ROUTING-README.md) · [기존 검증 기록](../../../infra/tests/TEST-README.md) · [Python 구조 분석](test_runner.py.md)

현재 테스트 파일과 확인된 실행 기록을 안내한다. 2026-10-10 서비스 콘솔 SSH 모의 테스트 5개는 통과했다. ALB 비활성화 검사에 맞춰 기존 workload의 Bastion 분리·MySQL 3대·계정 간 SG 참조 기대값도 현재 구현에 맞췄다. 테스트의 존재, 정적 대조와 실제 실행 결과는 각각 구분한다.

## 파일별 위치

| 파일 | 역할·검사 내용 |
| --- | --- |
| [infra/tests/test_runner.py](../../../infra/tests/test_runner.py) | 모의 AWS/Terraform CLI로 PowerShell 실행기 보호 동작 검사. Python 구조는 AST 스킬 결과 사용 |
| [전체 삭제 테스트](destroy-tests.md) | test_destroy_all.py·test_destroy_once.py·destroy_cli.py의 실제 AWS 없는 개별 Plan/Apply·단일 Destroy·보호 복원·실패·잔존 검증 |
| [test_destroy_console_ssh.ps1](../../../infra/tests/test_destroy_console_ssh.ps1) | 삭제 검사 함수의 서비스 콘솔 SSH 허용 목록 회귀 검사. [검사 범위·실행 방법](destroy-tests.md)에서 역할별 허용과 주소·단계·태그·동작 거부 조건을 찾는다. |
| [infra/tests/fixtures.json](../../../infra/tests/fixtures.json) | 가짜 foundation 출력 5개와 가짜 Peering ID 10개. 실제 배포 상태가 아님 |
| [school-access.tftest.hcl](../../../infra/terraform/stacks/workload/tests/school-access.tftest.hcl) | 학원 SSH 22·Public Front HTTP 80·Bastion 콘솔 규칙 미생성, 계정별 5개 검사 |
| [edge.tftest.hcl](../../../infra/terraform/stacks/workload/tests/edge.tftest.hcl) | 진입 EC2의 Public A·EIP·Front 연결·외부 허용·단독 초기 구축 검사 |
| [application-flows.tftest.hcl](../../../infra/terraform/stacks/workload/tests/application-flows.tftest.hcl) | 5개 계정의 앱 연결 ingress·egress, SG 소유 계정 참조·단일 포트, 불필요한 Kafka 역방향 수신 규칙 없음 |
| [foundation.tftest.hcl](../../../infra/terraform/stacks/foundation/tests/foundation.tftest.hcl) | account1_proxy, account2_private, nat_per_az |
| [connectivity.tftest.hcl](../../../infra/terraform/stacks/connectivity/tests/connectivity.tftest.hcl) | all_pairs, wrong_remote_account |
| [workload.tftest.hcl](../../../infra/terraform/stacks/workload/tests/workload.tftest.hcl) | account1_default_closed, account2_three_nodes, account3_four_nodes, account4_three_nodes, account5_three_nodes, missing_peering, account1_without_alb_sg, account1_alb_opt_in |
| [flatten.tftest.hcl](../../../infra/terraform/stacks/workload/tests/flatten.tftest.hcl) | account2 Private A의 Consumer 사양·기존 노드 유지·Kafka·MongoDB 세 계정과 Proxy·SSH 경로. [평탄화 Consumer 검사](#평탄화-consumer-검사) 참고 |
| [console-ssh.tftest.hcl](../../../infra/terraform/stacks/workload/tests/console-ssh.tftest.hcl) | 5개 계정의 서비스 SG 선택, 접두사 목록 소스·TCP 22, Bastion·ALB 제외와 Bastion 콘솔 규칙 미생성 |
| [model/port-ranges.tftest.hcl](../../../infra/terraform/modules/model/tests/port-ranges.tftest.hcl) | Spark 범위 확장, 끝 포트 생략 호환성, 없는 끝 포트와 역순 범위 거부 |
| [security-rules/port-ranges.tftest.hcl](../../../infra/terraform/modules/security-rules/tests/port-ranges.tftest.hcl) | peer 규칙의 TCP from_port·to_port와 기존 단일 포트 유지 |
| [spark-ports.tftest.hcl](../../../infra/terraform/stacks/workload/tests/spark-ports.tftest.hcl) | account2·3·4의 Spark 입출력 범위·Worker RPC·Master UI, 규칙 키 유지와 같은 시작 포트의 범위 병합 |

foundation 테스트는 NAT 0개·서브넷 수·역할 SG와 같은 AZ NAT 연결을 검사한다. 현재 구성의 account1 SG 목록에는 ad가 포함되고 account2는 mongo·spark·consumer다. Consumer 반영 시 함께 갱신한 기대값과 fixture는 [평탄화 Consumer 검사](#평탄화-consumer-검사)에 정리한다. connectivity는 10쌍 및 account1-account2 양방향 경로, 잘못된 계정 상태 거부를 검사한다. workload는 계정별 노드 구성, 기본 외부 인바운드 차단, ALB 비활성화와 선택적 활성화, Front→game/ad:8000 유지, game→Kafka SG 참조, Peering 누락 거부를 검사한다.

Terraform 테스트는 mock_provider를 사용하고, connectivity/workload는 원격 상태를 fixture로 대체한다. workload run들은 state_key를 분리한다. 테스트 파일의 command = apply는 mock 테스트 동작이며 실제 배포 명령의 Apply와 구분한다.

`console-ssh.tftest.hcl`은 서비스 콘솔 SSH 규칙만 검사하는 별도 파일이다. AWS provider와 foundation/connectivity 상태를 모의 처리하며 Windows에서는 `terraform test '-filter=tests\console-ssh.tftest.hcl' -no-color`로 실행한다. 현재 구성에서 account1~account5의 서비스 SG는 각각 4 / 3 / 4 / 3 / 3개, 총 17개다. 아래 과거 5개 통과 기록은 mysql-3 추가 전 입력의 결과다. 같은 역할의 EC2가 SG를 공유하는 경우의 중복 제거와 Bastion 콘솔 규칙 미생성도 검사한다. 기존 workload.tftest.hcl의 배치·SG 참조 단언 불일치를 수정한 것으로 취급하지 않는다.

2026-10-10 검증에서는 Terraform 1.16.5와 설치된 AWS provider 6.68.0을 사용했다. `terraform validate`와 이번 파일의 계정별 모의 테스트 5개가 통과했다. 기존 전체 테스트를 통과했다는 뜻은 아니며 실제 AWS Plan·Apply·SSH 접속은 실행하지 않았다.

## Spark 포트 범위

[통신 설정](../config/README.md#traffic) → [model](../terraform/README.md#model) → [workload](../terraform/stacks/workload.md#주요-계산-위치) → [security-rules](../terraform/README.md#security-groups와-security-rules) 순서로 포트 범위가 전달된다. 세 테스트 파일은 이 연결의 서로 다른 단계에 대응한다.

| 파일 | run 이름 | 코드에 선언된 검사 |
| --- | --- | --- |
| model/port-ranges.tftest.hcl | spark_ranges | Driver 7078–7094의 SG 조합 9개, BlockManager 7079–7095, 나머지 단일 포트 |
| 같은 파일 | legacy_single_ports | port_end를 생략한 모든 연결은 port_end=port |
| 같은 파일 | unknown_end_port / reversed_range | 없는 끝 포트 키 또는 시작보다 작은 끝 값은 var.traffic 검증 실패를 기대 |
| security-rules/port-ranges.tftest.hcl | peer_port_bounds | TCP peer 입출력 규칙의 시작·끝 속성 및 기존 3888 단일 포트 |
| workload/spark-ports.tftest.hcl | account2_spark_ports / account3_spark_ports / account4_spark_ports | 계정별 7100·8080 입출력 각 6개, Driver·BlockManager 범위와 다른 규칙의 단일 포트, 시작 포트 기반 규칙 키 |
| 같은 파일 | same_start_range_union | 짧은 Driver 범위를 추가해도 기존 끝 값 7094 유지 |

총 9개의 run이 있으며 모두 command=plan이다. model 테스트는 AWS 자원을 만들지 않고, 나머지 두 파일은 mock_provider를 사용한다. workload 테스트는 원격 상태도 fixture로 대체한다. 여기 적은 내용은 현재 테스트 선언을 대조한 결과이며, 이번 문서 동기화에서 Terraform test를 실행해 통과했다는 뜻은 아니다. 테스트 기대값은 기본 config를 읽으므로 별도 비용 프로필의 실제 설정을 검증하는 결과로 사용할 수 없다.

원격 Spark 서비스·Master 이중화·Worker 등록·PySpark 제출은 [플랫폼 Spark 검증](../../../../aws-platform/platform/docs/platform-routing/roles/spark/tasks/verify.yml.md)이 담당한다. 이 Terraform 모의 테스트가 EC2의 프로그램 설치나 클러스터 동작까지 확인하지는 않는다.

## 현재 기록의 한계

기존 infra/tests/README.md에는 실행기 8개 시나리오 통과, foundation/connectivity 통과 기록이 있다. workload는 state_key 수정 후 재실행 결과가 미확인으로 적혀 있고 prepare-key.sh 실행 검사도 미완료로 적혀 있다. 이를 이번 작업에서 새로 통과한 결과로 바꾸지 않았다.

실제 IAM 권한, AWS 자원 상태, AMI·인증서 유효성, 프로그램 설치, DB 데이터 보존·성능은 이 문서의 구조 검사 범위 밖이다.

## 현재 입력과 모의 테스트의 범위

workload 서비스 서버는 계정별 5 / 3 / 4 / 3 / 3대다. ALB 비활성화 검증에서 기존 account1의 Bastion 포함 기대값, account4의 mysql-3 누락, game→Kafka의 계정 ID/SG ID 참조를 현재 구현에 맞췄다. 가짜 certificate_arn은 제거했다. fixture의 ALB SG는 기존 foundation 상태를 모의하기 위해 유지한다.

account1_default_closed는 관리자 CIDR과 public_http_cidrs를 빈 목록으로 지정하고 사용자 CIDR은 지정해도 ALB 비활성 상태에서 웹 공개 규칙이 생기지 않는지 검사한다. 콘솔 SSH는 별도 자원으로 유지한다. ALB 모듈·DNS·역할·연결 없음, Front→game/ad 8000 유지도 확인한다. account1_without_alb_sg는 foundation에서 ALB SG를 정리한 뒤의 상태, account1_alb_opt_in은 명시적으로 활성화와 연결 3개를 복원한 프로필을 검사한다. AWS provider와 원격 상태는 모의 처리한다.

Bastion stack에는 현재 보관된 tests/*.tftest.hcl이 없다. 과거 검증 기록은 당시 실행 범위를 뜻하며 이번 변경의 실행 결과는 [검증 기록](../verification.md#2026-10-11-alb-비활성화)에 별도로 남긴다.

## 평탄화 Consumer 검사

[flatten.tftest.hcl](../../../infra/terraform/stacks/workload/tests/flatten.tftest.hcl)은 account2의 기존 두 노드와 Private A의 flatten-1(t3a.medium)을 검사한다. 공인 IP·별도 데이터 EBS가 없고, Consumer SG에서 Kafka 세 계정의 9092·MongoDB 세 계정의 27017·배스천 프록시 3128로 총 7개 송신 규칙이 생성되는지, Kafka SG의 역방향 ingress와 SSH 경로를 검사한다. fixture에 account2/consumer SG를 추가하고 foundation·콘솔 SSH·account2 노드 기대값도 함께 맞췄다. 모의 검사이며 실제 AWS·프로그램 설치 결과가 아니다.

## 수정 시 함께 볼 파일

실행기의 계정·환경·계획 처리 변경은 test_runner.py와 [실행기 문서](../scripts/infra.ps1.md)를 함께 본다. Terraform의 출력 형식이나 배치 변경은 위 파일 목록과 fixtures.json을 확인한다. Spark 통신 범위를 바꾸면 모델·SG 규칙·workload의 포트 범위 테스트 세 파일과 플랫폼 설정도 함께 확인한다. Python 함수 선언을 바꾸면 [Python 구조 문서](test_runner.py.md)와 [전체 삭제 테스트 구조](destroy-tests.md)를 routing-doc-sync로 다시 대조한다.

2026-10-10 mysql-3 증설에서는 [실제 저장 계획과 AWS 조회](../verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)로 생성 범위·기존 EC2 유지·보안규칙을 검증했다. 이 작업에서 기존 전체 모의 테스트를 재실행하거나 기대값을 수정하지 않았으므로 과거 통과 결과를 새 3노드 구성의 테스트 결과로 해석하지 않는다.


## 평탄화 Consumer 변경 연결

flatten-1은 account2 Private A의 t3a.medium·OS 20GiB·공인 IP 및 별도 데이터 디스크 없음으로 정의한다. role=consumer를 유지하고 Kafka·Spark 그룹에 넣지 않는다. traffic의 consumer_kafka는 consumer→Kafka TCP 9092, consumer_mongo는 consumer→MongoDB TCP 27017, forward_proxy는 consumer→Bastion TCP 3128, SSH 연결은 Bastion→consumer TCP 22를 허용한다. 역할별 흐름은 송신·수신 보안그룹 규칙으로 펼쳐진다. 플랫폼 방화벽의 Kafka·MongoDB 허용 출처에도 consumer를 포함한다. Consumer 프로그램 배포와 원격 방화벽 적용은 별도다. foundation의 account2_private, workload의 account2_three_nodes·flatten.tftest.hcl·console-ssh.tftest.hcl과 fixtures.json의 consumer SG가 관련 검사 위치다. 아래 2026-10-11 애플리케이션 통신 검사에서 평탄화 모의 테스트 4건을 다시 실행해 통과했다.

## 애플리케이션 통신 검사

[application-flows.tftest.hcl](../../../infra/terraform/stacks/workload/tests/application-flows.tftest.hcl)은 기본 topology·traffic을 읽고 AWS provider와 원격 foundation/connectivity 상태를 모의 처리한다. account1_application_flows부터 account5_application_flows까지 5개 run에서 필요한 연결이 양쪽 SG에 생성되는지, 로컬·다른 계정 SG 참조 형식, 시작·끝 포트가 요구한 단일 포트인지 검사한다. Kafka→Spark·Consumer의 별도 신규 연결은 없어야 한다.

2026-10-11 Terraform validate 통과, application-flows 5건·flatten 4건·workload spark-ports 4건으로 총 13건이 통과했다. account4/mysql 모의 SG 누락을 보완했고 Consumer의 MongoDB 추가에 따라 송신 수를 4개에서 7개로 맞췄다. 기존 전체 Terraform 테스트를 모두 통과했다는 뜻은 아니다.

Windows PowerShell에서 workload 디렉터리를 기준으로 실행한다. 필터 경로에는 Windows 구분자를 사용한다.

```powershell
# AWS API를 호출하지 않는 모의 테스트 13건을 실행한다.
terraform test -no-color '-filter=tests\application-flows.tftest.hcl' '-filter=tests\flatten.tftest.hcl' '-filter=tests\spark-ports.tftest.hcl'
```

SG 관계는 [설정 지도](../config/README.md#애플리케이션-통신-확장), 적용 경계와 검증 결과는 [검증 기록](../verification.md#2026-10-11-애플리케이션-통신-규칙)을 따른다.

## 진입용 edge 검사

edge.tftest.hcl은 모의 AWS·원격 상태로 account1_edge_public_a를 실행한다. edge-1과 기존 서비스 서버 4대, EIP 출력, OS 20GiB·별도 데이터 디스크 없음, 전용 edge SG의 Front TCP 80 양쪽 참조·Bastion SSH·Proxy를 확인한다. ACME 80·허용 사용자 443 및 edge 인터넷 HTTPS 송신을 확인하며 게임·광고·DB 직접 연결은 추가하지 않는다. edge_only_bootstrap은 EC2 한 대·foundation 한 계정·connectivity 조회 없음을 검사한다. 모의 적용은 기존 전체 상태의 삭제 거부를 증명하지 않으며 실행기가 Plan·Apply에서 별도로 차단한다. foundation·workload·콘솔 SSH의 account1 수량과 fixture에 edge를 반영했다. 콘솔 SSH 테스트에서 과거 mysql-3 추가가 누락된 account4 기대값도 보완했다. 실제 서버 설치·TLS·least_conn 분산은 검증 대상에 포함하지 않는다.

test_destroy_all.py의 seed는 테스트 사본에 prevent_destroy를 시나리오의 protected 값대로 명시한다. 운영 compute의 현재 true/false 값과 무관하게 보호 거부·삭제 허용을 각각 검증하며 운영 파일은 변경하지 않는다.

## 2026-10-12 학원 접속 범위

- 학원 공인 IP는 `222.112.208.69/32`다. 앞서 전달된 `.72`는 사용하지 않는다.
- `admin_public_cidrs`: 학원 IP. Bastion SSH 22 및 Private 서버의 역할별 SG에 학원 IP의 SSH 22를 허용한다.
- `public_http_cidrs`: `0.0.0.0/0`. Public Front의 HTTP 80만 전체 공개한다. 필드가 없는 이전 프로필은 game_client_cidrs로 동작한다.
- `game_client_cidrs`: 학원 IP. 기존 edge HTTPS 443 범위를 전체 공개로 확대하지 않는다.
- Bastion의 EC2 Instance Connect 콘솔 SSH 출처 규칙은 생성하지 않는다. 기존 규칙이 있다면 다음 workload Plan에 해당 규칙 삭제가 표시된다. 서비스 서버의 기존 콘솔 SSH 규칙은 유지한다.
- Private SSH CIDR 규칙은 인터넷 경로를 만들지 않는다. Bastion 경유 시 목적 서버에는 Bastion 사설 IP가 출처로 보이므로 기존 Bastion→서버 SG 규칙도 유지한다. OS 방화벽·접속 경로의 실제 성공은 별도다.
- 기존 저장 Plan은 다시 만들어야 한다. 코드만 수정했으며 AWS Apply는 실행하지 않았다.

## 학원 접속 검사

[school-access.tftest.hcl](../../../infra/terraform/stacks/workload/tests/school-access.tftest.hcl)은 모의 provider와 원격 상태 fixture로 5개 계정을 검사한다. Private 역할별 SG 수는 account1~5 순서로 2 / 3 / 4 / 3 / 3개다. 학원 222.112.208.69/32의 SSH 22, Front HTTP 80 전체 공개, Bastion 콘솔 SSH 미생성 및 0.0.0.0/0 SSH 미생성을 검사한다. 서비스 콘솔 SSH는 별도 규칙으로 유지한다.

2026-10-12 구현 검증에서 기존 workload 33개와 테스트 환경 workload 10개가 통과했다. 실제 AWS 적용이나 서버 접속 성공을 뜻하지 않는다. 이번 문서 동기화에서는 Terraform 테스트를 재실행하지 않았다. 실행 범위는 [검증 기록](../verification.md)을 참고한다.
