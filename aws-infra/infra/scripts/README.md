# 실행 명령어와 계정별 배포 구성

이 문서는 `infra.ps1` 명령어를 단어별로 읽는 방법과 각 계정에 배포할 자원, 실행 순서를 설명한다.
2026-10-10의 [실행기](infra.ps1)와 [배치 설정](../config/topology.tfvars.json)을 기준으로 작성했다. 아래 표는 코드의 배포 대상이며, 실제 AWS에 생성됐다는 의미는 아니다.

전체 준비 사항은 [공통 실행 안내](../README.md), 구조와 역할은 [설계 문서](../terraform-restructure-plan.md), Windows 도구 설치는 [설치 안내](../setup-windows/README.md)를 참고한다.

전체 삭제 명령은 [15절](#15-전체-인프라-삭제)에 있다. 삭제 범위·Bastion 분리 등 최신 코드 탐색은 [라우팅 문서](../../docs/infra-routing/ROUTING-README.md)를 기준으로 확인한다.

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

`account2` 자체에 AWS 계정 번호가 들어 있는 것은 아니다. 실행기는 `topology.accounts.account2`의 `id`와 `profile`을 읽고, 서버 목록에서는 `account` 값이 `account2`인 항목을 선택한다.

`Plan`·`Apply`·`Output`에서는 해당 CLI 프로필의 실제 AWS 계정 ID가 설정과 일치하는지 확인한다. 상태 버킷에 접근하는 프로필도 확인하므로, Account 2 작업 중 상태 저장소용 Account 1 인증 확인이 함께 나올 수 있다.

## 2. Account: 어느 계정의 구성을 실행하는가

현재 리전은 `ap-northeast-2`다. 아래 값은 [topology.tfvars.json](../config/topology.tfvars.json)에 있다.

| `-Account` 값 | AWS 계정 ID | CLI 프로필 | VPC CIDR | workload의 서버 대상 |
| --- | --- | --- | --- | --- |
| `account1` | `541308265856` | `account1` | `10.10.0.0/16` | front-a, front-b, game-server, ad-server — 4대 |
| `account2` | `529088287882` | `account2` | `10.20.0.0/16` | mongo-1, spark-2 — 2대 |
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
| account1 | ad-server | Private | C | t3a.large | 없음 |
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
Account 1에는 Public A·C에 걸친 HTTP ALB도 생성하도록 설정돼 있다. 위 상세 표의 Bastion은 workload 대상이 아닌 전용 bastion 단계이며 선택 생성한다. 서비스 EC2는 15대다.

</details>

## 3. Stage: 어떤 자원 묶음을 처리하는가

| `-Stage` 값 | 함께 쓸 `-Account` | 관리 대상 | 처음 실행할 때의 선행 조건 |
| --- | --- | --- | --- |
| `foundation` | `account1`~`account5` 중 하나 | 그 계정의 VPC·서브넷·기본 라우팅·역할별 보안그룹 자체, 설정에 따른 IGW·NAT | 계정 인증과 상태 저장소 준비 |
| `connectivity` | `shared` | 설정된 계정 쌍의 Peering 요청·수락·양방향 라우팅 | 5개 계정의 foundation 적용 완료 |
| `workload` | `account1`~`account5` 중 하나 | 그 계정의 보안그룹 규칙·EC2·EBS·키페어·공인 IP, 해당 시 ALB | 5개 foundation과 공통 connectivity 적용 완료, 해당 계정의 AMI·공개키 등 준비 |

| `bastion` | `account1` | 선택 Bastion EC2·루트 디스크·전용 키페어. EIP 없음 | Account 1 foundation·workload의 SSH/Proxy 규칙, AMI·공개키 준비 |

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
| 같은 파일 | topology.alb.certificate_arn | 공통 타입에 남은 키. 현재 HTTP ALB에 전달하지 않으며 인증서 필수 검사 없음 |
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
.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account2 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account3 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account4 -Stage foundation -Action Plan
.\infra\scripts\infra.ps1 -Account account5 -Stage foundation -Action Plan

.\infra\scripts\infra.ps1 -Account account1 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account account2 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account account3 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account account4 -Stage foundation -Action Apply
.\infra\scripts\infra.ps1 -Account account5 -Stage foundation -Action Apply

.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Plan
.\infra\scripts\infra.ps1 -Account shared -Stage connectivity -Action Apply

.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account3 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account4 -Stage workload -Action Plan
.\infra\scripts\infra.ps1 -Account account5 -Stage workload -Action Plan


.\infra\scripts\infra.ps1 -Account account1 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account2 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account3 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account4 -Stage workload -Action Apply
.\infra\scripts\infra.ps1 -Account account5 -Stage workload -Action Apply


```

## 10. S3 상태 버킷 설정 복원

```powershell
Set-Location C:\third_project\aws-infra

# 기존 설정을 읽고 이전 배포의 S3 상태 버킷 이름을 채웁니다.
$backendPath = 'C:\third_project\aws-infra\infra\config\backend.json'
$backendConfig = Get-Content -Raw -LiteralPath $backendPath | ConvertFrom-Json
$backendConfig.bucket = 'aws-infra-tfstate-541308265856'

# JSON을 UTF-8(BOM 없음) 형식으로 저장합니다.
$backendJson = $backendConfig | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($backendPath, $backendJson, [System.Text.UTF8Encoding]::new($false))

# 저장된 값을 확인합니다.
Get-Content -LiteralPath $backendPath
```

## 11. Account 1 Ubuntu AMI 조회와 설정

```powershell
Set-Location C:\third_project\aws-infra

# 서울 리전의 Ubuntu Server 24.04 x86_64 공식 AMI를 조회합니다.
$ubuntuAmiId = aws ssm get-parameter --profile account1 --region ap-northeast-2 --name "/aws/service/canonical/ubuntu/server/noble/stable/current/amd64/hvm/ebs-gp3/ami-id" --query "Parameter.Value" --output text

# 조회에 실패하면 잘못된 값을 저장하지 않고 중단합니다.
if ($LASTEXITCODE -ne 0 -or $ubuntuAmiId -notmatch '^ami-[0-9a-f]+$') {
    throw 'AMI 조회에 실패했습니다. 위 AWS 오류를 확인하세요.'
}

# 기존 설정을 유지하면서 Account 1의 AMI 값만 채웁니다.
$topologyPath = 'C:\third_project\aws-infra\infra\config\topology.tfvars.json'
$topologyConfig = Get-Content -Raw -LiteralPath $topologyPath | ConvertFrom-Json
$topologyConfig.topology.accounts.account1.ami_id = $ubuntuAmiId.Trim()
$topologyJson = $topologyConfig | ConvertTo-Json -Depth 50
[System.IO.File]::WriteAllText($topologyPath, $topologyJson, [System.Text.UTF8Encoding]::new($false))

# 저장된 AMI ID를 확인합니다.
$topologyConfig.topology.accounts.account1.ami_id
```

## 12. 테스트용 공인 IP 조회와 게임 접속 허용 설정

현재 PC가 연결된 네트워크의 공인 IPv4를 조회하고, 그 IP 하나를 허용하는 `/32` 형식으로 저장한다. `game_client_cidrs` 목록은 현재 IP 하나로 교체하며 다른 설정은 유지한다. 학교·사무실에서 조회하면 해당 네트워크의 공인 IP가 나오고, 집에서 조회하면 집 네트워크의 공인 IP가 나온다.

```powershell
Set-Location C:\third_project\aws-infra

# 현재 네트워크의 공인 IP를 조회하고 접속 허용 범위를 표시합니다.
$testPublicIp = (Invoke-RestMethod -Uri 'https://checkip.amazonaws.com').Trim()
"$testPublicIp/32"

# 기존 설정을 읽고 게임 접속 허용 IP만 변경합니다.
$trafficPath = 'C:\third_project\aws-infra\infra\config\traffic.tfvars.json'
$trafficConfig = Get-Content -Raw -LiteralPath $trafficPath | ConvertFrom-Json
$trafficConfig.traffic.game_client_cidrs = @("$testPublicIp/32")

# 기존 설정 전체를 UTF-8(BOM 없음) JSON으로 저장합니다.
$trafficJson = $trafficConfig | ConvertTo-Json -Depth 50
[System.IO.File]::WriteAllText(
    $trafficPath,
    $trafficJson,
    [System.Text.UTF8Encoding]::new($false)
)

# 파일에 실제로 저장된 접속 허용 IP를 확인합니다.
$savedTrafficConfig = Get-Content -Raw -LiteralPath $trafficPath | ConvertFrom-Json
$savedTrafficConfig.traffic.game_client_cidrs
```

이번 PC의 조회 결과는 `211.117.107.63/32`였다. 다른 네트워크에서는 조회값이 달라질 수 있다.

위 명령은 로컬 설정 파일을 저장한다. 실제 AWS 반영은 Account 1 workload의 새 Plan을 검토한 뒤 Apply할 때 이루어진다. 나중에 학교의 공인 IP 대역을 확보하면 `game_client_cidrs`의 테스트 IP를 해당 대역으로 교체하고 같은 절차로 적용한다. 설정을 바꾼 뒤에는 이전 저장 Plan을 사용할 수 없다.

현재 ALB는 HTTP 80 listener만 사용한다. certificate_arn은 공통 타입에 남아 있지만 인증서가 없다는 이유로 workload Plan·Apply를 중단하지 않는다. /static/*는 Front:80, /ads/*는 광고:8000, 기본 경로는 game:8000으로 보낸다. HTTPS/WSS 공개는 현재 구현과 별도로 설계해야 한다.

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

서버 이름과 디스크 키는 Terraform 식별자다. 계정 이동·노드 제거·디스크 축소는 기존 데이터를 자동으로 이전하지 않는다. 실행기는 데이터 EBS의 prevent_destroy를 변경하지 않으며 현재 값은 false다. 삭제·교체 계획과 데이터 보관을 확인한다. 한 역할을 완전히 제거하면 traffic의 역할 연결과 ALB 조건도 함께 수정해야 한다. 현재 5개 계정·서울 두 AZ·account1 배스천 구조는 유지한다.

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

## 13. 배스천 상태 조회와 중지·시작

[bastion.ps1](bastion.ps1)은 기존 배스천 한 대를 대상으로 AWS CLI를 실행한다. PowerShell 5.1 이상과 AWS CLI v2, 대상 계정의 유효한 CLI 프로필이 필요하다. Terraform·S3 상태·AMI·ALB 인증서는 실행 조건이 아니다. 실제 배스천은 현재 v2 Terraform 구성으로 이미 생성되어 있어야 한다.

```powershell
Set-Location C:\third_project\aws-infra

# 현재 전원 상태·IP·EC2 검사 결과를 확인합니다.
.\infra\scripts\bastion.ps1 -Action Status

# 중지를 요청하고 stopped 상태까지 기다립니다.
.\infra\scripts\bastion.ps1 -Action Stop

# 시작을 요청하고 running 및 EC2 시스템·인스턴스 검사 정상까지 기다립니다.
.\infra\scripts\bastion.ps1 -Action Start

# 시작·중지 권한을 먼저 검사하고, 중지 완료 후 같은 서버를 다시 시작합니다.
.\infra\scripts\bastion.ps1 -Action Restart
```

위 네 명령은 개별 사용 예시다. Status는 조회하고, Stop·Start·Restart는 별도 확인 질문 없이 실제 전원을 제어한다. 처음 실행할 때는 Status로 대상을 확인한다.

계정·프로필·리전은 [topology 설정](../config/topology.tfvars.json)의 bastion 노드에서 찾는다. 실제 AWS 계정 ID를 검사하고 Project·Account·Layout=v2·ManagedBy=Terraform·Node=bastion·Role=bastion 태그에 맞는 활성 대상이 정확히 한 대일 때만 진행한다. 여기서 활성 대상은 pending/running/stopping/stopped를 포함한다. 대상이 없거나 중복되면 중단하며 인스턴스 ID를 추측하지 않는다. 작업 중에는 처음 선택한 ID를 유지한다.

| Action | 완료 기준 |
| --- | --- |
| Status | 현재 전원 상태·IP·EC2 상태 검사 결과 출력 |
| Stop | stopped. 이미 stopped면 중지 요청 생략 |
| Start | running이고 SystemStatus·InstanceStatus 모두 ok. 이미 running이어도 검사 완료 대기 |
| Restart | Stop 완료 후 Start 완료. 시작·중지 권한 검사 또는 Stop이 실패하면 다음 단계로 진행하지 않음 |

pending/stopping 상태는 전환 완료를 기다린 뒤 요청한 목표 상태로 진행한다. Start 또는 Stop 한 단계의 대기 상한은 기본 600초이며 `-TimeoutSeconds 900`처럼 1~3600초로 바꿀 수 있다. Restart는 Stop·Start에 각각 적용한다. 마지막 AWS 조회에 소요되는 시간이 추가될 수 있다. 실패하면 마지막 상태·실패 원인을 출력하고 종료하며 강제 종료나 자동 롤백을 하지 않는다. 실패 후 현재 상태는 Status로 확인한다.

반환 객체에는 Action, Account, Region, InstanceId, State, SystemStatus, InstanceStatus, PublicIp, PrivateIp, SshPort, SshTcp가 있다. running이면 [traffic 설정](../config/traffic.tfvars.json)의 SSH 포트에 최대 3초 동안 TCP 접속을 시도한다.

| SshTcp | 의미 |
| --- | --- |
| PortOpen | TCP 포트 도달 성공. SSH 키 인증 성공을 의미하지 않음 |
| Unreachable | 제한 시간 안에 TCP 연결 실패. 관리자 CIDR·네트워크·SSH 서비스 확인 필요 |
| NoPublicIp | 조회 결과에 공인 IP가 없음 |
| NotChecked | running 상태가 아니어서 검사 생략 |

SSH 도달 실패는 전원 제어 결과와 별도로 경고하고 EC2를 유지한다. SG 규칙이나 관리자 IP는 자동 수정하지 않는다. 내부 서버 경유 접속, SSH 키 인증, Forward Proxy 복구는 별도 확인 대상이다.

배스천 중지는 SSH 세션·터널과 해당 서버를 사용하는 Forward Proxy 연결을 끊는다. 서비스가 프록시로 외부 API를 호출하는 시간에는 이 영향을 고려해 실행한다. 다른 PC의 전원 작업이나 Terraform 변경과 동시에 실행하지 않는다. 인스턴스 삭제·디스크 삭제·Elastic IP 해제·자동 예약은 수행하지 않는다.

필요한 EC2 권한은 DescribeInstances·DescribeInstanceStatus와 사용할 동작의 StartInstances·StopInstances다. Restart에는 두 변경 권한이 모두 필요하다. 함수와 예외 처리의 위치는 [배스천 라우팅 문서](../../docs/infra-routing/scripts/bastion.ps1.md)에 정리했다.

## 14. 계정별 새 SSH 키 준비와 기존 서버 등록

개인키는 `C:\Users\Playdata\.ssh\project-key`에 보관한다. Account 1은 `project-bastion.pem`, 나머지는 `account2.pem`~`account5.pem`이다. 기존 서버는 새 개인키를 PC에 저장하는 것만으로 접속 키가 바뀌지 않는다.

```powershell
Set-Location C:\third_project\aws-infra

# 로컬 개인키 권한·공개키·계정별 경로를 준비한다. AWS 변경은 하지 않는다.
.\infra\scripts\account-keys.ps1 -Action Prepare

# Bastion 전용 상태의 삭제 계획만 검토한 뒤 Delete를 실행한다.
.\infra\scripts\bastion.ps1 -Action PlanDelete
.\infra\scripts\bastion.ps1 -Action Delete

# 새 Account 1 키로 Bastion을 재생성한다. PlanCreate를 검토한 뒤 Create를 실행한다.
.\infra\scripts\bastion.ps1 -Action PlanCreate
.\infra\scripts\bastion.ps1 -Action Create
.\infra\scripts\bastion.ps1 -Action Output

# 새 Bastion을 통해 기존 서비스 서버 15대에 계정별 공개키를 등록한다.
.\infra\scripts\account-keys.ps1 -Action Register
```

`Prepare`는 기존 공개키를 `infra/.local/ssh-keys/previous-public/`에 보관하고, `infra/config/keys/account1.pub`~`account5.pub` 및 `topology.accounts.<계정>.ssh_public_key_path`를 갱신한다. 개인키는 저장소 안으로 복사하지 않는다. 설정 변경 전의 저장 Plan은 다시 만들어야 한다.

`Register`는 실제 계정·서버 태그·역할·개수·기동 상태를 확인한다. Bastion에 다섯 공개키를 추가하고, EC2 Instance Connect로 기존 서비스 서버에 임시 접속하여 `ubuntu`의 `authorized_keys`에 계정별 공개키를 추가한다. 기존 공개키는 보존한다. EC2·디스크·ALB의 생성이나 삭제, Terraform Apply는 수행하지 않는다. 필요한 권한은 STS GetCallerIdentity, EC2 DescribeInstances, EC2 Instance Connect SendSSHPublicKey이며 Ubuntu의 EIC 설치 및 SSH 경로가 필요하다.

등록 중 실패하면 원인을 해결하고 같은 명령을 다시 실행한다. 특정 계정만 재시도할 때는 `-Account account2`처럼 지정한다. Bastion을 다음에 재생성한 뒤에는 `Register -Account account1`을 실행하여 추가 팀원 공개키를 다시 등록한다.

접속 설정은 `infra/.local/ssh-keys/ssh-config`에 생성된다. 예를 들어 등록 후 Account 2의 Mongo 서버에 접속하는 명령은 다음과 같다.

```powershell
ssh -F .\infra\.local\ssh-keys\ssh-config infra-key-account2-mongo-1
```

EC2 Instance Connect 임시 키가 만료된 뒤에도 접속되는지 별도로 확인한다. 팀원에게는 자기 계정의 PEM과 필요한 접속 설정을 전달하고, 팀원 PC의 `IdentityFile` 경로와 관리자 공인 IP 허용 규칙을 맞춘다.

새 공개키를 서버에 등록한 뒤, AWS 키페어 등록 정보도 맞추기 위해 각 계정 workload의 새 `Plan`을 검토한다. 키페어 교체가 예상되지만 서비스 EC2·디스크·ALB 교체가 포함되면 Apply하지 않는다. 검토한 계정만 기존 `infra.ps1 -Action Apply`로 적용한다. 자세한 함수·경계는 [키 전환 라우팅 문서](../../docs/infra-routing/scripts/account-keys.ps1.md)를 참고한다.

## 15. 전체 인프라 삭제

이 프로젝트의 Terraform 상태가 관리하는 Bastion·5개 계정 workload·Peering·foundation을 삭제한다. 데이터 EBS도 삭제 대상이다. S3 상태 버킷·상태 이력, 상태에 없는 수동 자원과 다른 프로젝트는 자동 삭제하지 않는다.

workload가 생성한 역할별 service_console_ssh 규칙도 전체 삭제 대상이다. 삭제 검사기는 정확한 자원 주소와 문자열 역할 키 형식을 허용하며 단계·태그·계정·삭제 전용 검사를 유지한다. 관련 함수를 수정한 뒤에는 이전 실패 실행 ID를 재사용하지 않고 새 Plan을 만든다. [삭제 검사 문서](../../docs/infra-routing/scripts/lib/infra-destroy.ps1.md)를 참고한다.

현재 [compute/main.tf](../terraform/modules/compute/main.tf)의 데이터 EBS `prevent_destroy`는 `false`다. 별도로 `true`로 변경한 환경에서는 보호가 켜진 삭제 Plan이 실패하므로, 삭제 의도를 확인한 후 사용자가 직접 설정을 변경해야 한다. 스크립트는 원본·override·코드 사본을 수정하지 않는다. 보호 설정을 바꾼 경우에는 기존 계획을 적용하지 말고 새 Plan을 만든다. 이후 보호를 켤지 여부는 운영·삭제 정책에 맞춰 결정한다.

아래 명령은 한 단계씩 실행한다. Plan은 자원을 삭제하지 않고, Apply가 실제 삭제를 수행한다.

```powershell
Set-Location C:\third_project\aws-infra

# 최대 12개 상태의 삭제 계획을 준비한다. 데이터 EBS 삭제 선택이 필수다.
.\infra\scripts\destroy-all.ps1 -Action Plan -DeleteDataVolumes
```

Plan에서 출력한 실행 ID를 아래 변수에 넣는다. `infra/.local/destroy-all/{실행ID}/`의 계정·단계별 `delete-summary.json`과 Plan 출력을 검토한다. `delete_count`에는 EC2 OS 디스크 검증 항목도 포함되므로 Terraform의 destroy 개수와 다를 수 있다. 전체 실행 상태가 Ready여야 Apply할 수 있다.

```powershell
# Plan 결과의 32자리 실행 ID로 바꾼다.
$destroyRunId = '여기에_Plan에서_출력된_실행_ID'

# 준비·진행 상태를 조회한다. 이 명령은 로컬 기록을 읽는다.
.\infra\scripts\destroy-all.ps1 -Action Status -RunId $destroyRunId

# 모든 삭제 대상과 데이터 삭제를 검토한 뒤에만 실행한다.
.\infra\scripts\destroy-all.ps1 -Action Apply -RunId $destroyRunId -DeleteDataVolumes
```

삭제 순서는 **Bastion → account1~5 workload → shared connectivity → account1~5 foundation**으로 고정된다. 첫 삭제 전에 모든 계획·코드·설정·공개키·원격 상태 변경을 검사한다. 계획 중 하나라도 실패했거나 바뀌면 적용을 거부한다. 진행 중 한 단계가 실패하면 이후 단계는 실행하지 않는다.

실패·Ctrl+C 후에는 Status에서 위치를 확인하고 원인을 해결한 뒤 **새 Plan → 검토 → 새 ID로 Apply**를 수행한다. 이미 비어 있는 상태와 미생성 Bastion은 건너뛴다. 상태 파일이나 S3 버킷을 먼저 삭제하지 않는다. 다른 터미널·팀원 PC의 배포·콘솔 변경은 전체 삭제 중 함께 실행하지 않는다.

모든 삭제 단계 후에는 상태가 비었는지와 주요 AWS 자원 ID가 제거됐는지 확인한다. AWS의 삭제 반영 지연·조회 권한·잔존 자원 때문에 VerificationFailed가 표시되면 `verification.json`과 오류를 확인한다. 삭제 단계가 모두 끝난 경우에만 다음 읽기 전용 재검증을 사용할 수 있다.

```powershell
# 저장된 대상 목록으로 결과만 다시 조회한다. 삭제 Plan을 재적용하지 않는다.
.\infra\scripts\destroy-all.ps1 -Action Verify -RunId $destroyRunId
```

전체 삭제는 `destroy-all.ps1`로 실행한다. 내부용 `infra.ps1 -PlanMode Delete -DestroyRunId ...`는 실행 상태와 선행 단계 완료를 확인하므로 개별 단계의 우회 삭제 명령으로 사용하지 않는다. 구조·검사 범위는 [전체 삭제 라우팅 문서](../../docs/infra-routing/scripts/destroy-all.ps1.md)에 있다.
