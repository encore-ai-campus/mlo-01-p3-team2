# Terraform 코드 지도

[탐색 시작점](../ROUTING-README.md) · [설정 지도](../config/README.md)

## 실행 단위와 상태 소유권

| stack | 실행 대상 | 모듈 | 상태 출력 |
| --- | --- | --- | --- |
| [foundation](stacks/foundation.md) | account1~account5 각각 | model, network, security-groups | foundation |
| [connectivity](stacks/connectivity.md) | shared | model, peering × 설정된 계정 쌍 | connections, foundation_vpcs |
| [workload](stacks/workload.md) | account1~account5 각각 | model, security-rules, compute, 해당 시 alb | inventory |

세 stack의 versions.tf는 Terraform **>= 1.11, < 2.0**, hashicorp/aws **~> 6.68**, S3 backend를 선언한다. 실제 선택 provider 버전은 각 stack의 .terraform.lock.hcl이 기록한다. backend의 버킷·key·프로필·잠금 설정은 [실행기](../scripts/infra.ps1.md)가 init 인수로 전달한다.

서브넷 기본 경로는 foundation/network, 상대 VPC 경로는 connectivity/peering, SG 규칙은 workload/security-rules가 소유한다. 같은 자원을 서로 다른 상태에 중복 정의하지 않는다.

## model

원본: [modules/model/main.tf](../../../infra/terraform/modules/model/main.tf). AWS 자원 모듈 공통 입력을 검사하고 역할 연결을 계산한다.

| 선언 | 역할 |
| --- | --- |
| variable topology | 정확히 5계정, 서울 리전 A·C AZ ID, VPC /16, 노드·서브넷·디스크 설정 검사 |
| variable traffic | CIDR, 포트 범위, connections의 포트 키 검사 |
| local.roles / local.groups | 서버 역할과 활성 ALB 역할을 계정별 SG 목록으로 구성 |
| local.flow_list / local.flows | connections의 역할 관계를 실제 계정/역할 쌍으로 확장 |
| terraform_data.configuration | 존재하지 않는 역할, 중복·잘못된 Peering 이름, ALB 대상 조건을 precondition으로 검사 |
| outputs | topology, traffic, roles, flows |

예를 들어 game→kafka는 현재 account1/game에서 account3·4·5/kafka로 펼쳐진다. 같은 역할 간 연결은 같은 SG를 참조하는 조합도 포함한다. 이 결과는 허용 규칙의 입력이지 실제 트래픽이나 런타임 호출 그래프가 아니다.

## network

원본: [modules/network/main.tf](../../../infra/terraform/modules/network/main.tf), [versions.tf](../../../infra/terraform/modules/network/versions.tf).

- 입력: name, cidr, az_ids, public_subnets, egress.
- 각 VPC에 private_a·private_c를 /24로 생성한다. /16 기준 세 번째 옥텟은 10·11이다.
- public_subnets가 true이면 public_a·public_c(/24, 옥텟 0·1)와 IGW를 생성한다.
- 각 서브넷에 별도 라우팅 테이블과 명시적 연결을 생성한다. Public의 기본 경로는 IGW다.
- egress가 nat이면 Public A·C에 각각 EIP와 **연결 유형 public** NAT를 생성하고, Private 기본 경로를 같은 논리 AZ NAT에 연결한다.
- proxy와 none에서는 Private 기본 인터넷 경로를 만들지 않는다. Proxy 프로그램을 설치하거나 Bastion을 라우트 대상으로 지정하지 않는다.
- 출력: vpc_id, subnet_ids, route_table_ids, nat_gateway_ids, nat_routes.

## security-groups와 security-rules

| 원본 파일 | 입력·생성·출력 |
| --- | --- |
| [security-groups/main.tf](../../../infra/terraform/modules/security-groups/main.tf), [versions.tf](../../../infra/terraform/modules/security-groups/versions.tf) | name·vpc_id·roles로 역할별 aws_security_group 생성. ids 출력. 규칙은 workload가 소유 |
| [security-rules/main.tf](../../../infra/terraform/modules/security-rules/main.tf), [versions.tf](../../../infra/terraform/modules/security-rules/versions.tf) | ingress·egress·public_ingress·public_egress map으로 독립 SG 규칙 생성 |

