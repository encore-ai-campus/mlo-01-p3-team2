# Terraform 공통 구성과 이전 기준

갱신일: **2026-10-09**
위치: **C:\third_project\aws-infra\infra**
상태: **공통 코드 구현, AWS 미적용**. 실행 명령과 아직 채울 값은 [README.md](README.md)에 정리했다.

## 1. 합의한 구조

**전체 배치 설정 한곳 + 공통 Terraform 모듈 + 계정별 실행·상태 분리**를 사용한다.
계정별로 network.ps1·security.ps1과 Terraform 코드를 복사하지 않는다.

~~~text
infra/
├── README.md                       # 실행 순서와 배포 전 입력값
├── terraform-restructure-plan.md   # 구조·소유 범위·이전 기준
├── setup-windows/                 # 팀원 Windows PC의 도구 설치
│   ├── README.md                  # 설치 안내와 실행 예시
│   └── install-tools.ps1          # Terraform·AWS CLI 설치
├── scripts/                       # 직접 실행하는 파일과 공통 함수
│   ├── infra.ps1                   # 계정·단계를 받는 공통 실행기
│   ├── prepare-key.sh              # 선택적인 로컬 SSH 키 준비
│   └── lib/infra-common.ps1        # 설정 검사·해시·Terraform 호출
├── config/
│   ├── topology.tfvars.json        # 계정·서버·AZ·사양·디스크·공개키 경로
│   ├── traffic.tfvars.json         # 역할 사이 통신과 외부 CIDR
│   ├── backend.json                # 공유 S3 상태 저장소
│   └── keys/account1.pub           # 기존 공개키의 복사본
├── terraform/
│   ├── modules/
│   │   ├── model/                  # 설정 형식·관계 검사, 역할 관계 계산
│   │   ├── network/                # VPC·서브넷·기본 라우트·선택적 NAT
│   │   ├── security-groups/        # 역할별 보안그룹 자체
│   │   ├── security-rules/         # SG 참조·CIDR 규칙
│   │   ├── compute/                # EC2·별도 EBS·공개키·고정 공인 IP
│   │   ├── alb/                    # ALB·리스너·대상 그룹
│   │   └── peering/                # 요청·수락·양쪽 라우트
│   └── stacks/
│       ├── foundation/             # 단일 계정씩 실행
│       ├── connectivity/           # shared로 한 번 실행
│       └── workload/               # 단일 계정씩 실행
├── bootstrap/README.md             # 서버 내부 설치·배포의 연결 지점
├── tests/                          # 실행기 테스트와 모의 상태
└── .local/                         # 계정별 캐시·계획·출력, Git 제외
~~~

JSON 변수 파일은 PowerShell과 Terraform 양쪽에서 같은 값을 읽기 위해 선택했다.
Terraform module은 재사용 부품, stack은 계획·적용·상태 관리 단위다.
입력·출력이 작은 모듈은 main.tf에 함께 두어 불필요한 파일 분할을 줄였다.

## 2. 처음 적용할 16대 배치

A·C는 **물리 AZ ID**로 고정한다. 현재 A는 apne2-az1, C는 apne2-az3이다.
콘솔에 표시되는 계정별 AZ 이름의 글자가 같다고 같은 물리 AZ라고 가정하지 않는다.

| 계정 / VPC | 서버 키 | 영역 | AZ | 사양 | 별도 데이터 gp3 |
|---|---|---|---|---|---|
| account1 / 10.10.0.0/16 | bastion | Public | A | t3a.small | 없음 |
| account1 | front-a | Public | A | t3a.small | 없음 |
| account1 | front-b | Public | C | t3a.small | 없음 |
| account1 | game-server | Private | A | t3a.large | 없음 |
| account2 / 10.20.0.0/16 | mongo-1 | Private | A | t3a.small | 900GiB |
| account2 | spark-2 | Private | A | t3a.large | 100GiB |
| account2 | ad-server | Private | C | t3a.large | 없음 |
| account3 / 10.30.0.0/16 | kafka-1 | Private | A | t3a.large | 200GiB |
| account3 | mysql-1 | Private | A | t3a.small | 100GiB |
| account3 | spark-1 | Private | A | t3a.large | 100GiB |
| account3 | mongo-2 | Private | C | t3a.small | 900GiB |
| account4 / 10.40.0.0/16 | kafka-2 | Private | A | t3a.large | 200GiB |
| account4 | spark-3 | Private | C | t3a.large | 100GiB |
| account5 / 10.50.0.0/16 | mysql-2 | Private | C | t3a.small | 100GiB |
| account5 | mongo-3 | Private | A | t3a.small | 900GiB |
| account5 | kafka-3 | Private | C | t3a.large | 200GiB |

전체 t3a.small 8대 + t3a.large 8대, OS 디스크는 각각 20GiB.
데이터 디스크는 [상세 비용 문서](../costs/dual-az.md)의 **150명 입력 가정**을 옮겼다.
성능이나 실제 데이터 크기를 측정해서 확정한 값은 아니다.
Front(B)는 이름을 유지한 front-b이며 C에 배치한다. ALB는 Account 1 Public A·C에 걸친 1개다.

