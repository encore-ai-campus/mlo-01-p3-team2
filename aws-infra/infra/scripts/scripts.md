# 실행 명령어와 계정별 배포 구성

운영 대조: 2026-10-18. 아래 기본 topology 표는 18대이며, 실제 current는 game-server-test를 추가한 19대다. [현재 운영 구성](../../docs/operations/current-state.md)에 도메인·계정 배치·예약을 정리했다. 새 프로필은 current를 자동 복제하지 않는다.

실제 생성·설치 순서는 [배포 절차](../../docs/deployment-runbook.md)를 따른다. S3·AMI·접속 IP 복원, 배스천 운영, SSH 키 전환과 전체 삭제는 [복원·운영 절차](../../docs/operations-recovery.md)로 옮겼다. 장애가 발생하면 배포 절차의 장애 표에서 해당 절차로 이동한다.

현재 환경의 서버를 잠시 껐다 켤 때는 [전체 EC2 중지·시작](../../docs/operations/ec2-power.md)의 `power-all.ps1 -Action Stop` 또는 `-Action Start`를 사용한다.


이 문서는 **infra.ps1** 명령어를 단어별로 읽는 방법과 각 계정에 배포할 자원, 실행 순서를 설명한다.
2026-10-13의 [실행기](infra.ps1)와 [배치 설정](../config/topology.tfvars.json)을 기준으로 작성했다. 아래 표는 코드의 배포 대상이며, 실제 AWS에 생성됐다는 의미는 아니다.

전체 준비 사항은 [공통 실행 안내](../infra.md), 구조와 역할은 [설계 문서](../terraform-restructure-plan.md), Windows 도구 설치는 [설치 안내](../setup-windows/setup-windows.md)를 참고한다.

