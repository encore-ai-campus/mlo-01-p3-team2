# Terraform 코드 지도

[탐색 시작점](../ROUTING-README.md) · [설정 지도](../config/README.md)

## 실행 단위와 상태 소유권

| stack | 실행 대상 | 모듈 | 상태 출력 |
| --- | --- | --- | --- |
| [foundation](stacks/foundation.md) | account1~account5 각각 | model, network, security-groups | foundation |
| [connectivity](stacks/connectivity.md) | shared | model, peering × 설정된 계정 쌍 | connections, foundation_vpcs |
| [workload](stacks/workload.md) | account1~account5 각각 | model, security-rules, compute, 해당 시 alb | inventory |
| [bastion](stacks/bastion.md) | account1 선택 생성·삭제 | model, bastion | bastion |

네 stack의 versions.tf는 Terraform **>= 1.11, < 2.0**, hashicorp/aws **~> 6.68**, S3 backend를 선언한다. 실제 선택 provider 버전은 각 stack의 .terraform.lock.hcl이 기록한다. backend의 버킷·key·프로필·잠금 설정은 [실행기](../scripts/infra.ps1.md)가 init 인수로 전달한다.

서브넷 기본 경로는 foundation/network, 상대 VPC 경로는 connectivity/peering, SG 규칙은 workload/security-rules가 소유한다. 같은 자원을 서로 다른 상태에 중복 정의하지 않는다.

## model

원본: [modules/model/main.tf](../../../infra/terraform/modules/model/main.tf). AWS 자원 모듈 공통 입력을 검사하고 역할 연결을 계산한다.

| 선언 | 역할 |
| --- | --- |
| variable topology | 정확히 5계정, 서울 리전 A·C AZ ID, VPC /16, 노드·서브넷·디스크 설정 검사 |
| variable traffic | CIDR, 포트 값, connections의 시작·끝 포트 키와 순서 검사. port_end는 선택 항목 |
| local.roles / local.groups | 서버 역할과 활성 ALB 역할을 계정별 SG 목록으로 구성 |
| local.flow_list / local.flows | connections의 역할 관계를 실제 계정/역할 쌍으로 확장하고 port·port_end를 전달 |
| terraform_data.configuration | 존재하지 않는 역할, 중복·잘못된 Peering 이름, ALB 계정의 Public 서브넷과 같은 계정의 frontend·game·ad 대상 존재를 precondition으로 검사 |
| outputs | topology, traffic, roles, flows |

예를 들어 game→kafka는 현재 account1/game에서 account3·4·5/kafka로 펼쳐진다. 같은 역할 간 연결은 같은 SG를 참조하는 조합도 포함한다. 이 결과는 허용 규칙의 입력이지 실제 트래픽이나 런타임 호출 그래프가 아니다.

현재 nodes 객체에는 노드별 enabled 필드가 없다. workload는 account 일치와 role != bastion으로 서비스 EC2만 선택한다. topology.nodes.bastion은 foundation SG·SSH·Proxy 역할 계산과 전용 bastion 단계 입력으로 유지한다. alb.enabled는 ALB 활성화 여부만 제어한다. alb.certificate_arn은 공통 입력 타입에 남아 있지만 현재 HTTP ALB 모듈에는 전달하지 않으며 빈 문자열도 허용한다.