security-rules는 SG 참조용 peer 규칙과 IPv4 CIDR용 public 규칙을 각각 입출력으로 나눠 만든다. 모두 TCP 단일 포트 범위이며 OS 사용자·파일 권한이나 DB 권한은 설정하지 않는다. 출력은 ingress, egress, public_ingress다.

## peering

원본: [modules/peering/main.tf](../../../infra/terraform/modules/peering/main.tf). 이 파일에 provider 요구사항과 requester/accepter alias 선언도 들어 있다.

입력은 name, requester, accepter다. 각 상대 객체는 foundation 출력의 VPC·계정·리전·CIDR·라우팅 테이블 정보를 사용한다.

요청 계정에서 연결을 만들고 수락 계정에서 auto_accept로 수락한다. 양쪽 DNS resolution 옵션을 설정하고, **전달받은 양쪽의 모든 라우팅 테이블**에 상대 VPC CIDR → 해당 Peering 경로를 만든다. Public 테이블도 전달되면 포함된다. 출력은 id, requester_routes, accepter_routes다.

## compute

원본: [modules/compute/main.tf](../../../infra/terraform/modules/compute/main.tf), [versions.tf](../../../infra/terraform/modules/compute/versions.tf).

| 선언 | 담당 내용 |
| --- | --- |
| aws_key_pair.this | 계정 공개키 등록 |
| aws_instance.this | 노드 키를 for_each로 사용. 계정 AMI·노드 사양·서브넷·역할 SG·키페어 연결 |
| root_block_device | 암호화 gp3, root_gib 크기, delete_on_termination = true |
| metadata_options / credit_specification | IMDSv2 토큰 필수, CPU 크레딧 unlimited |
| user_data | /etc/aws-infra/node.json에 이름·역할·계정 기록 |
| local.disks / aws_ebs_volume.data | 노드/디스크 키로 별도 암호화 EBS 생성. EC2와 같은 AZ, prevent_destroy = true |
| aws_volume_attachment.data | 설정한 device_name으로 EBS 연결 |
| aws_eip.this / aws_eip_association.this | public_ip가 true인 노드에 EIP 생성·연결 |

instances 출력은 노드별 ID, role, private_ip, public_ip, instance_type, availability_zone, data_volumes다. OS 설치 이후 프로그램 설치·EBS 포맷/마운트·DB 초기화는 하지 않는다. [bootstrap 경계](../bootstrap/README.md)를 함께 확인한다.

## alb

원본: [modules/alb/main.tf](../../../infra/terraform/modules/alb/main.tf), [versions.tf](../../../infra/terraform/modules/alb/versions.tf).

입력은 name, vpc_id, subnet_ids, sg_id, certificate_arn, frontend_targets, game_targets, 두 대상 포트와 static_path·두 health_path다.

인터넷 공개 ALB, frontend/game HTTP 대상 그룹과 EC2 연결, HTTP 80→HTTPS 443 리다이렉트, 인증서가 연결된 HTTPS listener를 만든다. HTTPS 기본 대상은 game이며 우선순위 10의 static_path 규칙은 frontend로 보낸다. 현재 설정은 /static/*→80, 기본→8000이고 health check 성공 코드는 200~399다. 출력은 dns_name이다.

## 수정 후 확인 위치

모듈을 바꾸면 사용하는 stack과 [Terraform 모의 테스트](../tests/README.md)를 함께 확인한다. provider 버전 변경 시 해당 versions.tf와 lock 파일을 같이 검토한다. 이 문서는 코드의 자원 선언과 관계를 대조했으며 Terraform validate·test 또는 AWS 배포 성공을 대신하지 않는다.
