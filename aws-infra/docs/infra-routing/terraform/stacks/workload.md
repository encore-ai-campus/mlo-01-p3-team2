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
| local.nodes | topology.nodes 중 account가 account_key이고 role != bastion인 서비스 서버만 선택 |
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

## 현재 HTTP 접속 경로

| 경로 | 허용·전달 조건 |
| --- | --- |
| 외부 사용자 → ALB | game_client_cidrs에 지정한 IPv4 CIDR에서 TCP 80 |
| ALB → Front | /static/* 규칙, frontend 대상 그룹 HTTP 80. ALB SG를 참조하는 양쪽 규칙 |
| ALB → game-server | 기본 전달, game 대상 그룹 HTTP 8000. ALB SG를 참조하는 양쪽 규칙 |
| ALB → ad-server | /ads/* 규칙, ad 대상 그룹 HTTP 8000. alb_ad 연결로 ALB SG를 참조하는 양쪽 규칙 |
| 외부 관리자 → Bastion | admin_public_cidrs → SSH 22. 현재 관리자 CIDR 한 항목이 설정됨 |

ALB의 외부 HTTP 포트와 내부 대상 포트는 별개다. Bastion의 인터넷 HTTPS 443 egress도 ALB의 외부 인바운드와 별개다. Account 1 workload는 Front 두 대·game-server·ad-server 네 대를 생성하며 Bastion은 [전용 단계](bastion.md)에서 생성한다. topology에 Bastion을 남겨 SSH·Proxy SG 규칙은 계속 계산한다. 광고 서버는 Private A이고 game-server와 서로 다른 EC2이므로 각각 HTTP 8000을 사용한다. 프로그램 설치와 정적 파일 배포는 [bootstrap 범위](../../bootstrap/README.md)다.

## 선행 상태 확인

states.tf는 각 foundation의 계정·리전·CIDR·AZ를 검사한다. terraform_data.connectivity_ready는 연결에 사용한 VPC ID와 현재 VPC ID가 같은지, 모든 계정 간 flow의 Peering 쌍이 존재하는지 검사한다. rules는 이 검사에 의존한다.

선행 상태를 확인해도 AWS의 실제 연결 상태나 프로세스 설치·수신 여부까지 증명하지는 않는다. 프로그램 설치·디스크 마운트는 [bootstrap 범위](../../bootstrap/README.md)다.

## 출력

inventory에는 account, account_id, region, instances, alb_dns_name이 들어간다. instances 내부 필드는 [compute 모듈](../README.md#compute)에 있다. proxy_endpoint는 workload에서 제거했고 [Bastion 출력](bastion.md#출력)으로 옮겼다. workload는 Bastion 원격 상태를 읽지 않는다.

실행기 Output 결과는 infra/.local/{account}/workload/outputs.json에 Terraform의 output -json 형식으로 저장된다. inventory 내용은 JSON의 inventory.value 아래에 있다.

## 변경 시 경계

SG 규칙·compute·ALB는 하나의 workload 상태로 묶여 있다. 실행기에 보안규칙만 적용하는 별도 Stage는 없다. 현재 compute의 데이터 볼륨은 prevent_destroy=true이고 OS 루트 디스크는 EC2 종료 시 삭제 설정이다. 데이터 볼륨 삭제·교체가 포함된 배치 이동·이름 변경 계획은 보호 설정 때문에 실패할 수 있다. 이 보호는 데이터 이전·백업 기능이 아니다.

## 콘솔 SSH 규칙의 범위

prefix list 이름은 `com.amazonaws.${var.topology.region}.ec2-instance-connect`이며 현재 서울 리전에서는 `com.amazonaws.ap-northeast-2.ec2-instance-connect`를 조회한다. 접두사 목록 ID를 하드코딩하지 않는다. Bastion 또는 서비스 EC2 SG가 있는 계정에서 한 번 조회하고 기존 Bastion 규칙과 서비스 규칙이 같은 결과를 사용한다.

`service_console_ssh`는 현재 계정의 서비스 EC2 역할마다 TCP 22 인바운드를 추가한다. 같은 역할의 EC2가 여러 대여도 SG별 규칙은 하나이며 Bastion·ALB는 대상에서 제외한다. 현재 구성의 대상 SG 수는 account1부터 account5까지 3 / 3 / 4 / 3 / 3개, 합계 16개다. 기존 `bastion_console_ssh`는 Account 1의 기존 대상과 자원 주소를 유지하며 이번 서비스 규칙 추가로 변경하지 않는다. 관리자 CIDR·통신 관계·CloudShell IP는 이 기능의 입력으로 추가하지 않는다.

두 콘솔 SSH 규칙은 module.rules.public_ingress와 별도 자원이다. Private 서비스 EC2에 공인 접속 경로나 EC2 Instance Connect Endpoint를 만들지 않으며 SSH 키 등록도 변경하지 않는다. IAM 권한·EC2 Instance Connect 설치·SSH 서비스·네트워크 경로의 실제 성공은 별도 검증 대상이다. AWS 콘솔에서 같은 서비스 규칙을 이미 수동으로 추가했다면 적용 전에 Terraform 관리로 가져오거나 중복을 정리해야 한다. [서비스 콘솔 SSH 모의 테스트](../../../../infra/terraform/stacks/workload/tests/console-ssh.tftest.hcl)는 계정별 SG 선택·접두사 목록·TCP 22 및 Bastion·ALB 제외를 검사한다.

## mysql-3 증설과 ALB 복원 보류

nodes.mysql-3를 추가하면 기존 local.nodes 선택과 compute의 동적 생성으로 account4 Private A에 MySQL 서버를 추가한다. 기존 서버 선택 조건이나 compute 소스를 바꾸지 않았다. 먼저 account4 foundation에 mysql SG를 생성한 뒤 다섯 workload에서 해당 SG를 참조하는 규칙을 반영했다. 기존 Peering과 서브넷을 사용한다.

2026-10-10 current 프로필의 실제 Apply는 account1~5 순서로 3 / 1 / 3 / 17 / 2개 추가, 변경·삭제 0개였다. 총 26개는 SG 규칙 23개와 mysql-3 EC2·별도 EBS·연결 각 하나다. EC2의 OS EBS는 EC2 자원 설정에 포함된다. [AWS 조회 결과](../../verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)는 기존 EC2 16대 유지와 새 규칙의 소스 SG·포트·방향을 확인했다. MySQL 프로그램 설치나 실제 3306 서비스 통신은 별도다.

account1의 최초 전체 Plan은 7개 추가였으며 MySQL 규칙 3개 외에 삭제된 ALB·HTTP listener·static/ad listener rule 4개 재생성을 포함했다. 사용자가 비용 증가를 원하지 않아 ALB 복원을 보류했다. 이번에만 같은 backend와 입력을 사용한 별도 저장 계획에서 다음 세 자원으로 -target 범위를 제한하고 코드·설정 fingerprint, backend와 계획 해시·자원 목록을 검토한 뒤 적용했다.

- module.rules.aws_vpc_security_group_egress_rule.peer["account1/bastion/account4/mysql/22"]
- module.rules.aws_vpc_security_group_egress_rule.peer["account1/game/account4/mysql/3306"]
- module.rules.aws_vpc_security_group_ingress_rule.peer["account4/mysql/account1/bastion/3128"]

이는 모든 구성을 동기화한 일반 Apply가 아니며 반복 운영 절차로 추가한 기능도 아니다. 원래 account1의 7개 전체 저장 계획과 사용한 부분 계획은 적용 후 제거해 잘못 재사용하지 않도록 했다. alb.enabled=true는 그대로라 이후 일반 account1 Plan에는 ALB 재생성이 다시 포함될 수 있다. ALB가 없는 동안 기존 ALB URL로 웹 접속할 수 없다. ALB만 삭제해도 EC2는 남지만 재생성 후 새 기본 DNS 주소를 확인하고 Django 허용 호스트·직접 적은 서비스 주소를 갱신해야 한다. [AWS ALB DNS](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html#dns-name), [삭제 범위](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-delete.html).
