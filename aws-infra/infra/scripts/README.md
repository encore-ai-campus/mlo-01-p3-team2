# 실행 명령어와 계정별 배포 구성

이 문서는 `infra.ps1` 명령어를 단어별로 읽는 방법과 각 계정에 배포할 자원, 실행 순서를 설명한다.
2026-10-09의 [실행기](infra.ps1)와 [배치 설정](../config/topology.tfvars.json)을 기준으로 작성했다. 아래 표는 코드의 배포 대상이며, 실제 AWS에 생성됐다는 의미는 아니다.

전체 준비 사항은 [공통 실행 안내](../README.md), 구조와 역할은 [설계 문서](../terraform-restructure-plan.md), Windows 도구 설치는 [설치 안내](../setup-windows/README.md)를 참고한다.

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
| `workload` | 서버와 서비스 연결을 관리하는 단계 | Mongo-1·Spark-2·Ad-server, 해당 디스크·키페어·보안규칙 |
| `-Action` | 수행할 동작을 선택하는 옵션 | 바로 뒤의 동작 이름을 읽음 |
| `Plan` | 변경 계획 생성 | AWS 계정과 상태를 확인하고 계획 파일 저장. 자원 변경 적용은 하지 않음 |

`account2` 자체에 AWS 계정 번호가 들어 있는 것은 아니다. 실행기는 `topology.accounts.account2`의 `id`와 `profile`을 읽고, 서버 목록에서는 `account` 값이 `account2`인 항목을 선택한다.

`Plan`·`Apply`·`Output`에서는 해당 CLI 프로필의 실제 AWS 계정 ID가 설정과 일치하는지 확인한다. 상태 버킷에 접근하는 프로필도 확인하므로, Account 2 작업 중 상태 저장소용 Account 1 인증 확인이 함께 나올 수 있다.

## 2. Account: 어느 계정의 구성을 실행하는가

현재 리전은 `ap-northeast-2`다. 아래 값은 [topology.tfvars.json](../config/topology.tfvars.json)에 있다.

| `-Account` 값 | AWS 계정 ID | CLI 프로필 | VPC CIDR | workload의 서버 대상 |
| --- | --- | --- | --- | --- |
| `account1` | `541308265856` | `account1` | `10.10.0.0/16` | bastion, front-a, front-b, game-server — 4대 |
| `account2` | `529088287882` | `account2` | `10.20.0.0/16` | mongo-1, spark-2, ad-server — 3대 |
| `account3` | `667879771148` | `account3` | `10.30.0.0/16` | kafka-1, mysql-1, spark-1, mongo-2 — 4대 |
| `account4` | `688567306400` | `account4` | `10.40.0.0/16` | kafka-2, spark-3 — 2대 |
| `account5` | `217016296352` | `account5` | `10.50.0.0/16` | mysql-2, mongo-3, kafka-3 — 3대 |
| `shared` | 단일 계정 없음 | 위 5개 프로필 | 5개 VPC 사이 연결 | 서버 생성 없이 Peering·상대 VPC 라우팅 관리 |

**`shared`는 여섯 번째 AWS 계정이나 별도 CLI 프로필이 아니다.** `connectivity` 단계에서 5개 계정의 프로필을 사용해 연결 양쪽을 관리하는 실행 구분이다.

`-Account`를 생략하면 코드의 기본값은 `account1`이다. 이 문서의 명령은 대상을 분명히 하도록 항상 명시한다. 다른 CLI 프로필을 사용하려면 설정의 `accounts.<계정>.profile`을 바꾼다. 실행기에 별도의 `-Profile` 옵션은 없다.

<details>
<summary>계정별 서버·AZ·사양·데이터 디스크 16대 상세</summary>

