# infra/scripts/lib/infra-common.ps1

[탐색 시작점](../../ROUTING-README.md) · [원본 파일](../../../../infra/scripts/lib/infra-common.ps1) · [호출하는 실행기](../infra.ps1.md)

PowerShell 5.1 공통 함수 모음이다. 아래 선언은 원본 PowerShell을 대조한 것이며 Python AST 스킬로 검증한 결과가 아니다.

| 함수 | param 선언 | 역할 |
| --- | --- | --- |
| Read-InfraJson | ([string]$Path) | 파일을 읽어 ConvertFrom-Json 결과 반환 |
| Get-InfraFileHash | ([string]$Path) | 파일 바이트의 SHA-256을 계산하고 스트림·알고리즘 객체 정리 |
| Write-InfraJson | ([string]$Path, $Value) | 깊이 30의 JSON을 UTF-8 BOM 없이 저장 |
| Invoke-InfraTerraform | ([string]$Command, [string]$Directory, [string[]]$Arguments) | -chdir로 실행하고 0이 아닌 종료 코드를 오류로 전달 |
| Assert-InfraConfiguration | ($Topology, $Traffic) | 계정·VPC·송신 방식·외부 CIDR·포트 검사 |
| Assert-InfraBackend | ($Backend, $Topology) | S3 버킷 이름·key_prefix 형식·리전·등록 프로필 검사 |
| Get-InfraWorkPath | ([string]$Root, [string]$Account, [string]$Stage, [string]$ConfigurationDirectory) | 기본 경로는 유지하고 별도 구성의 로컬 Plan·출력 경로를 구성 경로 해시로 분리 |
| Get-InfraFingerprint | ([string]$Root, [string]$PublicKeyPath, [string]$ConfigurationDirectory) | 배포 입력 파일 목록과 각 해시를 합쳐 전체 fingerprint 생성 |
| Assert-InfraBastionPlan | ($Plan, [ValidateSet('Create','Delete')][string]$Mode, [string]$Account, [string]$Project) | Bastion 전용 자원·변경 종류·기존 자원 태그 검사 |

## 설정 검사의 범위

Assert-InfraConfiguration은 정확히 account1~account5가 있는지, ID·profile·VPC CIDR이 중복되지 않는지 확인한다. ID는 12자리, VPC는 IPv4 /16 형식이며 송신 방식은 proxy/nat/none 중 하나다. nat에는 public_subnets가 필요하다.

관리자·서비스 CIDR과 선택적 public_http_cidrs의 옥텟과 prefix, 네트워크 주소 정규화를 검사한다. 관리자 SSH의 0.0.0.0/0은 거부하며 포트는 1~65535 정수여야 한다. 전체 서버 스키마·역할 참조·Peering 관계 검사는 [model 모듈](../../terraform/README.md#model)이 추가로 담당한다.

Assert-InfraBackend는 로컬 값의 형식을 검사한다. 실제 AWS 계정·버킷 접근과 버전 관리는 호출자인 infra.ps1에서 AWS CLI로 검사한다.

## fingerprint에 들어가는 파일

- infra/config 바로 아래의 JSON 파일.
- infra/terraform 아래의 .tf 및 .terraform.lock.hcl 파일. .terraform 캐시 내부는 제외한다.
- infra/scripts/infra.ps1, infra/scripts/bastion.ps1, infra/scripts/destroy-all.ps1 및 infra/scripts/lib 바로 아래의 .ps1 파일.
- 선택한 공개키 파일이 존재하면 그 내용의 해시.
- ConfigurationDirectory를 지정하면 해당 topology.tfvars.json·traffic.tfvars.json의 절대 경로와 내용 해시.

Markdown, 로컬 상태·계획·캐시, .tftest.hcl, prepare-key.sh, 설치 스크립트는 이 함수의 목록에 포함되지 않는다. 이 해시는 실행기의 저장 계획 유효성 검사에 사용하며, 프로젝트의 모든 파일이나 실제 AWS 상태를 비교하는 해시는 아니다.

## Bastion 저장 계획 검사

Assert-InfraBastionPlan은 planned_values·prior_state와 resource_changes를 대조한다. 허용하는 managed 주소는 module.model.terraform_data.configuration, module.bastion.aws_instance.this, module.bastion.aws_key_pair.this뿐이다. Create는 no-op/create/update, Delete는 no-op/delete만 허용하고 교체·import·deferred 변경은 거부한다. 기존 EC2·키페어의 Project·Account·Stage=bastion 태그도 검사한다.

실제 AWS에서 전용 상태 밖의 기존 Bastion을 찾는 검사는 호출자인 [infra.ps1](../infra.ps1.md)의 Assert-SavedBastionPlan이 담당한다. 기존 workload 자원의 자동 이관 기능은 아니다.

## 2026-10-12 학원 접속 범위

- 학원 공인 IP는 `222.112.208.69/32`다. 앞서 전달된 `.72`는 사용하지 않는다.
- `admin_public_cidrs`: 학원 IP. Bastion SSH 22 및 Private 서버의 역할별 SG에 학원 IP의 SSH 22를 허용한다.
- `public_http_cidrs`: `0.0.0.0/0`. Public Front의 HTTP 80만 전체 공개한다. 필드가 없는 이전 프로필은 game_client_cidrs로 동작한다.
- `game_client_cidrs`: 학원 IP. 기존 edge HTTPS 443 범위를 전체 공개로 확대하지 않는다.
- Bastion의 EC2 Instance Connect 콘솔 SSH 출처 규칙은 생성하지 않는다. 기존 규칙이 있다면 다음 workload Plan에 해당 규칙 삭제가 표시된다. 서비스 서버의 기존 콘솔 SSH 규칙은 유지한다.
- Private SSH CIDR 규칙은 인터넷 경로를 만들지 않는다. Bastion 경유 시 목적 서버에는 Bastion 사설 IP가 출처로 보이므로 기존 Bastion→서버 SG 규칙도 유지한다. OS 방화벽·접속 경로의 실제 성공은 별도다.
- 기존 저장 Plan은 다시 만들어야 한다. 코드만 수정했으며 AWS Apply는 실행하지 않았다.
