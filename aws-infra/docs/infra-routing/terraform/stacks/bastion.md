# bastion: 선택 생성·삭제 전용 단계

[탐색 시작점](../../ROUTING-README.md) · [관리 스크립트](../../scripts/bastion.ps1.md) · [Bastion 모듈](../README.md#bastion)

## 파일과 책임

| 파일 | 확인할 내용 |
| --- | --- |
| [main.tf](../../../../infra/terraform/stacks/bastion/main.tf) | Account 1 Bastion 설정·foundation 참조·전용 키 이름·모듈 호출·출력 |
| [states.tf](../../../../infra/terraform/stacks/bastion/states.tf) | Account 1 foundation 원격 상태와 계정·리전·CIDR·AZ·Public A·Bastion SG 검사 |
| [provider.tf](../../../../infra/terraform/stacks/bastion/provider.tf) | Account 1 프로필·allowed_account_ids·Stage=bastion 공통 태그 |
| [variables.tf](../../../../infra/terraform/stacks/bastion/variables.tf) | account_key=account1 제한, topology·traffic·backend·공개키, model 호출 |
| [versions.tf](../../../../infra/terraform/stacks/bastion/versions.tf) | Terraform >= 1.11, < 2.0 · aws ~> 6.68 · S3 backend |
| [.terraform.lock.hcl](../../../../infra/terraform/stacks/bastion/.terraform.lock.hcl) | 실제 선택 provider 버전 |
| [modules/bastion/main.tf](../../../../infra/terraform/modules/bastion/main.tf) | EC2·OS 디스크·전용 키페어. 자동 공인 IP, EIP 없음 |

## 입력과 생성 범위

topology.nodes.bastion과 accounts.account1을 읽는다. 현재 Public A·t3a.small·20GiB 암호화 gp3 루트 디스크다. foundation의 public_a 서브넷과 bastion SG를 사용한다. 출력 precondition은 Account 1의 bastion 역할·Public A·Public 서브넷·public_ip=true·별도 데이터 디스크 없음 조건을 검사한다.

키페어 이름은 account1.key_pair_name에 -bastion을 붙인다. 현재 aws-infra-account1-bastion이며 서비스 키페어 aws-infra-account1과 구분한다. EC2는 자동 공인 IP를 사용하고 EIP를 만들지 않는다. 루트 디스크의 delete_on_termination=true로 EC2 삭제 시 OS 디스크도 삭제한다. model의 terraform_data.configuration도 전용 상태에서 관리한다.

이 stack은 foundation만 원격 상태로 읽는다. connectivity·workload·다른 계정의 서비스 자원을 상태 의존성으로 요구하지 않는다. 실제 SSH·Proxy 통신에는 workload의 해당 SG 규칙이 적용되어 있어야 한다.

## 상태와 저장 계획 보호

- S3 key: {key_prefix}/account1/bastion/terraform.tfstate. 현재 prefix 기준 aws-infra-v2/account1/bastion/terraform.tfstate.
- 로컬 계획·manifest: infra/.local/account1/bastion/.
- PlanCreate → 검토 → Create는 공통 실행기의 PlanMode=Create Plan·Apply에 대응한다.
- PlanDelete → 검토 → Delete는 PlanMode=Delete Plan·Apply에 대응하며 저장 삭제 계획을 적용한다.
- 공통 실행기는 EC2·키페어·model helper 외 변경, 교체·import·deferred 변경, 생성/삭제 계획 혼용을 거부한다. 전용 상태 밖에 기존 Bastion이 있으면 자동 이관하지 않고 중단한다.

전체 인프라 삭제는 별도 [destroy-all.ps1](../../scripts/destroy-all.ps1.md)이 담당한다. 서비스 데이터 EBS의 prevent_destroy는 현재 true다. Plan·Apply와 DeleteDataVolumes만으로는 보호를 해제하지 않으며, Destroy에 DisableDataVolumeProtection을 함께 지정하면 새 Plan 전에 잠시 해제하고 종료 시 원본으로 복원한다. 별도 Plan·Apply에서 보호를 직접 변경했다면 새 삭제 Plan을 준비해야 한다. 기존 Bastion Delete는 전용 상태에만 적용된다.

## 출력

Terraform 출력 이름은 bastion이다. id, public_ip, private_ip, root_volume_id, key_name에 account, account_id, region, ssh_port, ssh_command, proxy_endpoint를 합친다. 공통 실행기 Output은 infra/.local/account1/bastion/outputs.json의 bastion.value에 상태 값을 저장한다.

bastion.ps1의 Status·Output은 Terraform 출력 대신 AWS CLI로 현재 주소를 조회한다. 삭제 후에는 State=Absent를 표시한다. 접속 문자열과 Proxy endpoint는 주소 안내이며 키 인증·Squid 설치·실제 송신 성공을 증명하지 않는다.

## 설치와 재생성 경계

user_data는 /etc/aws-infra/node.json 역할 정보만 기록한다. [install-squid.sh](../../../../../aws-platform/platform/docs/platform-routing/scripts/install-squid.sh.md)의 Squid 설치, Proxy ACL·클라이언트 설정, [팀원 공개키 등록](../../scripts/account-keys.ps1.md)은 별도 작업이다. 재생성 후 공인·사설 주소와 SSH·Proxy 설정을 갱신한다.

Stop·Start·Restart는 같은 EC2의 전원 동작이다. Stop은 루트 디스크 삭제가 아니며, 사용 후 EC2와 OS 디스크를 없애려면 저장된 PlanDelete를 검토한 뒤 Delete를 사용한다.
