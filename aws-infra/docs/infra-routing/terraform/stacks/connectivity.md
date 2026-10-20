# connectivity: 5개 계정 사이의 연결

[탐색 시작점](../../ROUTING-README.md) · [peering 모듈](../README.md#peering)

## 파일과 책임

| 파일 | 확인할 내용 |
| --- | --- |
| [main.tf](../../../../infra/terraform/stacks/connectivity/main.tf) | 10개 계정 조합의 모듈 선언, peerings 포함 여부로 count 결정, connections 출력 |
| [providers.tf](../../../../infra/terraform/stacks/connectivity/providers.tf) | aws.account1~aws.account5 alias, 각 profile·allowed_account_ids |
| [states.tf](../../../../infra/terraform/stacks/connectivity/states.tf) | 5개 foundation 원격 상태와 postcondition, foundation_vpcs 출력 |
| [variables.tf](../../../../infra/terraform/stacks/connectivity/variables.tf) | 공통 입력과 model 호출 |
| [versions.tf](../../../../infra/terraform/stacks/connectivity/versions.tf) | Terraform/provider 범위, S3 backend |

## 연결 흐름

5개 계정의 foundation이 먼저 있어야 한다. states.tf는 S3의 각 foundation 출력을 읽고 account_id·account_key·region·vpc_cidr·az_ids가 현재 설정과 맞는지 검사한다.

main.tf의 각 계정 쌍은 명시적인 requester/accepter provider를 사용한다. 현재 10쌍을 전부 켰으며 topology.peerings에서 해당 이름을 빼면 그 쌍의 count가 0이 된다. provider alias는 설정에서 임의의 계정 수로 자동 생성되지 않으며, 현 구현은 5계정으로 고정돼 있다.

peering 모듈이 연결 요청·수락·DNS 옵션·양방향 상대 VPC 경로를 관리한다. 연결만 만들고 라우팅을 다른 stack에 맡기는 구조가 아니다.

## 출력과 상태

- connections: 계정 쌍 이름 → Peering ID.
- foundation_vpcs: 계정 키 → 연결 구성에 사용한 VPC ID.
- S3 key: {key_prefix}/shared/connectivity/terraform.tfstate.

workload는 foundation_vpcs가 현재 foundation VPC와 같은지, 역할 간 통신에 필요한 계정 쌍이 connections에 있는지 검사한다. 이 검사는 상태 출력의 일관성 검사이며 실제 패킷 전달·SG 허용·프로그램 수신을 확인하는 것은 아니다.