port_end를 생략하면 flow의 끝 값은 시작 포트와 같다. 지정된 끝 키는 ports에 존재하고 시작 이상이어야 한다. [model 포트 범위 테스트](../../../infra/terraform/modules/model/tests/port-ranges.tftest.hcl)는 이 조건과 Spark SG 조합 확장을 검사하도록 선언돼 있다. 실제 SG 속성·중복 범위 병합 검사는 [테스트 지도](../tests/README.md#spark-포트-범위)에서 이어서 확인한다.

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

security-rules는 SG 참조용 peer 규칙과 IPv4 CIDR용 public 규칙을 각각 입출력으로 나눠 만든다. peer 규칙은 TCP port부터 선택적 port_end까지 허용하며, 끝 값이 없으면 단일 포트다. public 규칙은 기존 TCP 단일 포트를 유지한다. OS 사용자·파일 권한이나 DB 권한은 설정하지 않는다. 출력은 ingress, egress, public_ingress다. [포트 범위 테스트](../tests/README.md#spark-포트-범위)는 모델 입력, 실제 규칙 속성, workload의 합집합 전달을 구분해 검사한다.

## peering

원본: [modules/peering/main.tf](../../../infra/terraform/modules/peering/main.tf). 이 파일에 provider 요구사항과 requester/accepter alias 선언도 들어 있다.

입력은 name, requester, accepter다. 각 상대 객체는 foundation 출력의 VPC·계정·리전·CIDR·라우팅 테이블 정보를 사용한다.

요청 계정에서 연결을 만들고 수락 계정에서 auto_accept로 수락한다. 양쪽 DNS resolution 옵션을 설정하고, **전달받은 양쪽의 모든 라우팅 테이블**에 상대 VPC CIDR → 해당 Peering 경로를 만든다. Public 테이블도 전달되면 포함된다. 출력은 id, requester_routes, accepter_routes다.

## compute

원본: [modules/compute/main.tf](../../../infra/terraform/modules/compute/main.tf), [versions.tf](../../../infra/terraform/modules/compute/versions.tf).

| 선언 | 담당 내용 |
| --- | --- |
| aws_key_pair.this | 계정 공개키 등록 |
| aws_instance.this | 노드 키를 for_each로 사용. 계정 AMI·노드 사양·서브넷·역할 SG·키페어 연결. associate_public_ip_address는 노드 public_ip 사용 |
| root_block_device | 암호화 gp3, root_gib 크기, delete_on_termination = true |
| metadata_options / credit_specification | IMDSv2 토큰 필수, CPU 크레딧 unlimited |
| user_data | /etc/aws-infra/node.json에 이름·역할·계정 기록 |
| local.disks / aws_ebs_volume.data | 노드/디스크 키로 별도 암호화 EBS 생성. EC2와 같은 AZ, 현재 prevent_destroy = true |
| aws_volume_attachment.data | 설정한 device_name으로 EBS 연결 |
| aws_eip.this / aws_eip_association.this | public_ip가 true인 노드에 EIP 생성·연결 |

instances 출력은 노드별 ID, role, private_ip, public_ip, instance_type, availability_zone, data_volumes다. OS 설치 이후 프로그램 설치·EBS 포맷/마운트·DB 초기화는 하지 않는다. [bootstrap 경계](../bootstrap/README.md)를 함께 확인한다.

현재 데이터 EBS의 Terraform 삭제 보호는 prevent_destroy=true다. 데이터 삭제·교체 Plan은 이 보호 때문에 실패할 수 있다. 전체 삭제의 DeleteDataVolumes는 데이터 삭제 선택이며 보호 해제 옵션이 아니다. Destroy와 DisableDataVolumeProtection을 함께 지정하면 이 선언을 Plan 전에 잠시 false로 바꾸고 종료 시 원래 바이트로 복원한다. 별도 Plan·Apply에서는 자동 변경하지 않으며 직접 설정을 바꾸면 새 Plan을 준비해야 한다. 삭제 흐름은 [전체 삭제 문서](../scripts/destroy-all.ps1.md)에 있다.

## bastion

원본: [modules/bastion/main.tf](../../../infra/terraform/modules/bastion/main.tf), [versions.tf](../../../infra/terraform/modules/bastion/versions.tf). 전용 [bastion stack](stacks/bastion.md)에서만 호출한다.

입력은 name, account_key, ami_id, instance_type, root_gib, subnet_id, sg_id, key_name, public_key다. 전용 aws_key_pair와 aws_instance 각 하나를 만든다. Public A에서 자동 공인 IP를 받고 EIP 자원은 없다. 루트 디스크는 암호화 gp3·delete_on_termination=true, IMDSv2 필수, CPU 크레딧 unlimited다. user_data는 Bastion 역할 정보만 기록하며 Proxy를 설치하지 않는다.

instance 출력은 id, public_ip, private_ip, root_volume_id, key_name이다. VPC·서브넷·SG·규칙·서비스 서버·별도 데이터 EBS는 이 모듈이 생성하거나 삭제하지 않는다.

## alb

원본: [modules/alb/main.tf](../../../infra/terraform/modules/alb/main.tf), [versions.tf](../../../infra/terraform/modules/alb/versions.tf).

입력은 name, vpc_id, subnet_ids, sg_id, frontend_targets, game_targets, ad_targets, 세 대상 포트(frontend_port, game_port, ad_port)와 static_path·ad_path 및 세 health_path(frontend_health_path, game_health_path, ad_health_path)다. certificate_arn 입력과 ACM ARN precondition은 제거됐다.

인터넷 공개 ALB, frontend/game/ad HTTP 대상 그룹과 EC2 연결, HTTP 80 listener를 만든다. HTTP 기본 대상은 game이며 같은 listener의 우선순위 10 static_path 규칙은 frontend, 우선순위 20 ad_path 규칙은 ad로 보낸다. 현재 설정은 /static/*→Front 두 대의 80, /ads/*→ad-server 한 대의 8000, 기본→game-server 한 대의 8000이다. 광고 요청의 경로는 변경하지 않는다. HTTPS 443 listener와 HTTPS 리다이렉트는 없다. 출력은 dns_name이며 http://{dns_name}/ads/ 형식으로 광고 경로에 접속한다.

세 대상 그룹의 health check 경로는 현재 /, 성공 코드는 200~399다. 광고 Django의 실제 URL과 / 응답 여부는 애플리케이션 소스가 없어 확인하지 못했다. EC2 생성과 대상 등록은 웹서버·Django 설치나 healthy 상태를 보증하지 않는다. ALB 외부 인바운드는 [workload](stacks/workload.md)의 game_client_cidrs → TCP 80 규칙으로 제한한다.

## 수정 후 확인 위치

모듈을 바꾸면 사용하는 stack과 [Terraform 모의 테스트](../tests/README.md)를 함께 확인한다. provider 버전 변경 시 해당 versions.tf와 lock 파일을 같이 검토한다. 이 문서는 코드의 자원 선언과 관계를 대조했으며 Terraform validate·test 또는 AWS 배포 성공을 대신하지 않는다.
