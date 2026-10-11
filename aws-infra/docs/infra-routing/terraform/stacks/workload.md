# workload: 보안규칙·서버·디스크·ALB

[탐색 시작점](../../ROUTING-README.md) · [모듈 지도](../README.md) · [통신 설정](../../config/README.md)

## 파일과 책임

| 파일 | 확인할 내용 |
| --- | --- |
| [main.tf](../../../../infra/terraform/stacks/workload/main.tf) | Bastion 제외 노드 선택, SG 규칙·콘솔 SSH 계산, compute/alb 호출, inventory 출력 |
| [states.tf](../../../../infra/terraform/stacks/workload/states.tf) | 5개 foundation 및 shared/connectivity 원격 상태, connectivity_ready 검사 |
| [provider.tf](../../../../infra/terraform/stacks/workload/provider.tf) | 선택 계정의 AWS 프로필·계정 제한·태그 |
| [variables.tf](../../../../infra/terraform/stacks/workload/variables.tf) | 공통 입력·SSH 공개키·model 호출 |
| [versions.tf](../../../../infra/terraform/stacks/workload/versions.tf) | Terraform/provider 범위, S3 backend |
| [workload.tftest.hcl](../../../../infra/terraform/stacks/workload/tests/workload.tftest.hcl) | 계정별 서버 배치·기본 외부 차단·Peering 누락 모의 검사 |
| [console-ssh.tftest.hcl](../../../../infra/terraform/stacks/workload/tests/console-ssh.tftest.hcl) | 계정별 서비스 SG·접두사 목록·TCP 22 및 기존 Bastion 규칙 유지 모의 검사 |
| [spark-ports.tftest.hcl](../../../../infra/terraform/stacks/workload/tests/spark-ports.tftest.hcl) | Spark 세 계정의 포트 범위·7100·8080, 기존 규칙 키 및 같은 시작 포트의 끝 값 병합 검사 |

평탄화 노드 flatten-1은 account2의 consumer 역할이다. 기존 local.nodes와 compute의 동적 입력으로 생성하고 service_console_ssh에도 consumer SG를 포함한다. 기본 설정의 [flatten.tftest.hcl](../../../../infra/terraform/stacks/workload/tests/flatten.tftest.hcl)은 Private A·medium 사양·기존 서버 유지·브로커 세 계정의 규칙을 모의 검사한다.

## 주요 계산 위치

| 선언 | 의미 |
| --- | --- |
| local.nodes | 현재 계정의 role != bastion인 서버. edge_bootstrap_only=true이면 edge만 선택 |
| local.active_flows | 정규 배포는 전체 flow, 초기 구축은 같은 계정의 edge 관련 flow만 선택 |
| local.edge_ingress | edge SG에 ACME 80, 사용자 CIDR 443, 관리자 CIDR 22 |
| local.service_console_ssh_sg_ids | 현재 계정 서비스 EC2의 역할별 SG. 같은 역할을 중복 제거하며 Bastion·ALB는 제외 |
| local.sg_ids | 모든 foundation의 SG ID를 계정/역할 키로 결합 |
| local.peer_sg_ids | 같은 계정은 SG ID, 다른 계정은 소유 계정 ID/SG ID로 peer 참조 구성 |
| local.ingress_grouped | model.flows 중 대상 계정이 현재 계정인 규칙. port·port_end 전달 |
| local.egress_grouped | model.flows 중 소스 계정이 현재 계정인 규칙. port·port_end 전달 |
| local.admin_ingress | Bastion SG가 있을 때 관리자 CIDR → SSH 포트 |
| local.alb_ingress | 현재 계정 ALB가 활성화됐을 때 game_client_cidrs → TCP 80 |
| data.aws_ec2_managed_prefix_list.ec2_instance_connect | Bastion 또는 서비스 EC2 SG가 있는 계정에서 해당 리전의 IPv4 EC2 Instance Connect 접두사 목록을 이름으로 조회 |
| aws_vpc_security_group_ingress_rule.bastion_console_ssh | 기존 Bastion 전용 TCP 22 규칙. 서비스 규칙 추가 시 대상·자원 주소 유지 |
| aws_vpc_security_group_ingress_rule.service_console_ssh | 서비스 EC2 역할별 SG에 접두사 목록을 소스로 TCP 22 허용. Bastion·ALB 제외 |
| module.rules | SG쌍/포트 중복을 제거하고 규칙 생성. internet_https_roles에는 외부 TCP 443 egress |
| module.compute | 선택 계정의 서버·키페어·EBS·EIP 생성. rules 이후 실행 |
| module.alb | ALB 대상 계정에만 생성. HTTP 80 listener 및 같은 계정의 frontend/game/ad 대상 그룹. 역할별 EC2 ID·포트·경로·헬스 체크 경로를 전달하며 인증서 입력을 전달하지 않음 |

