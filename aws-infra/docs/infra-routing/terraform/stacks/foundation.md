# foundation: 계정별 기반 자원

[탐색 시작점](../../ROUTING-README.md) · [모듈 지도](../README.md)

## 파일과 책임

| 파일 | 확인할 내용 |
| --- | --- |
| [main.tf](../../../../infra/terraform/stacks/foundation/main.tf) | 계정 선택, network/groups 호출, foundation 출력 |
| [provider.tf](../../../../infra/terraform/stacks/foundation/provider.tf) | 대상 계정의 profile·allowed_account_ids, 공통 태그 |
| [variables.tf](../../../../infra/terraform/stacks/foundation/variables.tf) | topology·traffic·account_key·state_backend·ssh_public_key, model 호출 |
| [versions.tf](../../../../infra/terraform/stacks/foundation/versions.tf) | Terraform/provider 범위, S3 backend |

## 처리와 출력

account_key로 accounts에서 한 계정을 선택한다. network에 VPC CIDR·물리 AZ ID·Public 사용 여부·egress를 넘기고, groups에 해당 계정의 역할 목록과 VPC ID를 넘긴다. 원격 상태를 읽지 않는 첫 번째 배포 단계다.

foundation 출력에는 account_key, account_id, region, vpc_cidr, az_ids, vpc_id, subnet_ids, route_table_ids, sg_ids, nat_gateway_ids가 들어간다. connectivity·workload 및 Account 1 bastion이 S3 원격 상태에서 이 출력을 읽고 계정·리전·CIDR·AZ를 대조한다.

현재 Account 1은 Public·Private A/C로 서브넷 4개, 나머지는 Private A/C로 각각 2개다. 모든 계정이 proxy이므로 NAT는 없다. SG는 생성하지만 서비스 간 허용 규칙·서비스 EC2·ALB는 workload에서 만든다. Bastion SG는 EC2가 없는 동안에도 유지하며 Bastion EC2·OS 디스크·전용 키페어는 [bastion 단계](bastion.md)에서 별도로 만든다.

## 변경 영향

VPC·서브넷·AZ·역할 목록이 바뀌면 foundation을 검토한 뒤 connectivity·workload·bastion의 상태 의존성을 확인한다. 계정별 상태 key는 {key_prefix}/{account}/foundation/terraform.tfstate다. 기존 자원의 자동 import나 과거 로컬 상태의 자동 이관은 이 stack에 없다.

## ALB 비활성화 시 SG 정리

기본 및 current 설정의 alb.enabled=false에 따라 ALB 비활성화 직후 account1 역할 SG는 4개였으며 edge-1 추가 후 ad·bastion·frontend·game·edge 5개, 전체 18개다. 기존 ALB SG가 사용 중이면 먼저 account1 workload의 ALB와 참조 규칙을 정리한 뒤 foundation을 적용한다. [배포 순서](../../../deployment-runbook.md#alb-비활성화-적용-순서)를 따른다. foundation.tftest.hcl의 account1_proxy도 ALB 없는 역할 집합을 검사한다.

edge-1의 역할 edge가 기존 model.roles에 반영돼 전용 SG를 만든다. 새 VPC·서브넷·IGW는 추가하지 않는다. ALB 삭제가 미완료인 환경에서는 [edge 추가 순서](../../../deployment-runbook.md#진입용-edge-1-추가)에 따라 기존 SG 참조 정리와 새 SG 생성을 나눈다.
