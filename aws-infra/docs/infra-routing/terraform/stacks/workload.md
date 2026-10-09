# workload: 보안규칙·서버·디스크·ALB

[탐색 시작점](../../ROUTING-README.md) · [모듈 지도](../README.md) · [통신 설정](../../config/README.md)

## 파일과 책임

| 파일 | 확인할 내용 |
| --- | --- |
| [main.tf](../../../../infra/terraform/stacks/workload/main.tf) | 노드 선택, SG 규칙 계산, compute/alb 호출, inventory 출력 |
| [states.tf](../../../../infra/terraform/stacks/workload/states.tf) | 5개 foundation 및 shared/connectivity 원격 상태, connectivity_ready 검사 |
| [provider.tf](../../../../infra/terraform/stacks/workload/provider.tf) | 선택 계정의 AWS 프로필·계정 제한·태그 |
| [variables.tf](../../../../infra/terraform/stacks/workload/variables.tf) | 공통 입력·SSH 공개키·model 호출 |
| [versions.tf](../../../../infra/terraform/stacks/workload/versions.tf) | Terraform/provider 범위, S3 backend |
| [workload.tftest.hcl](../../../../infra/terraform/stacks/workload/tests/workload.tftest.hcl) | 계정별 서버 배치·기본 외부 차단·Peering 누락 모의 검사 |

## 주요 계산 위치

| 선언 | 의미 |
| --- | --- |
| local.nodes | topology.nodes 중 account가 account_key인 서버만 선택 |
| local.sg_ids | 모든 foundation의 SG ID를 계정/역할 키로 결합 |
| local.ingress_grouped | model.flows 중 대상 계정이 현재 계정인 규칙 |
| local.egress_grouped | model.flows 중 소스 계정이 현재 계정인 규칙 |
| local.admin_ingress | Bastion SG가 있을 때 관리자 CIDR → SSH 포트 |
| local.alb_ingress | 현재 계정 ALB가 활성화됐을 때 사용자 CIDR → 80·443 |
| module.rules | SG쌍/포트 중복을 제거하고 규칙 생성. internet_https_roles에는 외부 TCP 443 egress |
| module.compute | 선택 계정의 서버·키페어·EBS·EIP 생성. rules 이후 실행 |
| module.alb | ALB 대상 계정에만 생성. 같은 계정의 frontend/game 역할 노드를 대상 그룹에 연결 |

규칙 양쪽이 서로 다른 계정이면 소스 계정 workload가 egress, 대상 계정 workload가 ingress를 소유한다. 포트나 관계를 바꿀 때 양쪽 계획을 확인한다. 현재 모든 역할 관계는 [설정 지도](../../config/README.md#traffic)에 정리했다.

## 선행 상태 확인

states.tf는 각 foundation의 계정·리전·CIDR·AZ를 검사한다. terraform_data.connectivity_ready는 연결에 사용한 VPC ID와 현재 VPC ID가 같은지, 모든 계정 간 flow의 Peering 쌍이 존재하는지 검사한다. rules는 이 검사에 의존한다.

선행 상태를 확인해도 AWS의 실제 연결 상태나 프로세스 설치·수신 여부까지 증명하지는 않는다. 프로그램 설치·디스크 마운트는 [bootstrap 범위](../../bootstrap/README.md)다.

## 출력

inventory에는 account, account_id, region, instances, alb_dns_name, proxy_endpoint가 들어간다. instances 내부 필드는 [compute 모듈](../README.md#compute)에 있다. proxy_endpoint는 해당 계정에 bastion 노드가 있을 때 그 사설 IP와 proxy 포트로 만든 문자열이며, Proxy가 실행 중임을 의미하지 않는다.

실행기 Output 결과는 infra/.local/{account}/workload/outputs.json에 Terraform의 output -json 형식으로 저장된다. inventory 내용은 JSON의 inventory.value 아래에 있다.

## 변경 시 경계

SG 규칙·compute·ALB는 하나의 workload 상태로 묶여 있다. 실행기에 보안규칙만 적용하는 별도 Stage는 없다. 데이터 볼륨에는 prevent_destroy가 있지만 OS 루트 디스크는 EC2 종료 시 삭제 설정이다. 배치 이동·이름 변경을 단순 재배포로 취급하지 않는다.