전체 삭제 명령은 [복원·운영 문서의 전체 삭제 절](../../docs/operations-recovery.md#6-전체-인프라-삭제)에 있다. 삭제 범위·Bastion 분리 등 최신 코드 탐색은 [라우팅 문서](../../docs/infra-routing/ROUTING-README.md)를 기준으로 확인한다.

## 실행기 공통 처리

환경 변수 보관·복원, AWS CLI 출력 수집, Terraform 저장 계획 읽기는 [공통 라이브러리](lib/infra-common.ps1)에 모았다. 각 실행기는 대상·명령 인수·오류 판정과 실행 순서를 담당한다. 명령어 사용법과 Plan/Apply 재검사 시점은 같다. 함수별 연결은 [공통 함수 지도](../../docs/infra-routing/scripts/lib/infra-common.ps1.md)를 따른다.

실행 코드 변경 후에는 기존 저장 계획의 fingerprint가 달라지므로 Plan을 새로 생성해야 한다. 이는 기존 저장 계획 보호 규칙이다.

## 1. 명령어를 단어별로 읽기

이 문서의 상대 경로 명령은 `C:\third_project\aws-infra`에서 실행한다.

```powershell
Set-Location C:\third_project\aws-infra
```

다음 명령은 **Account 2의 서버·보안규칙 등 workload 변경 계획을 만든다.**

```powershell
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Plan
```

| 부분 | 뜻 | 이 예시에서 하는 일 |
| --- | --- | --- |
| `.\` | 현재 PowerShell 작업 폴더 | `C:\third_project\aws-infra` 기준 |
| `infra\scripts\infra.ps1` | 실행할 파일 | 모든 계정이 함께 사용하는 공통 실행기 |
| `-Account` | 대상 계정을 선택하는 옵션 | 바로 뒤의 계정 키를 읽음 |
| `account2` | 배치 설정에 있는 계정 키 | Account 2의 AWS 계정 ID·CLI 프로필을 선택 |
| `-Stage` | 작업 묶음을 선택하는 옵션 | 바로 뒤의 단계 이름을 읽음 |
| `workload` | 서버와 서비스 연결을 관리하는 단계 | Mongo-1·Spark-2, 해당 디스크·키페어·보안규칙 |
| `-Action` | 수행할 동작을 선택하는 옵션 | 바로 뒤의 동작 이름을 읽음 |
| `Plan` | 변경 계획 생성 | AWS 계정과 상태를 확인하고 계획 파일 저장. 자원 변경 적용은 하지 않음 |

`account2` 자체에 AWS 계정 번호가 들어 있는 것은 아니다. 실행기는 **topology.accounts.account2**의 `id`와 `profile`을 읽고, 서버 목록에서는 `account` 값이 `account2`인 항목을 선택한다.

`Plan`·`Apply`·`Output`에서는 해당 CLI 프로필의 실제 AWS 계정 ID가 설정과 일치하는지 확인한다. 상태 버킷에 접근하는 프로필도 확인하므로, Account 2 작업 중 상태 저장소용 Account 1 인증 확인이 함께 나올 수 있다.

## 2. Account: 어느 계정의 구성을 실행하는가

현재 리전은 `ap-northeast-2`다. 아래 값은 [topology.tfvars.json](../config/topology.tfvars.json)에 있다.

| `-Account` 값 | AWS 계정 ID | CLI 프로필 | VPC CIDR | workload의 서버 대상 |
| --- | --- | --- | --- | --- |
| `account1` | `541308265856` | `account1` | `10.10.0.0/16` | front-a, front-b, game-server, ad-server, flatten-1 — 5대 |
| `account2` | `529088287882` | `account2` | `10.20.0.0/16` | mongo-1, spark-2 — 2대 |
| `account3` | `667879771148` | `account3` | `10.30.0.0/16` | mysql-1, spark-1, mongo-2 — 3대 |
| `account4` | `688567306400` | `account4` | `10.40.0.0/16` | kafka-1, kafka-2, mysql-3, spark-3 — 4대 |
| `account5` | `217016296352` | `account5` | `10.50.0.0/16` | mysql-2, mongo-3, kafka-3 — 3대 |
| `shared` | 단일 계정 없음 | 위 5개 프로필 | 5개 VPC 사이 연결 | 서버 생성 없이 Peering·상대 VPC 라우팅 관리 |

**`shared`는 여섯 번째 AWS 계정이나 별도 CLI 프로필이 아니다.** `connectivity` 단계에서 5개 계정의 프로필을 사용해 연결 양쪽을 관리하는 실행 구분이다.

`-Account`를 생략하면 코드의 기본값은 `account1`이다. 이 문서의 명령은 대상을 분명히 하도록 항상 명시한다. 다른 CLI 프로필을 사용하려면 설정의 `accounts.<계정>.profile`을 바꾼다. 실행기에 별도의 `-Profile` 옵션은 없다.

<details>
<summary>계정별 서버·AZ·사양·데이터 디스크 18대 상세(Bastion 포함)</summary>

| 계정 | 서버 키 | 영역 | 논리 AZ | 사양 | 별도 데이터 gp3 |
| --- | --- | --- | --- | --- | --- |
| account1 | bastion | Public | A | t3a.small | 없음 |
| account1 | front-a | Public | A | t3.small | 없음 |
| account1 | front-b | Public | A | t3.small | 없음 |
| account1 | game-server | Private | A | t3.large | 없음 |
| account2 | mongo-1 | Private | A | t3a.small | 900GiB |
| account2 | spark-2 | Private | A | t3a.large | 100GiB |
| account1 | flatten-1 | Private | A | t3a.medium | 없음 |
| account1 | ad-server | Private | A | t3.large | 없음 |
| account4 | kafka-1 | Private | A | t3a.large | 200GiB |
| account3 | mysql-1 | Private | A | t3a.small | 100GiB |
| account3 | spark-1 | Private | A | t3a.large | 100GiB |
| account3 | mongo-2 | Private | A | t3a.small | 900GiB |
| account4 | kafka-2 | Private | A | t3a.large | 200GiB |
| account4 | mysql-3 | Private | A | t3a.small | 100GiB |
| account4 | spark-3 | Private | A | t3a.large | 100GiB |
| account5 | mysql-2 | Private | A | t3a.small | 100GiB |
| account5 | mongo-3 | Private | A | t3a.small | 900GiB |
| account5 | kafka-3 | Private | A | t3a.large | 200GiB |

모든 서버의 OS 디스크는 별도 20GiB다. 데이터 용량은 현재 설정값이며 성능을 보장하는 권장값이라는 의미는 아니다.
논리 A는 `apne2-az1`, C는 `apne2-az3`에 대응한다. 계정 콘솔의 AZ 이름 끝 글자가 아니라 설정한 물리 AZ ID 기준이다.
기본 및 current 설정의 ALB는 비활성화돼 있으며 전용 연결 3개도 제거했다. 위 상세 표의 Bastion은 workload 대상이 아닌 전용 bastion 단계이며 선택 생성한다. 서비스 EC2는 17대다. flatten-1은 Kafka 평탄화 Consumer 전용이며 role=consumer다. 생성 후 인벤토리의 consumer 그룹으로 등록되고, 평탄화 프로그램 설치는 별도로 수행한다.

</details>

## 3. Stage: 어떤 자원 묶음을 처리하는가

| `-Stage` 값 | 함께 쓸 `-Account` | 관리 대상 | 처음 실행할 때의 선행 조건 |
| --- | --- | --- | --- |
| `foundation` | `account1`~`account5` 중 하나 | 그 계정의 VPC·서브넷·기본 라우팅·역할별 보안그룹 자체, 설정에 따른 IGW·NAT | 계정 인증과 상태 저장소 준비 |
| `connectivity` | `shared` | 설정된 계정 쌍의 Peering 요청·수락·양방향 라우팅 | 5개 계정의 foundation 적용 완료 |
| `workload` | `account1`~`account5` 중 하나 | 그 계정의 보안그룹 규칙·EC2·EBS·키페어·공인 IP, 해당 시 ALB | 5개 foundation과 공통 connectivity 적용 완료, 해당 계정의 AMI·공개키 등 준비 |

| `bastion` | `account1` | 선택 Bastion EC2·루트 디스크·전용 키페어·EIP·EIP 연결 | Account 1 foundation·workload의 SSH/Proxy 규칙, AMI·공개키 준비 |

현재 설정에서는 Account 1만 Public 서브넷·IGW를 만들고, 모든 계정의 인터넷 송신 방식은 Proxy이므로 NAT는 생성하지 않는다. connectivity는 현재 설정된 10개 계정 쌍을 연결한다.

foundation의 보안그룹 생성과 workload의 보안규칙 적용은 다른 작업이다. EC2와 ALB도 workload에서 생성한다. 따라서 `foundation -Action Apply`만으로 서버나 서비스 포트가 모두 준비되지는 않는다.

현재 workload는 보안규칙·서버·ALB를 한 상태에서 관리한다. `-Stage security`, `-Stage compute`, `-Stage alb`처럼 기능별로 선택하는 옵션은 구현돼 있지 않다.

| 조합 예시 | 결과 |
| --- | --- |
| `-Account account2 -Stage foundation` | Account 2의 네트워크·보안그룹 단계 |
| `-Account account2 -Stage workload` | Account 2의 서버·보안규칙 단계 |
| `-Account shared -Stage connectivity` | 5개 계정 사이의 연결 단계 |
| `-Account account2 -Stage connectivity` | 잘못된 조합으로 중단 |
| `-Account shared -Stage workload` | 잘못된 조합으로 중단 |

## 4. Action: 확인하는가, 적용하는가

| `-Action` 값 | 수행하는 일 | AWS 자원에 변경 적용 |
| --- | --- | --- |
| `Validate` | backend 없이 초기화하고 Terraform 문법·구성을 검증 | 없음 |
| `Test` | 선택한 stage에 작성된 모의 테스트 실행 | 없음 |
| `Plan` | 실제 계정 확인, S3 상태 조회·잠금, 변경 계획 계산·저장 | 없음 |
| `Apply` | 같은 계정·stage에 저장한 계획을 검증한 뒤 실제 적용 | 있음 |
| `Output` | 저장된 Terraform 상태의 출력을 로컬 JSON으로 저장 | 자원 변경 없음 |

`Validate`와 `Test`는 실제 AWS 계정에 배포하지 않는다. 초기화 과정에서 provider 다운로드는 필요할 수 있다.
`Test`의 계정별 사례는 테스트 파일에 정의돼 있으므로 `-Account account2`를 지정했다고 Account 2 사례만 골라 실행하는 것은 아니다.
`Output`은 저장된 상태를 읽는 동작이며, 서버의 실시간 상태나 서비스 연결 성공을 점검하는 명령은 아니다.

**`Apply`는 저장 계획을 바로 적용하며 별도 확인창을 띄우지 않는다.** 먼저 `Plan` 결과의 생성·변경·삭제 항목을 검토하고 실행한다. 설정·코드·공개키가 바뀌거나 저장 계획이 없으면 다시 `Plan`이 필요하다. 적용 성공 후에는 사용한 계획 파일을 지운다.

`-Stage`와 `-Action`은 필수 옵션이다. infra.ps1의 지원 동작은 표의 5개이며 `-Action Destroy`나 전체 계정을 실행하는 `-Account all`은 없다. 전체 삭제 실행 방법은 [복원·운영 절차](../../docs/operations-recovery.md#6-전체-인프라-삭제)에서 확인한다.
선택 옵션 `-PluginDirectory`는 기존 provider 파일의 위치를 지정할 때 사용한다. AWS 계정이나 서버 배치를 선택하는 옵션은 아니다.

## 5. 실제 배포 전에 채울 값

현재 저장된 설정에는 빈 값이 있어 그대로 `Plan`을 실행하면 준비 단계에서 중단된다.

| 파일 | 설정 | 사용하는 단계 |
| --- | --- | --- |
| [backend.json](../config/backend.json) | `bucket`, `region`, `profile`, `key_prefix` | 모든 stage의 Plan·Apply·Output. 기존 S3 버킷과 버전 관리가 필요하며 자동 생성하지 않음 |
| [topology.tfvars.json](../config/topology.tfvars.json) | `topology.accounts.<계정>.id`와 `.profile` | 대상 계정 확인. 현재 account1~account5 설정값과 로컬 프로필이 일치해야 함 |
| 같은 파일 | `topology.accounts.<계정>.ami_id` | 해당 계정 workload Plan·Apply |
| 같은 파일 | `topology.accounts.<계정>.ssh_public_key_path` | 해당 계정 workload Plan·Apply. `.pem` 개인키가 아닌 OpenSSH `.pub` 공개키 |
| 같은 파일 | topology.alb.certificate_arn | 공통 타입에 남은 키. 현재 HTTP ALB에 전달하지 않으며 인증서 필수 검사 없음 |
| [traffic.tfvars.json](../config/traffic.tfvars.json) | **traffic.admin_public_cidrs** | Bastion SSH의 관리자 공인 IP. Account 2~5 Private SG에도 SSH CIDR 규칙 사용. Account 1 네 서비스의 SSH는 Bastion만 허용 |
| 같은 파일 | **traffic.game_client_cidrs** | 이전 edge 및 public_http_cidrs가 없는 프로필의 HTTP 허용 범위. 현재 두 Front의 80·443 전체 공개 정책에는 사용하지 않음 |

공개키 상대 경로는 `infra/`를 기준으로 해석한다. 예를 들어 `config/keys/account1.pub`는 `infra/config/keys/account1.pub`를 뜻한다.
AWS 자격 증명은 로컬 CLI 프로필에 등록한 것을 사용하며 이 설정 파일에 액세스 키·시크릿 키를 넣지 않는다.

## 6. 처음 구축하는 순서와 실제 명령

아래 각 대상에서 **Plan → 내용 검토 → 같은 대상의 Apply**를 수행한다. Account 1만 끝낸 뒤 다음 단계로 넘어가는 것이 아니라, 한 단계의 필요한 계정을 모두 완료한다.

| 순서 | Account | Stage | 완료할 내용 |
| --- | --- | --- | --- |
| 1 | account1, account2, account3, account4, account5 각각 | foundation | 5개 계정의 네트워크·보안그룹 |
| 2 | shared | connectivity | 5개 계정 사이의 연결 |
| 3 | account1, account2, account3, account4, account5 각각 | workload | 전체 17대 서비스 서버·보안규칙, 활성 프로필에서만 ALB |

### 6-1. 정적 검증

```powershell
# 실제 배포 전에 세 단계의 Terraform 구성을 확인한다.
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Validate
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Validate
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Validate
```

### 6-2. 각 계정의 foundation

Account 1의 변경 계획을 만든다.

```powershell
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Plan
```

그 계획을 확인한 뒤 적용한다.

```powershell
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Apply
```

위 두 명령의 `account1`을 `account2`, `account3`, `account4`, `account5`로 바꿔 각각 계획·검토·적용한다. 이 단계에서는 EC2를 만들지 않는다.

### 6-3. 공통 connectivity

5개 계정의 foundation을 모두 적용한 뒤 연결 계획을 만든다.

```powershell
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Plan
```

계획을 확인한 뒤 연결을 적용한다.

```powershell
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Apply
```

이 단계는 account1~account5로 반복하지 않고 `shared`로 한 번 관리한다.

### 6-4. 각 계정의 workload

아래는 Account 2 예시다. 대상 서버는 mongo-1·spark-2이며, 해당 계정의 보안규칙·키페어·설정된 데이터 디스크도 함께 계획한다.

```powershell
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Plan
```

계획을 확인한 뒤 적용한다.

```powershell
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Apply
```

`-Account`를 바꿔 5개 계정 모두 같은 절차를 수행한다. 현재 기본 및 current 설정에서는 Account 1 ALB를 생성하지 않는다. 서버별 AZ·사양·디스크 용량은 명령어가 아닌 배치 설정에서 읽는다.

workload는 다른 계정의 foundation 상태도 읽지만, 서버는 선택한 계정에 속한 항목만 생성한다. 다른 계정과의 통신 규칙을 바꾼 경우에는 규칙 양쪽에 해당하는 계정의 workload 계획·적용이 필요하다.

### 6-5. 계정별 결과 조회

```powershell
# Account 2의 저장된 서버 주소·역할 출력을 JSON으로 받는다.
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Output
```

결과는 `infra/.local/account2/workload/outputs.json`에 저장한다. 다른 계정도 `-Account`를 바꿔 조회한다.

EC2 생성 뒤의 Kafka·MongoDB·MySQL·Spark·Django·Proxy 설치와 실행은 [bootstrap 범위](../bootstrap/bootstrap.md)에 해당한다. 이 실행기가 해당 프로그램 설치와 파이프라인 연결까지 완료해 주지는 않는다.

## 7. 실행 결과는 어디에 저장하는가

| 파일·경로 | 의미 |
| --- | --- |
| `infra/.local/<Account>/<Stage>/saved.tfplan` | Plan으로 저장한 변경 계획 |
| 같은 폴더의 `saved-plan.json` | 계정·단계·상태 경로·설정 및 코드 해시. Apply 전 일치 여부 확인 |
| 같은 폴더의 **outputs.json** | Output으로 조회한 상태 출력 |
| S3의 `<key_prefix>/<Account>/<Stage>/terraform.tfstate` | 계정·단계별 Terraform 상태 |

예를 들어 현재 기본 prefix에서 Account 2 workload 상태는 S3의 `aws-infra-v2/account2/workload/terraform.tfstate`다. shared 연결 상태는 `aws-infra-v2/shared/connectivity/terraform.tfstate`다. 새 실행기는 기존 로컬 상태를 자동으로 가져오지 않는다.

## 8. 자주 헷갈리는 항목

| 하고 싶은 일 | 사용할 방법 |
| --- | --- |
| 다른 계정의 서버를 배포 | `-Account` 변경. 선택한 계정의 프로필·AMI·공개키를 먼저 준비 |
| 서버의 사양·디스크 용량 변경 | topology의 해당 서버 설정 변경 후 그 계정 workload Plan·검토·Apply |
| 특정 서버 한 대만 명령어로 선택 | 현재 `-Node` 같은 옵션 없음. 해당 계정 workload의 변경 계획을 검토 |
| 보안그룹 규칙 변경 | traffic 수정 후 관련 계정 workload Plan·검토·Apply |
| 네트워크만 구성 | 해당 계정 foundation Plan·검토·Apply |
| 명령 한 번으로 5개 계정을 모두 구축 | 현재 자동 순회 기능 없음. 6절의 순서대로 대상별 실행 |
| SSH 키가 이미 있음 | 기존 공개키 경로를 설정. `prepare-key.sh`로 다시 만들 필요 없음 |


## 비용별 구성 선택과 일괄 배포

[deploy.ps1](deploy.ps1)은 EC2 사양·대수·계정 배치를 구성 폴더로 선택하고 프록시 준비까지 연결한다. 기존 Terraform 실행기와 상태를 재사용한다. 전체 동작과 제약은 [배포 라우팅 문서](../../docs/infra-routing/scripts/deploy.ps1.md)를 참고한다.

Windows PowerShell에서 먼저 현재 설정의 복사본을 만든다. 아래 budget은 사용자가 편집할 구성 이름이며, 자동으로 저렴한 사양을 선정한다는 뜻은 아니다.

~~~powershell
# 이 단계는 로컬 파일만 만들며 AWS를 변경하지 않는다.
$deployScript = 'C:\third_project\aws-infra\infra\scripts\deploy.ps1'
$deploymentProfile = 'C:\third_project\aws-infra\infra\config\profiles\budget'
& $deployScript -Action NewProfile -ProfileDirectory $deploymentProfile
~~~

생성한 구성 폴더에서 다음 값을 편집한다.

| 바꾸려는 항목 | 수정할 곳 |
| --- | --- |
| 서버 크기 | topology.tfvars.json의 topology.nodes.노드명.instance_type |
| 서버 대수 | topology.nodes의 노드 항목 추가·제거 |
| account1 등 다른 계정에 서비스 배치 | 각 노드의 account |
| 디스크·AZ·서브넷 | 노드의 data_disks·root_gib·az·subnet_tier |
| 통신·프록시 포트 | traffic.tfvars.json |
| 개인키 경로·역할 이름 연결·WSL 환경 | platform.json의 ssh_keys·role_groups·wsl_distribution·ansible_venv |

서버 이름과 디스크 키는 Terraform 식별자다. 계정 이동·노드 제거·디스크 축소는 기존 데이터를 자동으로 이전하지 않는다. 실행기는 데이터 EBS의 prevent_destroy를 변경하지 않으며 현재 값은 true다. 데이터 삭제·교체가 포함된 계획은 실패할 수 있으며 데이터 보관·이전은 별도로 준비한다. 한 역할을 완전히 제거하면 traffic의 역할 연결과 ALB 조건도 함께 수정해야 한다. 현재 5개 계정·A/C 서브넷·account1 배스천 구조는 유지한다. 모든 서버는 A에 둔다.

기존 환경에서 사양만 조정할 때는 해당 workload Plan을 먼저 확인한다.

~~~powershell
# Plan은 변경 계획만 만들고, 다음 Apply가 그 저장 계획을 실제 적용한다.
& $deployScript -Action Plan -Stage workload -Account account1 -ProfileDirectory $deploymentProfile
& $deployScript -Action Apply -Stage workload -Account account1 -ProfileDirectory $deploymentProfile
~~~

처음부터 전체를 준비하거나 모든 계정에 변경을 적용할 때는 아래 명령을 사용한다. foundation → connectivity → workload → bastion 순서로 각 단계의 Plan을 출력하며, 해당 단계에서 APPLY를 입력해야 적용한다. 실패하거나 중단하면 앞 단계의 성공한 변경은 남는다. 기존 SG를 제거하는 계정 간 이전은 기존 EC2·SG 참조와 데이터 정리 순서를 먼저 검토해야 한다.

~~~powershell
# AWS에 실제 적용한다. 단계별 Plan 검토 후 APPLY를 입력한다.
& $deployScript -Action Deploy -ProfileDirectory $deploymentProfile
~~~

생성 후에는 현재 EC2 주소를 읽어 aws-platform/platform/inventory/hosts.budget.yml을 만들고 WSL의 프록시 스크립트를 실행한다. 이미 서버가 준비된 경우에는 아래 두 단계만 실행할 수 있다.

~~~powershell
# 현재 주소와 계정별 키 경로를 인벤토리로 갱신한다.
& $deployScript -Action Inventory -ProfileDirectory $deploymentProfile

# account1 또는 다른 계정·역할 그룹을 지정할 수 있다. 기본 Limit은 all이다.
& $deployScript -Action Proxy -ProfileDirectory $deploymentProfile -Limit account1
~~~

Proxy는 선택한 클라이언트 외에 공용 배스천의 Squid·APT·방화벽도 준비한다. 역할별 Kafka·Spark·DB 설치는 별도다. SSH 키는 WSL에 미리 두며 Ansible 가상환경의 기본 경로는 ~/.venvs/platform이다. 다른 경로를 사용하면 platform.json에서 바꾼다.

**구성들은 동일한 원격 Terraform 상태를 사용한다.** 선택한 구성으로 현재 환경을 변경하며, 별도의 인프라 복사본을 만들지 않는다. 로컬 Plan만 구성 경로별로 분리하고 선택 파일의 변경을 검사한다. 한 환경에 서로 다른 구성의 배포를 동시에 실행하지 않는다.

실제 구성 폴더와 생성된 인벤토리는 Git에서 제외한다. 인프라 코드 변경으로 기존 저장 Plan의 fingerprint가 달라지므로 이 변경을 받은 뒤에는 Plan을 새로 만든다. Windows 체크아웃에서도 scripts/setup-proxy.sh와 scripts/install-squid.sh는 저장소 .gitattributes에 따라 LF를 유지한다.

구성을 선택한 뒤 후속 Plan·Apply에도 같은 ProfileDirectory를 지정한다. 기존 infra.ps1을 구성 옵션 없이 실행하면 원래 infra/config를 읽으므로 선택한 구성과 다른 변경 계획이 나올 수 있다.

mysql-3 추가 후 current 프로필의 실제 적용 결과와 ALB 복원 보류는 [AWS 검증 기록](../../docs/infra-routing/verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)을 따른다. 당시에는 alb.enabled=true를 유지했으나 2026-10-11 기본 및 current 설정을 false로 바꾸고 전용 연결을 제거했다. 기존 자원 정리는 [배포 순서](../../docs/deployment-runbook.md#alb-비활성화-적용-순서)를 따른다. 이번 적용은 MySQL 관련 범위만 검토해 수행했으며, Cluster 설치 전 Inventory·Proxy·새 데이터 디스크 마운트·OS 방화벽 준비가 필요하다.

현재 Account 1은 Public A의 front-a(game_frontend)·front-b(ad_frontend), Private A의 game-server·ad-server를 생성한다. Front는 각각 t3.small·EIP, Backend는 각각 t3.large다. edge-1은 생성하지 않으며 현재 구성에 -EdgeBootstrapOnly를 사용하지 않는다. Inventory로 두 Front의 자기 공인 IP와 대응 Backend 사설 IP:8000을 갱신한 뒤 [Front별 HTTPS 설치](../../docs/deployment-runbook.md#front별-https-설치)를 따른다. Proxy는 다운로드 준비이며 Nginx·Certbot 설치는 별도 Ansible 단계다.