## 3. 설정의 책임

topology에서 서버별 account, role, az, subnet_tier, instance_type, root_gib, data_disks를 바꾼다.
서버 이름과 데이터 디스크 이름은 for_each의 고정 키로 사용한다.
계정의 id/profile과 VPC·AMI·SSH 공개키도 이 파일에 모은다.

traffic은 출발 역할 목록 → 도착 역할 목록 → 포트 이름을 정의한다.
model 모듈은 이 관계를 실제 배치된 account/role SG 쌍으로 계산한다.
workload는 해당 계정의 인바운드·아웃바운드만 생성하며, 같은 SG 쌍·포트는 중복 제거한다.

- 동일 리전 Peering으로 연결한 계정끼리는 상대 역할 SG를 참조한다.
- 인바운드·아웃바운드를 모두 필요한 대상·TCP 포트로 제한한다.
- 관리자 IP는 Bastion SSH에, 서비스 공개 CIDR은 ALB 80/443에 적용한다.
- 기본 관리자 CIDR·서비스 공개 CIDR은 빈 배열이다.
- SG는 파일 읽기·수정이나 sudo 권한을 부여하지 않는다.

AWS 인증은 기존 account1~account5 CLI 프로필을 사용한다.
SSH 공개키 등록은 workload가 수행하고, 개인키 생성·보관은 로컬 선택 작업이다.
둘은 서로 대체하는 인증 수단이 아니다.

## 4. 단계별 소유 범위

| 단계 | 실행 범위 | 소유 자원 |
|---|---|---|
| foundation | account1~account5 각각 | VPC, 서브넷, 라우팅 테이블, 기본 라우트, IGW·선택적 NAT, 빈 역할 SG |
| connectivity | shared | 계정 사이 Peering 요청·수락·DNS 옵션·상대 VPC 라우트 |
| workload | account1~account5 각각 | SG 규칙, EC2, EBS, 키페어, 공인 IP, 해당 계정 ALB |

같은 AWS 자원이나 라우트를 두 상태에서 관리하지 않는다.
기본 라우트는 foundation, Peering 라우트는 connectivity, SG 자체는 foundation, SG 규칙은 workload가 맡는다.

~~~mermaid
flowchart TD
  C["topology · traffic 설정"] --> F["5개 계정 foundation"]
  F --> P["shared connectivity"]
  F --> W["5개 계정 workload"]
  P --> W
  W --> O["계정별 서버 주소·역할 출력"]
  O --> B["서버 프로그램 설치·연결 설정·배포"]
~~~

다중 계정 provider를 for_each로 동적으로 바꾸지 않는다.
connectivity에는 5개 provider alias와 10개 계정 쌍을 명시하며, topology.peerings로 활성화 여부를 선택한다.
현재 통신 관계는 Bastion 관리/Proxy와 분산 서비스 복제·소비 때문에 10쌍을 포함한다.
Peering은 중간 VPC를 거쳐 전달하지 않으므로 필요한 계정 쌍을 직접 연결한다.

다른 stack의 상태를 읽을 때 계정 ID·VPC CIDR·리전·AZ를 현재 설정과 비교한다.
workload는 필요한 Peering 유무와 connectivity가 기록한 VPC ID도 확인한다.
foundation 변경 후에는 connectivity를 먼저 갱신한다.

## 5. 인터넷 송신과 ALB

현재 비용 가정은 Account 1의 Bastion/Proxy와 NAT 0개다.
이 기본값을 코드에 옮겼지만 Proxy 프로그램 설치까지 완료한 것은 아니다.
서비스 간 통신은 사설 Peering, 인터넷 HTTPS 송신은 명시적 Forward Proxy를 사용한다.

egress를 nat으로 고르고 public_subnets를 켜면 같은 계정의 Public A·C에 public NAT를 만들고
각 Private 서브넷의 0.0.0.0/0을 같은 AZ NAT로 연결한다.
egress=none도 선택할 수 있다. 이 설정은 기본 인터넷 라우트 선택이며, SG와 앱의 Proxy 설정을 자동 변경하지 않는다.

