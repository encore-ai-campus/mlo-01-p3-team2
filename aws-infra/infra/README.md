# 5개 계정 공통 실행 안내

현재 실행 코드는 **C:\third_project\aws-infra\infra** 아래에 있다.
설계 설명은 [terraform-restructure-plan.md](terraform-restructure-plan.md), 서버 설치 범위는 [bootstrap/README.md](bootstrap/README.md)를 참고한다.
팀원 Windows PC의 도구 준비는 [setup-windows/README.md](setup-windows/README.md)를 참고한다.
명령어의 각 옵션과 계정별 배포 대상은 [실행 명령어와 계정별 구성](scripts/README.md)에 정리했다.

**이 개편에서는 AWS 자원 생성·변경·삭제를 실행하지 않았다.**
기존 로컬 Terraform 상태를 새 S3 상태로 이관하지도 않았다. 새 코드를 기존 자원에 연결하려면 적용 전에 유지·이관·교체 범위를 정해야 한다.

## 1. 어디를 수정하는가

| 파일 | 역할 |
|---|---|
| [config/topology.tfvars.json](config/topology.tfvars.json) | 5개 계정·16대 서버의 배치, 사양, AZ, 디스크, AMI, 공개키, ALB |
| [config/traffic.tfvars.json](config/traffic.tfvars.json) | 관리자 IP, 서비스 공개 범위, 서비스 간 포트 |
| [config/backend.json](config/backend.json) | 공통 S3 상태 버킷과 접근 프로필 |
| [scripts/infra.ps1](scripts/infra.ps1) | 계정·단계를 선택하는 공통 실행기 |
| [scripts/prepare-key.sh](scripts/prepare-key.sh) | SSH 키가 없을 때만 사용하는 선택 도구 |
| [setup-windows/install-tools.ps1](setup-windows/install-tools.ps1) | Windows PC에 Terraform·AWS CLI를 설치하는 도구 |

설정은 Terraform과 PowerShell이 함께 읽는 JSON 형식이다. JSON 파일에는 주석을 넣지 않는다.
AWS 액세스 키·시크릿 키는 이 파일들에 넣지 않고 기존 CLI 프로필을 사용한다.

## 2. 현재 반영한 배치와 기본값

- 계정별 서버 수: **4 / 3 / 4 / 2 / 3대**, 전체 16대.
- 논리 A = **apne2-az1**, 논리 C = **apne2-az3**. 기존 네트워크 상태에서 확인한 물리 AZ ID이며, 계정별 콘솔의 a/c 글자와 항상 같다는 뜻은 아니다.
- 계정별 VPC: **10.10 / 10.20 / 10.30 / 10.40 / 10.50.0.0/16**.
- 각 VPC의 Private A·C는 세 번째 옥텟 10·11인 /24, Public A·C는 0·1인 /24로 만든다.
  예: Account 1은 10.10.10.0/24, 10.10.11.0/24, 10.10.0.0/24, 10.10.1.0/24.
