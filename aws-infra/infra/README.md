# 5개 계정 공통 실행 안내

현재 코드 기준: 2026-10-10. 실행 위치는 C:\third_project\aws-infra이며 코드는 infra/ 아래에 있다. [배포 절차](../docs/deployment-runbook.md), [명령별 실행 안내](scripts/README.md), [코드 지도](../docs/infra-routing/ROUTING-README.md), [서버 설치 경계](bootstrap/README.md)를 함께 사용한다. 이 문서 작업에서는 AWS·Terraform 적용을 실행하지 않았다.

## 1. 수정할 입력과 실행기

| 파일 | 역할 |
| --- | --- |
| [topology.tfvars.json](config/topology.tfvars.json) | 계정·AZ·노드·사양·디스크·AMI·공개키·HTTP ALB |
| [traffic.tfvars.json](config/traffic.tfvars.json) | 관리자/사용자 CIDR, 포트와 역할 연결, 선택적 port_end |
| [backend.json](config/backend.json) | 기존 S3 상태 버킷·프로필·key_prefix |
| [infra.ps1](scripts/infra.ps1) | 계정·단계별 Validate/Test/Plan/Apply/Output |
| [deploy.ps1](scripts/deploy.ps1) | 구성 복사·단계별 배포·현재 IP 인벤토리·프록시 준비 |
| [bastion.ps1](scripts/bastion.ps1) | 별도 Bastion 생성·삭제·전원·현재 주소 조회 |
| [account-keys.ps1](scripts/account-keys.ps1) | 기존 개인키의 공개키 준비·기존 서버 등록 |
| [destroy-all.ps1](scripts/destroy-all.ps1) | 상태 범위 전체 삭제 Plan·적용·진행·잔존 검사 |
| [Windows 도구](setup-windows/README.md) | Terraform·AWS CLI 설치와 인증 준비 |

설정은 JSON이며 주석·AWS 액세스 키를 넣지 않는다. 공개키 상대 경로는 infra 기준이고 개인키는 운영 PC에 보관한다. 비용별 프로필의 topology·traffic을 골라도 backend와 동일 원격 상태를 공유한다.

## 2. 현재 기본값