| 계정 | 서버 키 | 영역 | 논리 AZ | 사양 | 별도 데이터 gp3 |
| --- | --- | --- | --- | --- | --- |
| account1 | bastion | Public | A | t3a.small | 없음 |
| account1 | front-a | Public | A | t3a.small | 없음 |
| account1 | front-b | Public | C | t3a.small | 없음 |
| account1 | game-server | Private | A | t3a.large | 없음 |
| account2 | mongo-1 | Private | A | t3a.small | 900GiB |
| account2 | spark-2 | Private | A | t3a.large | 100GiB |
| account2 | ad-server | Private | C | t3a.large | 없음 |
| account3 | kafka-1 | Private | A | t3a.large | 200GiB |
| account3 | mysql-1 | Private | A | t3a.small | 100GiB |
| account3 | spark-1 | Private | A | t3a.large | 100GiB |
| account3 | mongo-2 | Private | C | t3a.small | 900GiB |
| account4 | kafka-2 | Private | A | t3a.large | 200GiB |
| account4 | spark-3 | Private | C | t3a.large | 100GiB |
| account5 | mysql-2 | Private | C | t3a.small | 100GiB |
| account5 | mongo-3 | Private | A | t3a.small | 900GiB |
| account5 | kafka-3 | Private | C | t3a.large | 200GiB |

모든 서버의 OS 디스크는 별도 20GiB다. 데이터 용량은 현재 설정값이며 성능을 보장하는 권장값이라는 의미는 아니다.
논리 A는 `apne2-az1`, C는 `apne2-az3`에 대응한다. 계정 콘솔의 AZ 이름 끝 글자가 아니라 설정한 물리 AZ ID 기준이다.
Account 1에는 Public A·C에 걸친 ALB도 생성하도록 설정돼 있다.

</details>

## 3. Stage: 어떤 자원 묶음을 처리하는가

| `-Stage` 값 | 함께 쓸 `-Account` | 관리 대상 | 처음 실행할 때의 선행 조건 |
| --- | --- | --- | --- |
| `foundation` | `account1`~`account5` 중 하나 | 그 계정의 VPC·서브넷·기본 라우팅·역할별 보안그룹 자체, 설정에 따른 IGW·NAT | 계정 인증과 상태 저장소 준비 |
| `connectivity` | `shared` | 설정된 계정 쌍의 Peering 요청·수락·양방향 라우팅 | 5개 계정의 foundation 적용 완료 |
| `workload` | `account1`~`account5` 중 하나 | 그 계정의 보안그룹 규칙·EC2·EBS·키페어·공인 IP, 해당 시 ALB | 5개 foundation과 공통 connectivity 적용 완료, 해당 계정의 AMI·공개키 등 준비 |

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

`-Stage`와 `-Action`은 필수 옵션이다. 지원 동작은 표의 5개이며 `-Action Destroy`나 전체 계정을 실행하는 `-Account all`은 없다.
선택 옵션 `-PluginDirectory`는 기존 provider 파일의 위치를 지정할 때 사용한다. AWS 계정이나 서버 배치를 선택하는 옵션은 아니다.

## 5. 실제 배포 전에 채울 값

현재 저장된 설정에는 빈 값이 있어 그대로 `Plan`을 실행하면 준비 단계에서 중단된다.

| 파일 | 설정 | 사용하는 단계 |
| --- | --- | --- |
| [backend.json](../config/backend.json) | `bucket`, `region`, `profile`, `key_prefix` | 모든 stage의 Plan·Apply·Output. 기존 S3 버킷과 버전 관리가 필요하며 자동 생성하지 않음 |
| [topology.tfvars.json](../config/topology.tfvars.json) | `topology.accounts.<계정>.id`와 `.profile` | 대상 계정 확인. 현재 account1~account5 설정값과 로컬 프로필이 일치해야 함 |
| 같은 파일 | `topology.accounts.<계정>.ami_id` | 해당 계정 workload Plan·Apply |
| 같은 파일 | `topology.accounts.<계정>.ssh_public_key_path` | 해당 계정 workload Plan·Apply. `.pem` 개인키가 아닌 OpenSSH `.pub` 공개키 |
| 같은 파일 | `topology.alb.certificate_arn` | ALB를 생성하는 Account 1 workload Plan·Apply |
| [traffic.tfvars.json](../config/traffic.tfvars.json) | `traffic.admin_public_cidrs` | Bastion SSH에 허용할 팀원 공인 IP 범위. 빈 배열이면 외부 SSH 허용 규칙 없음 |
| 같은 파일 | `traffic.game_client_cidrs` | ALB에 접속할 사용자 IP 범위. 빈 배열이면 외부 접속 허용 규칙 없음 |