규칙 양쪽이 서로 다른 계정이면 소스 계정 workload가 egress, 대상 계정 workload가 ingress를 소유한다. 포트나 관계를 바꿀 때 양쪽 계획을 확인한다. 현재 모든 역할 관계는 [설정 지도](../../config/README.md#traffic)에 정리했다.

SG 쌍과 시작 포트를 규칙 키로 유지한다. 같은 키의 연결에 끝 포트가 여럿 있으면 최대값까지 합쳐 security-rules에 전달하므로, 기존 단일 포트를 범위로 바꿔도 Terraform 자원 주소는 유지된다. 현재 Spark Driver 7078–7094, BlockManager 7079–7095를 전달하고 Worker RPC 7100과 Master UI 8080을 Spark SG 사이에 추가한다. 현재 배치에서는 account2·3·4가 대상이며 다른 역할의 규칙 범위를 넓히지 않는다.

[포트 범위 테스트](../../tests/README.md#spark-포트-범위)는 모델 입력·SG 자원 속성·이 단계의 병합을 구분한다. 실제 데몬·작업 포트는 [플랫폼 Spark 설정](../../../../../aws-platform/platform/docs/platform-routing/roles/spark/README.md#프라이빗-서버의-통신-포트)에서 맞춘다. SG 규칙을 추가하는 것만으로 Spark를 설치하거나 서비스를 시작하지 않는다.

## 선택적으로 ALB를 활성화했을 때의 HTTP 접속 경로

현재 기본 및 current 설정에서는 ALB가 비활성화돼 아래 ALB 경로를 생성하지 않는다. 외부→Front 웹 접속 규칙은 아직 없으며, 기존 Front→game/ad 8000만 유지한다. ALB를 다시 사용할 때는 활성화와 전용 연결 3개를 함께 설정한다.

| 경로 | 허용·전달 조건 |
| --- | --- |
| 외부 사용자 → ALB | game_client_cidrs에 지정한 IPv4 CIDR에서 TCP 80 |
| ALB → Front | /static/* 규칙, frontend 대상 그룹 HTTP 80. ALB SG를 참조하는 양쪽 규칙 |
| ALB → game-server | 기본 전달, game 대상 그룹 HTTP 8000. ALB SG를 참조하는 양쪽 규칙 |
| ALB → ad-server | /ads/* 규칙, ad 대상 그룹 HTTP 8000. alb_ad 연결로 ALB SG를 참조하는 양쪽 규칙 |
| 외부 관리자 → Bastion | admin_public_cidrs → SSH 22. 현재 관리자 CIDR 한 항목이 설정됨 |

ALB의 외부 HTTP 포트와 내부 대상 포트는 별개다. Bastion의 인터넷 HTTPS 443 egress도 ALB의 외부 인바운드와 별개다. Account 1 workload는 edge-1·Front 두 대·game-server·ad-server 다섯 대를 생성하며 Bastion은 [전용 단계](bastion.md)에서 생성한다. topology에 Bastion을 남겨 SSH·Proxy SG 규칙은 계속 계산한다. 광고 서버는 Private A이고 game-server와 서로 다른 EC2이므로 각각 HTTP 8000을 사용한다. 프로그램 설치와 정적 파일 배포는 [bootstrap 범위](../../bootstrap/README.md)다.

## 선행 상태 확인

정규 배포는 다섯 foundation의 계정·리전·CIDR·AZ를 검사한다. terraform_data.connectivity_ready는 현재 VPC와 Peering 쌍을 확인한다. edge_bootstrap_only=true이면 해당 계정 foundation만 읽고 connectivity를 조회하지 않는다. terraform_data.edge_bootstrap_guard[0]은 Account 1, ALB 비활성, Public edge-1(t3a.small) 한 대 조건을 검사한다. 실행기는 별도로 기존 자원 삭제·교체를 차단한다.

선행 상태를 확인해도 AWS의 실제 연결 상태나 프로세스 설치·수신 여부까지 증명하지는 않는다. 프로그램 설치·디스크 마운트는 [bootstrap 범위](../../bootstrap/README.md)다.

## 출력

inventory에는 account, account_id, region, instances, alb_dns_name이 들어간다. instances 내부 필드는 [compute 모듈](../README.md#compute)에 있다. proxy_endpoint는 workload에서 제거했고 [Bastion 출력](bastion.md#출력)으로 옮겼다. workload는 Bastion 원격 상태를 읽지 않는다.

실행기 Output 결과는 infra/.local/{account}/workload/outputs.json에 Terraform의 output -json 형식으로 저장된다. inventory 내용은 JSON의 inventory.value 아래에 있다.

## 변경 시 경계

SG 규칙·compute·ALB는 하나의 workload 상태로 묶여 있다. 실행기에 보안규칙만 적용하는 별도 Stage는 없다. 현재 compute의 데이터 볼륨은 prevent_destroy=true이고 OS 루트 디스크는 EC2 종료 시 삭제 설정이다. 데이터 볼륨 삭제·교체가 포함된 배치 이동·이름 변경 계획은 보호 설정 때문에 실패할 수 있다. 이 보호는 데이터 이전·백업 기능이 아니다.

## 콘솔 SSH 규칙의 범위

prefix list 이름은 `com.amazonaws.${var.topology.region}.ec2-instance-connect`이며 현재 서울 리전에서는 `com.amazonaws.ap-northeast-2.ec2-instance-connect`를 조회한다. 접두사 목록 ID를 하드코딩하지 않는다. Bastion 또는 서비스 EC2 SG가 있는 계정에서 한 번 조회하고 기존 Bastion 규칙과 서비스 규칙이 같은 결과를 사용한다.

`service_console_ssh`는 현재 계정의 서비스 EC2 역할마다 TCP 22 인바운드를 추가한다. 같은 역할의 EC2가 여러 대여도 SG별 규칙은 하나이며 Bastion·ALB는 대상에서 제외한다. 현재 구성의 대상 SG 수는 account1부터 account5까지 4 / 3 / 4 / 3 / 3개, 합계 17개다. 기존 `bastion_console_ssh`는 Account 1의 기존 대상과 자원 주소를 유지하며 이번 서비스 규칙 추가로 변경하지 않는다. 관리자 CIDR·통신 관계·CloudShell IP는 이 기능의 입력으로 추가하지 않는다.

두 콘솔 SSH 규칙은 module.rules.public_ingress와 별도 자원이다. Private 서비스 EC2에 공인 접속 경로나 EC2 Instance Connect Endpoint를 만들지 않으며 SSH 키 등록도 변경하지 않는다. IAM 권한·EC2 Instance Connect 설치·SSH 서비스·네트워크 경로의 실제 성공은 별도 검증 대상이다. AWS 콘솔에서 같은 서비스 규칙을 이미 수동으로 추가했다면 적용 전에 Terraform 관리로 가져오거나 중복을 정리해야 한다. [서비스 콘솔 SSH 모의 테스트](../../../../infra/terraform/stacks/workload/tests/console-ssh.tftest.hcl)는 계정별 SG 선택·접두사 목록·TCP 22 및 Bastion·ALB 제외를 검사한다.

## mysql-3 증설과 ALB 복원 보류

nodes.mysql-3를 추가하면 기존 local.nodes 선택과 compute의 동적 생성으로 account4 Private A에 MySQL 서버를 추가한다. 기존 서버 선택 조건이나 compute 소스를 바꾸지 않았다. 먼저 account4 foundation에 mysql SG를 생성한 뒤 다섯 workload에서 해당 SG를 참조하는 규칙을 반영했다. 기존 Peering과 서브넷을 사용한다.

2026-10-10 current 프로필의 실제 Apply는 account1~5 순서로 3 / 1 / 3 / 17 / 2개 추가, 변경·삭제 0개였다. 총 26개는 SG 규칙 23개와 mysql-3 EC2·별도 EBS·연결 각 하나다. EC2의 OS EBS는 EC2 자원 설정에 포함된다. [AWS 조회 결과](../../verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)는 기존 EC2 16대 유지와 새 규칙의 소스 SG·포트·방향을 확인했다. MySQL 프로그램 설치나 실제 3306 서비스 통신은 별도다.

account1의 최초 전체 Plan은 7개 추가였으며 MySQL 규칙 3개 외에 삭제된 ALB·HTTP listener·static/ad listener rule 4개 재생성을 포함했다. 사용자가 비용 증가를 원하지 않아 ALB 복원을 보류했다. 이번에만 같은 backend와 입력을 사용한 별도 저장 계획에서 다음 세 자원으로 -target 범위를 제한하고 코드·설정 fingerprint, backend와 계획 해시·자원 목록을 검토한 뒤 적용했다.

- module.rules.aws_vpc_security_group_egress_rule.peer["account1/bastion/account4/mysql/22"]
- module.rules.aws_vpc_security_group_egress_rule.peer["account1/game/account4/mysql/3306"]
- module.rules.aws_vpc_security_group_ingress_rule.peer["account4/mysql/account1/bastion/3128"]

이는 모든 구성을 동기화한 일반 Apply가 아니며 반복 운영 절차로 추가한 기능도 아니다. 원래 account1의 7개 전체 저장 계획과 사용한 부분 계획은 적용 후 제거해 잘못 재사용하지 않도록 했다. 당시에는 alb.enabled=true를 유지했다. 이후 아래 2026-10-11 변경에서 기본 및 current 설정의 ALB를 비활성화했다. ALB가 없는 동안 기존 ALB URL로 웹 접속할 수 없다. ALB만 삭제해도 EC2는 남지만 재생성 후 새 기본 DNS 주소를 확인하고 Django 허용 호스트·직접 적은 서비스 주소를 갱신해야 한다. [AWS ALB DNS](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html#dns-name), [삭제 범위](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-delete.html).

## 애플리케이션 연결 확장

2026-10-11 [traffic 연결 10종류](../../config/README.md#애플리케이션-통신-확장)를 추가했다. 기존 module.model.flows → ingress_grouped/egress_grouped → module.rules 경로가 새 SG 연결 28쌍을 각 계정의 ingress·egress로 펼치므로 workload 구현은 변경하지 않았다. 기본 설정과 current 프로필을 함께 반영했다.

적용 대상은 account1~5 workload다. SG 외부 CIDR·ALB·EC2 배치·기존 클러스터 연결은 이번 변경에서 수정하지 않는다. 외부 사용자→Front 443이나 HTTPS 서버 배포도 포함하지 않는다. 실제 Plan에는 이 연결 외의 기존 코드·AWS 상태 차이가 함께 나타날 수 있으므로 전체 변경을 확인해야 한다.

[application-flows 모의 검사](../../tests/README.md#애플리케이션-통신-검사) 5건과 flatten·Spark 회귀 8건을 통과했다. 실제 AWS Plan·Apply는 실행하지 않았다. OS firewall의 game·ad 수신 역할과 MySQL·MongoDB·Kafka 출처도 함께 수정했으며 원격 Ansible 적용은 별도다.

## ALB 비활성화 설정

2026-10-11 기본 및 current 설정의 ALB를 끄고 전용 연결 3개를 제거했다. 기존 local.alb_enabled·module.alb.count·model.flows 계산으로 처리하므로 workload 구현 파일은 변경하지 않았다. ALB 모듈·DNS와 ALB 전용 규칙은 생성하지 않으며 당시 서비스 EC2 17대와 Front EIP 두 개, 다른 서비스 연결을 유지했다. 이후 아래 edge-1 추가로 서비스 EC2는 18대, workload EIP는 3개다. 기존 foundation 출력에 ALB SG가 남은 전환 단계와 SG 정리 후를 모두 모의 검사한다. 실제 원격 상태 전환과 자원 삭제는 검증하지 않았다.

foundation을 먼저 적용해 사용 중인 ALB SG를 삭제하지 않도록 [배포 순서](../../../deployment-runbook.md#alb-비활성화-적용-순서)를 따른다.

## 진입용 edge-1 추가

기본 및 current topology는 edge-1을, traffic은 edge_front·SSH·Proxy 연결을 선언한다. account1 foundation의 edge SG를 먼저 준비해야 한다. 정규 workload 서비스 수는 5/3/4/3/3대이며 Front EIP 두 개와 edge EIP 한 개를 사용한다. main.tf의 edge_ingress는 외부 80(ACME), 사용자 CIDR 443, 관리자 CIDR 22를 만들고 internet_https_roles는 edge의 인터넷 443 송신을 허용한다. [edge.tftest.hcl](../../../../infra/terraform/stacks/workload/tests/edge.tftest.hcl)은 Public A·EIP·SG 연결·외부 허용 및 초기 구축의 단일 노드를 검사한다.

## edge 단독 초기 구축

edge_bootstrap_only는 기본 false다. [infra.ps1](../../scripts/infra.ps1.md)의 -EdgeBootstrapOnly를 쓰면 edge-1 한 대와 같은 계정의 edge 관련 연결만 생성하고 Bastion 콘솔/관리자 규칙·다른 계정 연결을 생략한다. 정규 workload와 자원 주소·backend를 공유하므로 나중에 일반 모드로 다른 서버를 추가한다. 기존 전체 상태에 사용하면 제거 계획이 생길 수 있어 실행기가 Plan·Apply 양쪽에서 삭제·교체와 edge-1(t3a.small) 외 EC2를 거부한다.

전체 삭제 실행기는 상태의 edge_bootstrap_guard[0] 표식을 읽어 같은 초기 구축 모드를 Delete Plan·Apply에도 전달한다. 일반 상태는 기존대로 다섯 foundation·connectivity를 읽는다. 이 선택은 생성 시의 삭제 차단을 없애는 옵션이 아니며, 삭제는 기존 전체 삭제 실행 ID·범위·태그·상태 해시 검사를 모두 통과해야 한다.

connectivity_ready는 edge_bootstrap_guard에 의존하며, compute와 SG 규칙은 connectivity_ready 뒤에 생성된다. 삭제 시 역순으로 정리해 EC2·규칙 삭제가 중단돼도 초기 구축 표식이 남도록 한다.