ALB는 HTTPS 인증서가 필요하다. 초기 경로 가정은 /static/* → Front 80, 기본 경로 → game 8000이다.
실제 Django URL과 정적 파일 배포·헬스 체크에 맞춰 수정한다.
모든 이벤트를 Kafka에 먼저 기록하는 Kappa 흐름은 서버 프로그램에서 구현하며 SG나 ALB만으로 완성되지 않는다.

## 6. 실행기와 상태 분리

infra/scripts/infra.ps1은 Account, Stage, Action을 받는다.
실행 위치와 관계없이 상위 infra 폴더에서 config·terraform·.local을 찾는다.
foundation/workload에는 account1~account5, connectivity에는 shared를 사용한다.
동작은 Validate / Test / Plan / Apply / Output이다.

- Validate: backend 없이 초기화 후 문법·스키마 확인.
- Test: mock provider·mock remote state로 코드 테스트. AWS 배포 없음.
- Plan: 대상 프로필과 backend 프로필의 실제 계정 확인, S3 버전 관리 확인 후 저장 계획 생성.
- Apply: 계정·단계·state key·코드/설정/공개키 해시·계획 파일 해시를 검사하고 저장 계획 적용.
- Output: 상태의 출력을 계정별 outputs.json으로 저장.

새 Plan을 시작하면 이전 계획을 무효화하고, Apply 성공 후 계획을 소비한다.
기존 프로세스의 AWS 환경 자격 증명이 지정한 프로필을 덮어쓰지 않게 격리하고 종료 시 복원한다.
로그인 창을 자동으로 열거나 장기 액세스 키를 파일로 추출하지 않는다.

S3 상태는 key_prefix/accountN/foundation, key_prefix/accountN/workload,
key_prefix/shared/connectivity의 11개 terraform.tfstate로 나눈다.
버킷 버전 관리와 S3 잠금 파일(use_lockfile)을 사용한다.
로컬 TF_DATA_DIR도 계정·단계별로 나누고 Validate/Test용 캐시는 온라인 작업과 분리한다.

버킷 생성·버킷 정책·기존 상태 이관은 자동화하지 않았다.
backend.json의 빈 bucket 값 때문에 현재 상태 그대로 Plan/Apply는 시작할 수 없다.
팀이 실제 사용할 버킷과 접근 권한을 먼저 준비한다.

## 7. 서버 내부 설치와 데이터 보호

compute는 EC2와 암호화된 gp3 디스크, IMDSv2, 역할 메타데이터를 구성한다.
데이터 디스크는 별도 EBS 자원이며 prevent_destroy로 삭제·교체 계획을 막는다.
OS 루트 디스크는 인스턴스 삭제 시 함께 삭제되는 일반 설정이므로 데이터 보관 위치로 사용하지 않는다.

Kafka·MongoDB·MySQL·Spark·Django·Proxy 설치, 파일시스템 포맷/마운트, 서비스 시작, 복제 설정은
[bootstrap 안내](bootstrap/README.md)에 정의한 다음 단계다. 이번 개편에 자동 설치 구현은 포함하지 않는다.
Output 결과를 서버 연결 설정의 입력으로 사용할 수 있지만 완전한 배포 설정 생성기는 아직 없다.

계정·AZ를 바꾼다고 데이터가 자동 이동하지 않는다.
새 대상 준비 → 데이터 이전 → 접속 전환 → 기존 자원 정리 절차가 필요하다.
사양·디스크 증설과 계정·AZ 이동은 별개의 변경으로 검토한다.

## 8. 기존 파일을 어떻게 처리했는가

| 이전 파일 | 대체 위치/처리 |
|---|---|
| scripts/account1/login.ps1 | 필수 배포 경로에서 제외. infra.ps1이 기존 CLI 프로필을 확인 |
| scripts/account1/network.ps1 | infra.ps1 -Stage foundation |
| scripts/account1/security.ps1 | 입력 검사는 공통 실행기, SG 자체는 foundation, 규칙은 workload |
| scripts/account1/prepare-key.sh | infra/scripts/prepare-key.sh로 공통화, 기존 키 재사용 |
| scripts/account1/README.md | infra/README.md에 전체 실행 순서 |
| 상위 config/account1~account5 | infra/config/topology.tfvars.json과 공개키 복사본 |
| 상위 terraform/accounts/account1 소스 | infra/terraform의 공통 모듈·stack |

대체된 소스는 C:\third_project\trash\aws-infra-legacy-20261009에 원래 상대 경로와 SHA-256 목록을 남겨 보관한다.
기존 .terraform-state, .terraform 캐시/초기화 정보, 개인키와 CLI 프로필은 이동하지 않는다.

기존 Account 1 VPC CIDR은 10.11.0.0/16이고 새 기준은 10.10.0.0/16이다.
소스 개편과 기존 AWS 자원 교체는 별개다. 새 상태에 기존 자원을 자동 import하지 않았으며,
원래 로컬 상태를 잃어버린 것처럼 새 자원을 곧바로 적용해서는 안 된다.

## 9. 참고 자료

- [계정별 배치와 비용 요약](../costs/README.md)
- [상세 비용 가정](../costs/dual-az.md)
- [Terraform provider를 모듈에 전달하는 방법](https://developer.hashicorp.com/terraform/language/modules/develop/providers)
- [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3)
- [Terraform for_each](https://developer.hashicorp.com/terraform/language/meta-arguments/for_each)
- [Terraform 테스트 상태 분리](https://developer.hashicorp.com/terraform/language/tests#modules-state)
- [AWS AZ ID](https://docs.aws.amazon.com/ram/latest/userguide/working-with-az-ids.html)