공개키 상대 경로는 `infra/`를 기준으로 해석한다. 예를 들어 `config/keys/account1.pub`는 `infra/config/keys/account1.pub`를 뜻한다.
AWS 자격 증명은 로컬 CLI 프로필에 등록한 것을 사용하며 이 설정 파일에 액세스 키·시크릿 키를 넣지 않는다.

## 6. 처음 구축하는 순서와 실제 명령

아래 각 대상에서 **Plan → 내용 검토 → 같은 대상의 Apply**를 수행한다. Account 1만 끝낸 뒤 다음 단계로 넘어가는 것이 아니라, 한 단계의 필요한 계정을 모두 완료한다.

| 순서 | Account | Stage | 완료할 내용 |
| --- | --- | --- | --- |
| 1 | account1, account2, account3, account4, account5 각각 | foundation | 5개 계정의 네트워크·보안그룹 |
| 2 | shared | connectivity | 5개 계정 사이의 연결 |
| 3 | account1, account2, account3, account4, account5 각각 | workload | 전체 16대 서버·보안규칙, Account 1 ALB |

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

아래는 Account 2 예시다. 대상 서버는 mongo-1·spark-2·ad-server이며, 해당 계정의 보안규칙·키페어·설정된 데이터 디스크도 함께 계획한다.

```powershell
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Plan
```

계획을 확인한 뒤 적용한다.

```powershell
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Apply
```

`-Account`를 바꿔 5개 계정 모두 같은 절차를 수행한다. 현재 설정에서 Account 1 workload에는 ALB도 포함된다. 서버별 AZ·사양·디스크 용량은 명령어가 아닌 배치 설정에서 읽는다.

workload는 다른 계정의 foundation 상태도 읽지만, 서버는 선택한 계정에 속한 항목만 생성한다. 다른 계정과의 통신 규칙을 바꾼 경우에는 규칙 양쪽에 해당하는 계정의 workload 계획·적용이 필요하다.

### 6-5. 계정별 결과 조회

```powershell
# Account 2의 저장된 서버 주소·역할 출력을 JSON으로 받는다.
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Output
```

결과는 `infra/.local/account2/workload/outputs.json`에 저장한다. 다른 계정도 `-Account`를 바꿔 조회한다.

EC2 생성 뒤의 Kafka·MongoDB·MySQL·Spark·Django·Proxy 설치와 실행은 [bootstrap 범위](../bootstrap/README.md)에 해당한다. 이 실행기가 해당 프로그램 설치와 파이프라인 연결까지 완료해 주지는 않는다.

## 7. 실행 결과는 어디에 저장하는가

| 파일·경로 | 의미 |
| --- | --- |
| `infra/.local/<Account>/<Stage>/saved.tfplan` | Plan으로 저장한 변경 계획 |
| 같은 폴더의 `saved-plan.json` | 계정·단계·상태 경로·설정 및 코드 해시. Apply 전 일치 여부 확인 |
| 같은 폴더의 `outputs.json` | Output으로 조회한 상태 출력 |
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

## 9. 한 줄씩 실행하는 전체 명령어

```powershell
Set-Location C:\third_project\aws-infra
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Validate
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Validate
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Validate
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account account2 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account2 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account account3 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account3 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account account4 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account4 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account account5 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account5 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Plan
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Apply
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account3 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account3 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account4 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account4 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account5 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account5 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Output
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Output
.\infra\scripts\infra.ps1 -Account account3 -Stage workload -Action Output
.\infra\scripts\infra.ps1 -Account account4 -Stage workload -Action Output
.\infra\scripts\infra.ps1 -Account account5 -Stage workload -Action Output
```