- 리전 ap-northeast-2, 논리 A=apne2-az1·C=apne2-az3. 계정 콘솔 AZ 이름과 구분한다.
- VPC는 10.10·10.20·10.30·10.40·10.50.0.0/16이다. 각 Private A/C는 /24의 세 번째 옥텟 10/11이다.
- 서비스 서버는 계정별 4/2/4/2/3대, 총 15대다. Bastion은 account1 Public A의 별도 상태로 선택 생성한다. 포함하면 계정별 5/2/4/2/3대, 총 16대다.
- 광고는 account1 Private C다. account1만 Public A/C·IGW·ALB를 만들며 기본 NAT는 0개다.
- Front 두 대에 EIP를 만들고 Bastion은 자동 공인 IP를 사용한다. 서비스 OS 디스크는 20GiB, 별도 데이터 디스크는 [프로젝트 구성표](../README.md#서버-수와-사양)를 따른다.
- ALB는 HTTP 80이며 /static/* → Front:80, /ads/* → ad:8000, 기본 → game:8000이다. ACM ARN을 요구하거나 HTTPS 리스너를 만들지 않는다.
- 현재 관리자·사용자 CIDR은 각각 한 항목이다. 배포 전에 본인의 접속 범위와 맞는지 확인한다. 서비스 콘솔 SSH는 리전별 EC2 Instance Connect IPv4 접두사 목록 → 서비스 역할 SG의 TCP 22 규칙을 별도로 선언한다.

인터넷 다운로드는 [프록시 준비](../../aws-platform/platform/README.md#구성별-프록시-준비-스크립트)가 필요하다. NAT 모드로 바꾸려면 해당 계정의 public_subnets=true·egress=nat로 Public A/C의 AZ별 NAT를 만들고 인터넷 송신 SG·프로그램 Proxy 설정도 맞춘다. 다른 VPC의 NAT를 Peering만으로 공유하는 구성은 아니다.

## 3. 배포 전 확인할 값

현재 기본 파일에는 S3 bucket, 다섯 계정 AMI와 config/keys/account1.pub~account5.pub 경로가 채워져 있다. 채워져 있다는 것만으로 실제 자원·권한·키 일치를 보증하지 않는다. 기본 backend의 bucket은 aws-infra-tfstate-541308265856, region=ap-northeast-2, profile=account1, key_prefix=aws-infra-v2다. AMI 기본값은 ami-0c713e716602facc2다. 선택한 프로필의 실제 값을 사용한다.

| 입력 | 확인 |
| --- | --- |
| 계정 ID·CLI 프로필 | STS 응답과 accounts.*.id가 일치 |
| 상태 버킷 | 버전 관리 Enabled, 상태·잠금 파일 접근 권한 |
| AMI | 선택 리전·x86_64·Ubuntu 24.04와 맞는 실제 이미지 |
| 공개키 | 계정별 개인키와 쌍이며 infra 기준 경로에 존재 |
| 관리자/사용자 CIDR | Bastion SSH / ALB HTTP 접속 범위 |
| ALB 앱 경로 | 실제 /static/*·/ads/*·헬스 체크 응답 |

certificate_arn은 현재 공통 입력 타입에 남아 있지만 HTTP ALB에 전달하지 않는다. 인증서가 없다는 이유로 이 구성의 Plan·Apply를 막지 않는다. 실행기는 로그인·버킷 생성·권한 수정·기존 상태 이관을 자동으로 수행하지 않는다.

## 4. 실행 순서와 상태

도구는 PowerShell 5.1 이상, Terraform >=1.11·<2.0, AWS CLI와 각 계정 인증이다. provider는 ~>6.68이며 각 stack lock 파일을 사용한다. Ansible 연결에는 WSL·가상환경·키도 필요하다.

```powershell
Set-Location C:\third_project\aws-infra
# 먼저 정적 검사를 한다. provider가 없으면 다운로드가 필요할 수 있다.
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Validate
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Validate
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Validate
# foundation은 account1~5 각각 Plan → 검토 → Apply한다.
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Apply
# 다섯 foundation 완료 후 연결을 구성한다.
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Plan
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Apply
# workload도 account1~5 각각 같은 순서로 진행한다.
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Apply
# 별도 Bastion 계획을 검토한 뒤 생성한다.
.\infra\scripts\bastion.ps1 -Action PlanCreate
.\infra\scripts\bastion.ps1 -Action Create
```

Apply는 저장 계획을 추가 확인창 없이 적용한다. Plan의 삭제·교체를 검토하고, 설정·코드·공개키가 바뀌면 새 Plan을 만든다. Apply 성공 후 계획과 manifest는 제거된다. 새 Plan이 실패하면 이전 계획도 적용할 수 없다.

S3 상태는 foundation/workload 계정별 10개와 shared/connectivity 1개, 선택 Bastion의 account1/bastion 1개다. 기본 key는 aws-infra-v2/계정/단계/terraform.tfstate다. S3 use_lockfile과 버전 관리를 사용하고 Terraform workspace는 default다. 로컬 작업은 .local/계정/단계, 다른 프로필은 .local/profiles/구성경로해시/계정/단계로 분리하며 이 분리가 원격 환경 복제를 뜻하지는 않는다.

## 5. 설치·변경·정리

생성 후 Inventory → Proxy는 [deploy.ps1 실행 안내](scripts/README.md#비용별-구성-선택과-일괄-배포)를 따른다. Proxy 완료 후 Vault·데이터 마운트를 준비하고 WSL에서 서비스 역할을 실행한다. 클러스터 설치는 각 역할 전체를 대상으로 검증까지 완료한다.

현재 데이터 EBS의 prevent_destroy=false다. 사양·노드 이름·계정·AZ 변경 계획에 데이터 삭제·교체가 포함될 수 있다. 자동 백업·이전·파일시스템 확장은 없다. 전체 정리는 [삭제 절차](scripts/README.md#15-전체-인프라-삭제)로 분리하고 상태 밖 수동 자원이나 상태 S3 버킷을 삭제한다고 가정하지 않는다.

## 6. 테스트와 이관 이력

[테스트 안내](tests/README.md)는 실행기 모의 테스트·Terraform 테스트·미해결 기대값을 구분한다. Validate·모의 테스트 성공은 실제 IAM·Peering·AMI·서비스 성능 확인과 다르다. 이번 문서 작업에서 이를 재실행하지 않았다.

2026-10-09 개편 당시 대체된 소스는 C:\third_project\trash\aws-infra-legacy-20261009에 보관했다는 기록이 있다. 현재 실행기는 그 파일을 읽지 않는다. 과거 10.11.0.0/16 네트워크·로컬 상태가 새 10.10.0.0/16 S3 구성에 자동 이관된 것은 아니다. 실제 상태·자원 연결은 별도 이관 계획으로 확인한다.