- 비용 문서의 현재 가정대로 Account 1만 Public 서브넷·IGW를 만들고, **NAT 0개 + Bastion Forward Proxy**를 선택했다.
- Bastion과 Front 2대에 고정 EC2 공인 IP 각 1개, Account 1에 ALB 1개.
- OS 디스크는 20GiB/대. 150명 비용 가정에 맞춘 초기 데이터 디스크는 Mongo 900GiB/대, Kafka 200GiB/대, Spark 100GiB/대, MySQL 100GiB/대다. **실측 권장 용량이 아니라 기존 견적의 입력값**이다.
- 관리자 SSH와 ALB 외부 공개 CIDR은 비어 있다. 채우기 전에는 외부에서 접속할 수 없다.
- 보안그룹은 역할별 통신에 필요한 TCP 포트만 연다. 서버 사용자·파일 권한을 설정하지 않는다.
- 기본 ALB는 HTTP 80을 HTTPS 443으로 돌리고, /static/*는 Front HTTP 80, 나머지 경로는 game HTTP 8000으로 보낸다. 아직 실제 앱의 경로·헬스 체크를 검증한 설정은 아니므로 배포 전에 맞춘다.

Proxy 프로그램은 자동 설치하지 않는다. 서비스 간에는 사설 Peering 경로를 사용하고,
인터넷 HTTPS는 애플리케이션의 Proxy 설정과 실제 Proxy 서비스가 있어야 사용할 수 있다.
Private 서브넷의 기본 라우트를 Bastion이나 다른 VPC의 IGW에 연결하는 구성이 아니다.

NAT로 바꾸려면 해당 계정의 topology 설정에서 public_subnets를 true, egress를 "nat"으로 바꾼다.
foundation이 **Public A·C에 public NAT를 하나씩** 만들고 **각 Private 서브넷을 같은 AZ NAT로 라우팅**한다.
클라이언트의 직접 HTTPS 송신이 필요하면 traffic의 internet_https_roles와 프로그램의 Proxy 설정도 함께 조정한다.

## 3. 실제 배포 전 채울 값

| 설정 | 필요한 값 |
|---|---|
| backend.bucket | 이미 준비한 S3 상태 버킷 이름. 현재 빈칸 |
| backend.region / profile | 그 버킷의 리전과 접근할 CLI 프로필. 기본 프로필 account1 |
| accounts.*.ami_id | 서울 리전에서 사용할 Ubuntu 24.04 x86_64 AMI. 현재 빈칸 |
| accounts.*.ssh_public_key_path | 해당 계정 EC2에 등록할 OpenSSH 공개키 파일 |
| alb.certificate_arn | Account 1·서울 리전의 ACM 인증서 ARN. 현재 빈칸 |
| traffic.admin_public_cidrs | 팀원의 관리자 공인 IPv4 CIDR, 개인 IP는 /32 |
| traffic.game_client_cidrs | 서비스에 접속할 사용자 IPv4 CIDR |

공개키의 상대 경로는 `infra/`를 기준으로 해석한다.
기존 Account 1 공개키만 config/keys/account1.pub로 복사했다.
Account 2~5의 공개키 경로는 비워 두었다. 팀이 같은 공개키를 사용하기로 했다면 동일한 .pub 경로를 명시할 수 있다.
개인키는 각자의 PC에서 보관하며 Terraform에 전달하지 않는다. 새 키를 만들 필요가 없다면 prepare-key.sh를 실행하지 않는다.

계정 ID와 프로필은 기존 설정에서 옮겼고 Account 1 프로필은 실제 등록된 account1로 맞췄다.

| 이름 | 계정 ID | CLI 프로필 |
|---|---|---|
| account1 | 541308265856 | account1 |
| account2 | 529088287882 | account2 |
| account3 | 667879771148 | account3 |
| account4 | 688567306400 | account4 |
| account5 | 217016296352 | account5 |

Plan·Apply·Output은 실제 프로필의 계정 ID를 STS로 확인한다.
이미 등록한 자격 증명이 유효하면 매번 브라우저 로그인할 필요가 없다. 실행기가 login.ps1이나 aws login을 호출하지 않는다.

상태 버킷에는 버전 관리가 켜져 있어야 한다. 실행기는 이를 조회하고, 꺼져 있으면 중단한다.
버킷 자동 생성·권한 수정은 하지 않는다. backend 프로필에는 버전 관리 상태 조회·객체 목록/읽기/쓰기와
잠금 파일(.tflock)의 읽기/쓰기/삭제 권한이 필요하다. 다른 stack의 상태를 읽는 데도 이 프로필을 사용한다.
[S3 backend 공식 권한 안내](https://developer.hashicorp.com/terraform/language/backend/s3#permissions-required)

## 4. 실행 순서

`-Account`·`-Stage`·`-Action`의 의미, 5개 계정의 서버 목록, 단계별 명령 예시는 [실행 상세 안내](scripts/README.md)를 참고한다.

필요 도구: **Terraform 1.11 이상 2.0 미만**, AWS CLI, PowerShell 5.1 이상.
AWS provider는 6.x이며 각 stack의 .terraform.lock.hcl에 버전을 고정한다.

작업 경로는 다음과 같이 잡는다.

~~~powershell
Set-Location C:\third_project\aws-infra
~~~

먼저 AWS에 접근하지 않는 정적 검증을 할 수 있다. 최초 init은 provider 다운로드가 필요할 수 있다.

~~~powershell
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Validate
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Validate
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Validate
~~~

Validate는 문법과 스키마를 검사한다. 실제 AMI·권한·서비스 설치나 AWS 연결 성공을 확인하는 명령은 아니다.

실제 구축 순서는 **5개 계정 foundation → 공통 connectivity → 5개 계정 workload**다.
아래 Plan/Apply는 사용자가 검토 후 실행할 명령이며, 이번 개편에서 실행하지 않았다.

~~~powershell
# Account 1의 기반 네트워크 계획을 확인한 뒤 적용한다.
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Apply

# Account 2~5도 계정 이름을 바꾸어 foundation Plan → 검토 → Apply를 수행한다.
# 다섯 계정의 foundation이 모두 끝난 후 공동 연결을 구성한다.
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Plan
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Apply

# 서버·보안그룹 규칙·ALB는 계정마다 계획하고 적용한다.
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Apply

# 계정별 서버 주소와 역할을 JSON으로 저장한다.
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Output
~~~

Apply는 **이미 저장한 계획을 그대로 적용하며 추가 확인창은 띄우지 않는다.**
Plan 출력의 생성·변경·삭제 대상을 확인한 다음 실행한다.
설정·Terraform·실행기·공개키가 바뀌면 Apply를 막으므로 다시 Plan을 만든다.
이번 폴더 이동 전에 저장한 계획도 새 경로에서 Plan을 다시 실행한 뒤 검토한다.
새 Plan이 실패하면 이전 계획을 적용할 수 없게 무효화한다.
팀원이 그 사이 상태를 갱신한 경우 Terraform의 저장 계획 검사도 적용된다.

상태 파일은 하나의 버킷 안에서 다음 11개 경로로 분리한다.

~~~text
aws-infra-v2/account1/foundation/terraform.tfstate
aws-infra-v2/account1/workload/terraform.tfstate
... account2~account5 각각 foundation/workload ...
aws-infra-v2/shared/connectivity/terraform.tfstate
~~~

S3 잠금은 use_lockfile=true를 사용한다. 기본 Terraform workspace만 사용한다.
로컬 작업 파일은 infra/.local/계정/단계 아래에 분리하며 Git에서 제외한다.
S3 잠금과 별개로 같은 PC에서 같은 계정·단계의 실행기를 동시에 실행하지 않는다.

## 5. 변경과 데이터 이전

| 변경 | 수정할 곳 | 적용 범위 |
|---|---|---|
| 같은 계정·AZ의 사양/디스크 용량 | topology.nodes | 해당 workload |
| 노드의 계정·AZ·역할 이동 | topology.nodes | 관련 foundation → connectivity → workload 검토 및 데이터 이전 |
| VPC·AZ ID·NAT 방식 | topology.accounts / az_ids | foundation → connectivity → workload 재검토 |
| 통신 포트·관리자 IP | traffic | 규칙 양끝에 해당하는 workload |
| ALB 경로·헬스 체크 | topology.alb | ALB 계정 workload 및 서버 설정 |

노드 이름과 데이터 디스크 이름은 Terraform 자원 식별자다. 표시 이름처럼 임의로 바꾸지 않는다.
EBS 데이터 볼륨에는 prevent_destroy가 있어 자동 삭제·교체 계획을 막는다.
계정·AZ 이동은 스냅샷/복제·새 대상 준비·데이터 이전·접속 전환 계획이 필요하며 자동 이전하지 않는다.
이 보호를 제거하거나 자원을 state에서 빼는 작업을 일상적인 실행 절차로 사용하지 않는다.
용량 증설 뒤에는 서버 안의 파일시스템 확장이 필요할 수 있다.

기존 Account 1 네트워크는 10.11.0.0/16, 새 배치는 10.10.0.0/16이다.
새 Plan은 기존 자원을 알아서 재사용하지 않으며 추가 자원을 생성하는 계획이 나올 수 있다.
기존 .terraform-state와 새 S3 상태를 구분하고, 실제 교체 방식을 결정한 뒤 적용한다.

## 6. 검증

~~~powershell
# 아래 Terraform 테스트는 AWS provider와 원격 상태를 모의 처리한다.
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Test
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Test
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Test

# Python 3.10 이상: AWS/Terraform CLI 대신 가짜 실행 파일로 실행기 보호 동작을 확인한다.
python .\infra\tests\test_runner.py
~~~

기존 provider 파일을 사용할 때는 -PluginDirectory에 provider 디렉터리를 지정할 수 있다.
테스트용 JSON·임시 계획은 .local/tests 아래에만 생성한다.
테스트는 설치 프로그램의 실제 동작, AWS IAM 권한, 서비스 성능을 보증하지 않는다.

## 7. 이전 파일

대체된 Account 1 스크립트·기존 Terraform 소스·기존 계정 설정은
**C:\third_project\trash\aws-infra-legacy-20261009**에 원래 상대 경로를 유지해 보관한다.
이동 목록은 그 폴더의 manifest.json을 참고한다.

기존 .terraform-state, .terraform 캐시/초기화 정보, SSH 개인키, AWS CLI 프로필은 정리 대상에서 제외했다.
새 실행기는 trash의 파일을 읽지 않는다.
