# Terraform VPC·EC2 생성부터 Ansible 설치까지

기준: 2026-10-10의 저장소 코드. Windows PC의 `C:\third_project\aws-infra`와 `C:\third_project\aws-platform\platform`을 함께 사용한다. 서버 OS는 현재 프록시 준비 코드가 지원하는 **Ubuntu 24.04 x86_64**를 기준으로 한다.

[복원·운영 절차](operations-recovery.md)는 이 문서와 같은 폴더에 있다. 실행 중 오류가 발생하면 [13절 장애 표](#13-자주-만난-출력과-다음-조치)에서 해당 증상의 절차로 이동하고, 원인 해결 후 중단된 배포 단계로 돌아온다.

이 문서는 운영자가 실행할 명령과 완료 조건을 정리한 것이다. 문서 작성 과정에서 AWS 배포나 원격 Ansible 작업을 실행하지 않았다. **각 단계가 성공한 것을 확인한 뒤 다음 명령을 실행한다.**

## 지금 진행하던 작업에서 이어가기

이미 `current` 구성을 만들고 다음 메시지까지 확인했다면 VPC·EC2 생성과 인벤토리 생성은 반복하지 않는다.

```text
Ansible 인벤토리 갱신: C:\third_project\aws-platform\platform\inventory\hosts.current.yml
```

**기존 Windows PowerShell 창**에서 다음을 실행한다. 프롬프트가 `PS C:\third_project\aws-infra>`인 창이다.

```powershell
Set-Location 'C:\third_project\aws-infra'
$deployScript = 'C:\third_project\aws-infra\infra\scripts\deploy.ps1'
$deploymentProfile = 'C:\third_project\aws-infra\infra\config\profiles\current'

# 전체 인벤토리 서버의 프록시·APT 다운로드 환경을 준비한다.
& $deployScript -Action Proxy -ProfileDirectory $deploymentProfile -Limit all
```

WSL 가상환경과 SSH 키가 준비되어 있어야 한다. 아직 준비하지 않았다면 **7단계**부터 진행한다. 암호화된 **vault.yml**이 이미 있다면 **9.1단계**에서 비밀번호 파일을 준비하고, **8단계의 WSL 실행 방법**을 사용한다.

마지막에 `프록시 준비 완료`가 나오면 **9단계의 서비스 설치 전 확인**으로 넘어간다. 이 명령은 Kafka·Spark·MySQL·MongoDB를 설치하지 않는다.

## 1. 명령어별로 어떤 작업이 실행되는가

### 1.1 PowerShell 작업 위치와 구성 지정

먼저 **Windows PowerShell**에 아래 세 줄을 입력한다. 파일을 수정하거나 AWS 자원을 생성하는 명령은 아니다.

```powershell
Set-Location 'C:\third_project\aws-infra'
$deployScript = 'C:\third_project\aws-infra\infra\scripts\deploy.ps1'
$deploymentProfile = 'C:\third_project\aws-infra\infra\config\profiles\current'
```

| 명령 | 실행 후 상태 |
| --- | --- |
| `Set-Location ...` | 현재 작업 폴더를 aws-infra로 바꾼다. 이후 상대 경로의 기준이 된다. |
| `$deployScript = ...` | 배포 실행기 경로를 현재 PowerShell 창의 변수에 저장한다. 아직 실행하지 않는다. |
| `$deploymentProfile = ...` | 사용할 구성 폴더 경로를 변수에 저장한다. 폴더를 생성하는 명령은 아니다. |

이후 명령의 `& $deployScript`는 변수에 저장한 스크립트를 실행한다는 뜻이다. `-Action`은 수행할 작업, `-Stage`는 Terraform 단계, `-ProfileDirectory`는 읽을 구성 폴더를 지정한다. PowerShell 창을 새로 열면 위 변수를 다시 설정한다.

### 1.2 구성 생성과 전체 EC2 배포

**current 구성이 없을 때만** 아래 명령을 실행한다. 기본 topology·traffic을 복사하고 platform.json을 만들어 로컬 구성 파일 세 개를 준비한다. AWS 자원은 생성하지 않는다. 기존 파일이 있으면 덮어쓰지 않고 중단한다. 구성 변경 위치는 4절에서 확인한다.

```powershell
# 처음 사용할 구성 폴더를 만든다. 이미 있다면 이 명령은 생략한다.
& $deployScript -Action NewProfile -ProfileDirectory $deploymentProfile
```

입력·AWS 인증·SSH 키와 **7절의 WSL 준비**가 끝났으면 전체 생성 명령을 실행한다.

```powershell
# 단계별 계획을 검토하고 APPLY를 입력하면 해당 단계의 자원을 생성·변경한다.
& $deployScript -Action Deploy -ProfileDirectory $deploymentProfile
```

| Deploy 안에서 실행되는 순서 | 하는 작업 | 적용 또는 완료 조건 |
| --- | --- | --- |
| foundation Plan → Apply | 다섯 계정의 VPC·서브넷·기본 보안그룹 등 | 계획을 확인하고 대문자 `APPLY` 입력 |
| connectivity Plan → Apply | 계정 간 VPC Peering·라우팅 | 계획을 확인하고 `APPLY` 입력 |
| workload Plan → Apply | 선택한 topology에 등록된 서비스 EC2·데이터 EBS·통신 규칙·선택적 ALB | 계획을 확인하고 `APPLY` 입력 |
| bastion Plan → Apply | 배스천 EC2 | 계획을 확인하고 `APPLY` 입력 |
| Inventory | 실제 EC2 주소를 조회해 hosts.current.yml 생성 | `Ansible 인벤토리 갱신` 메시지 확인 |
| Proxy | 배스천 Squid·방화벽과 서버들의 APT·HTTPS 다운로드 환경 준비 | `프록시 준비 완료` 메시지 확인 |

`APPLY` 이외의 값을 입력하거나 단계가 실패하면 이후 작업을 중단한다. 앞 단계에서 생성한 자원은 남는다. **Deploy는 MySQL·MongoDB·Kafka·ZooKeeper·Spark 설치를 실행하지 않는다.** 구성에 정의된 자원을 현재 Terraform 상태에 반영하므로, 기존 환경에서는 계획에 생성뿐 아니라 변경·삭제도 포함될 수 있다. Vault가 이미 있다면 프록시 비밀번호 전달 조건까지 포함한 12.4절의 안내를 따른다.

### 1.3 단계별로 실행하거나 이미 만든 EC2에서 이어가기

아래는 전체 Deploy 대신 필요한 동작을 따로 실행할 때 쓰는 명령이다. 각 명령에는 위에서 지정한 동일한 구성 폴더를 전달한다.

| 명령 | 하는 작업 | 다음 조치 |
| --- | --- | --- |
| `& $deployScript -Action Plan -Stage workload -ProfileDirectory $deploymentProfile` | 서비스 EC2·EBS 등의 변경 계획을 저장한다. 실제 적용은 하지 않는다. | 계획 검토 후 같은 단계의 Apply |
| `& $deployScript -Action Apply -Stage workload -ProfileDirectory $deploymentProfile` | 저장한 workload 계획을 실제 AWS에 적용한다. 추가 확인 질문은 없다. | 성공 후 Inventory |
| `& $deployScript -Action Inventory -ProfileDirectory $deploymentProfile` | 기존 EC2의 현재 IP와 구성을 확인하고 Ansible 인벤토리를 갱신한다. EC2를 만들지 않는다. | WSL 접속 검사·Proxy |
| `& $deployScript -Action Proxy -ProfileDirectory $deploymentProfile -Limit all` | 이미 생성한 인벤토리로 전체 서버의 프록시·APT 환경을 준비한다. | 9절의 서비스 설치 전 준비 |

처음 구축할 때는 Plan·Apply를 **foundation → connectivity → workload → bastion** 순서로 실행한다. 위 workload 두 줄만 실행해서 새 VPC와 Peering까지 생성되지는 않는다. 단계별 전체 명령은 5절에 있다. `-Account`를 생략하면 전체 계정을 처리하며, connectivity는 shared, bastion은 배스천 계정으로 처리한다.

### 1.4 EC2 연결 확인과 서비스 설치 명령

아래 명령은 **내 PC의 WSL**에서 실행한다. 먼저 7.3절의 가상환경·ANSIBLE_CONFIG·inventory 변수와 필요한 Vault·디스크·통신 설정을 준비한다.

| 명령 | 하는 작업 |
| --- | --- |
| `ansible-inventory -i "$inventory" --graph` | 대상 서버와 역할 그룹 목록을 확인한다. 서버를 변경하지 않는다. |
| `ansible -i "$inventory" all -m ansible.builtin.ping` | SSH와 원격 Python 연결을 검사한다. 서비스 설치 여부를 검사하는 명령은 아니다. |
| `ansible-playbook -i "$inventory" site.yml --syntax-check` | 플레이북 문법을 확인한다. 서버에 설치 작업을 적용하지 않는다. |
| `ansible-playbook -i "$inventory" site.yml --tags common --limit all` | 공통 패키지·SSH·시간 동기화 설정을 적용한다. DB·Kafka 설치 역할은 실행하지 않는다. |
| `ansible-playbook -i "$inventory" site.yml --tags mysql --limit mysql` | mysql 그룹 전체 3~9대의 Cluster 설치·계정·상태 검증을 실행한다. 기본 설정은 세 대이며, mysql-3가 포함된 최신 인벤토리와 디스크·Proxy·방화벽 준비를 먼저 확인한다. |
| `ansible-playbook -i "$inventory" site.yml --tags mongodb --limit mongodb` | MongoDB 설치·계정·지원 구성의 Replica Set 설정과 검증을 실행한다. |
| `ansible-playbook -i "$inventory" site.yml --tags kafka --limit kafka` | Java·Kafka 설치와 KRaft 구성·검증을 실행한다. |
| `ansible-playbook -i "$inventory" site.yml --tags zookeeper,spark --limit spark` | Spark 서버에 ZooKeeper와 Spark를 순서대로 설치하고 검증한다. |

설치 전 확인과 방화벽 적용은 9~10절, 역할별 설치 조건과 완료 범위는 11절을 따른다. 이 표의 명령을 준비 절차 없이 모두 연달아 실행하지 않는다.

## 2. 어느 터미널에서 실행하는가

| 구분 | 프롬프트 예시 | 실행할 작업 |
|---|---|---|
| Windows PowerShell | `PS C:\third_project\aws-infra>` | Terraform 실행, 구성 선택, 인벤토리 생성, **deploy.ps1** 실행 |
| 내 PC의 WSL Ubuntu | `(platform) playdatawsl@DESKTOP-...:/mnt/c/third_project/aws-platform/platform$` | Ansible 설치·실행, Vault 준비 |
| SSH로 들어간 EC2 | `ubuntu@ip-10-...:~$` | 이 문서의 배포 명령을 입력하는 곳이 아님 |

`C:\...`는 Windows 경로이고 `/mnt/c/...`는 같은 파일을 WSL에서 보는 경로다. 코드 블록 안의 명령만 복사한다. 프롬프트의 `PS ...>`나 `$`는 복사하지 않는다.

실행 순서는 다음과 같다.

```text
도구·AWS 인증·키 확인
→ 구성 선택
→ foundation: VPC·서브넷·기본 보안그룹
→ connectivity: 계정 간 VPC Peering·라우팅
→ workload: 서비스 EC2·EBS·보안그룹 규칙·선택적 ALB
→ bastion: 배스천 EC2
→ Inventory: 실제 주소로 Ansible 인벤토리 생성
→ Proxy: Squid·APT·다운로드 준비
→ Vault·디스크·서비스 통신 조건 확인
→ 공통 설정·방화벽
→ MySQL·MongoDB·Kafka·ZooKeeper·Spark 설치 및 역할 내 검증
```

## 3. 최초 준비

### 3.1 Windows 도구와 AWS 인증

**Windows PowerShell**에서 실행한다.

```powershell
Set-Location 'C:\third_project\aws-infra'
$deployScript = 'C:\third_project\aws-infra\infra\scripts\deploy.ps1'
$deploymentProfile = 'C:\third_project\aws-infra\infra\config\profiles\current'

terraform version
aws --version
ssh -V
wsl --list --verbose
```

현재 실행기는 PowerShell 5.1 이상, Terraform `>= 1.11, < 2.0`, AWS CLI와 WSL을 사용한다. 도구가 없다면 [Windows 설치 안내](../infra/setup-windows/setup-windows.md)를 먼저 따른다. WSL 배포판 이름은 이후 **platform.json**의 `wsl_distribution`과 같아야 한다.

기본 AWS 프로필 이름을 사용하는 경우 다음 조회가 모두 성공해야 한다. 이름을 바꿨다면 선택한 topology의 `accounts.*.profile` 값으로 바꾼다.

```powershell
# 반환된 Account가 해당 계정의 topology.accounts.*.id와 같은지 확인한다.
aws sts get-caller-identity --profile account1
aws sts get-caller-identity --profile account2
aws sts get-caller-identity --profile account3
aws sts get-caller-identity --profile account4
aws sts get-caller-identity --profile account5
```

다음 입력도 준비되어 있어야 한다. **deploy.ps1**이 AWS 인증이나 상태 버킷을 자동으로 만들지는 않는다.

| 입력 | 확인할 내용 |
|---|---|
| `infra/config/backend.json` | 기존 S3 상태 버킷, 리전, 접근 프로필, `key_prefix`. 버킷 버전 관리 및 상태·잠금 파일 접근 권한 |
| 선택한 **topology.tfvars.json** | 계정 ID·프로필, 리전, Ubuntu 24.04 x86_64 AMI, VPC CIDR, 역할·사양·디스크, 공개키 경로 |
| 선택한 **traffic.tfvars.json** | 관리자 공인 IP의 `/32` CIDR, 서비스 공개 범위, 역할 간 포트 |
| 계정별 개인키 | 아래 파일이 실제 EC2에 등록할 공개키와 쌍을 이루는지 확인 |

입력값이 빠졌거나 기존 값을 다시 맞춰야 하면 [S3 상태 버킷 설정 복원](operations-recovery.md#1-s3-상태-버킷-설정-복원), [Ubuntu AMI 조회·설정](operations-recovery.md#2-account-1-ubuntu-ami-조회와-설정), [공인 IP·게임 접속 범위](operations-recovery.md#3-테스트용-공인-ip-조회와-게임-접속-허용-설정) 중 필요한 절차만 선택한다.

### 3.2 계정별 SSH 키

현재 기본 키 배치는 다음과 같다. `.pem` 파일은 이미 보관한 것을 사용한다.

| 계정 | Windows 개인키 파일 | WSL에서 사용할 경로 |
|---|---|---|
| account1 | `C:\Users\Playdata\.ssh\project-key\project-bastion.pem` | `~/.ssh/project-key/project-bastion.pem` |
| account2 | `C:\Users\Playdata\.ssh\project-key\account2.pem` | `~/.ssh/project-key/account2.pem` |
| account3 | `C:\Users\Playdata\.ssh\project-key\account3.pem` | `~/.ssh/project-key/account3.pem` |
| account4 | `C:\Users\Playdata\.ssh\project-key\account4.pem` | `~/.ssh/project-key/account4.pem` |
| account5 | `C:\Users\Playdata\.ssh\project-key\account5.pem` | `~/.ssh/project-key/account5.pem` |

**처음 새로 구축하며 공개키 준비를 아직 하지 않은 경우에만**, `NewProfile` 전에 Windows PowerShell에서 실행한다.

```powershell
# 기존 개인키에서 공개키를 추출하고 기본 topology의 공개키 경로를 맞춘다.
.\infra\scripts\account-keys.ps1 -Action Prepare
```

이 명령은 로컬 키 권한과 `infra/config/keys/account1.pub`~**account5.pub**, 기본 topology를 갱신한다. 기존 EC2의 로그인 키를 바꾸는 명령은 아니다. 이미 생성한 `current` 프로필도 자동 갱신하지 않는다. 현재처럼 새 EC2 접속까지 확인했다면 이 단계는 건너뛴다.

생성되는 Ansible 인벤토리는 **배스천 접속 키와 목적지 계정 키를 분리해서 사용**한다. 개인키를 배스천에 복사하는 단계는 필요하지 않다.

기존 서버의 SSH 인증이 실패하면 [SSH 장애 확인](operations-recovery.md#72-ssh-인증-또는-접속-시간-초과)을 먼저 수행한다. 기존 EC2의 등록 공개키를 계획적으로 바꾸는 절차는 [SSH 키 전환](operations-recovery.md#5-계정별-새-ssh-키-준비와-기존-서버-등록)에 있다.

## 4. 구성 프로필 선택

**Windows PowerShell**에서 실행한다. `current` 프로필이 없을 때만 생성한다.

```powershell
& $deployScript -Action NewProfile -ProfileDirectory $deploymentProfile
```

이미 `infra/config/profiles/current/`에 아래 세 파일이 있으면 생성 명령을 생략한다. `NewProfile`은 기존 파일을 덮어쓰지 않는다.

| 파일 | 바꾸는 내용 |
|---|---|
| **topology.tfvars.json** | `nodes`의 계정 배치, `instance_type`, 노드 항목, 디스크 용량 등 |
| **traffic.tfvars.json** | 관리자 IP, 허용 포트, 역할 간 연결 |
| **platform.json** | 인벤토리 이름, WSL 배포판·가상환경 경로, 계정별 키 경로, 역할 그룹 연결 |

`current` 기본값은 인벤토리 **hosts.current.yml**, WSL 배포판 `Ubuntu`, 가상환경 `~/.venvs/platform`이다. 실제 환경과 다르면 이 파일에서 수정한다.

구성 변경 시 다음 경계를 지킨다.

- `NewProfile`은 기본 `infra/config`를 복사한다. 비용을 자동 계산하거나 저렴한 사양으로 자동 변경하지 않는다.
- 현재 실행기는 `account1`~`account5`와 **account1의 bastion 한 대**를 전제로 한다. 서비스 노드는 계정 간에 배치할 수 있다.
- 서로 다른 프로필도 **같은 원격 Terraform 상태를 사용**한다. `budget` 같은 이름을 만들어도 독립된 인프라 복사본이 생기는 것이 아니다.
- 노드 삭제·계정 이동은 기존 EC2·데이터에 영향을 준다. 현 코드의 데이터 EBS는 prevent_destroy=true이며 삭제·교체가 포함된 계획은 보호 설정 때문에 실패할 수 있다. 데이터 이전·백업은 자동화되어 있지 않다.
- Terraform에서 대수를 바꿀 수 있는 것과 플랫폼 역할이 지원하는 대수는 별개다. 현재 플랫폼 MySQL은 전체 mysql 그룹 3~9대의 InnoDB Cluster를 요구한다. 기본 인프라는 MySQL 세 대로 갱신됐으며 이전 프로필과 인벤토리에 mysql-3가 빠져 있는지 확인한다. 새 서버의 데이터 마운트·Proxy·방화벽을 준비한 뒤 설치한다. MongoDB 1 또는 3대, Kafka 3대, Spark 3대는 기존 안내를 따른다. 노드 이름 끝 숫자는 서비스 ID에 쓰이므로 임의로 변경하지 않는다.

이후 모든 명령에서 **같은 `$deploymentProfile`**을 사용한다. **infra.ps1**을 구성 옵션 없이 직접 호출하면 기본 `infra/config`를 읽으므로 선택한 프로필과 다른 계획이 나올 수 있다.

## 5. Terraform으로 네트워크와 EC2 생성

전부 **Windows PowerShell**에서 실행한다. `Plan`과 `Apply`는 각각 따로 실행한다. `Plan` 결과의 생성·변경·삭제 목록을 검토한 후에만 다음 `Apply`를 실행한다. **개별 `Apply`는 추가 확인 질문 없이 저장된 계획을 적용한다.**

Plan·Apply가 실패하면 뒤 단계로 진행하지 않는다. [Terraform 계획 오류와 재개](operations-recovery.md#77-terraform-계획-오류와-배포-재개)에서 인증·상태·저장 계획·데이터 보호 조건을 확인하고 실패한 단계의 새 Plan부터 이어간다.

### 5.1 VPC·서브넷·기본 보안그룹: foundation

```powershell
& $deployScript -Action Plan -Stage foundation -ProfileDirectory $deploymentProfile
```

계획을 검토한 뒤 적용한다. `-Account`를 생략했으므로 다섯 계정을 순서대로 처리한다.

```powershell
& $deployScript -Action Apply -Stage foundation -ProfileDirectory $deploymentProfile
```

### 5.2 계정 간 Peering과 라우팅: connectivity

다섯 계정의 foundation이 모두 성공한 뒤 실행한다.

```powershell
& $deployScript -Action Plan -Stage connectivity -ProfileDirectory $deploymentProfile
```

```powershell
& $deployScript -Action Apply -Stage connectivity -ProfileDirectory $deploymentProfile
```

이 단계는 공동 단계이므로 `-Account account4` 같은 개별 계정 옵션을 붙이지 않는다.

### 5.3 서비스 EC2·EBS·통신 규칙·ALB: workload

2026-10-10 current 프로필의 MySQL 증설은 적용했다. 이후 2026-10-11 기본 및 current 설정에서 ALB를 비활성화하고 전용 연결 3개를 제거했다. 다른 기존 프로필은 자동 변경되지 않으며, 기존 자원 정리에는 아래 일반 생성 순서 대신 [ALB 비활성화 적용 순서](#alb-비활성화-적용-순서)를 따른다. 실제 AWS 상태는 이번에 조회하지 않았다.

```powershell
& $deployScript -Action Plan -Stage workload -ProfileDirectory $deploymentProfile
```

```powershell
& $deployScript -Action Apply -Stage workload -ProfileDirectory $deploymentProfile
```

### 5.4 배스천 EC2: bastion

```powershell
& $deployScript -Action Plan -Stage bastion -ProfileDirectory $deploymentProfile
```

```powershell
& $deployScript -Action Apply -Stage bastion -ProfileDirectory $deploymentProfile
```

각 단계의 모든 대상에 `Apply complete!`가 나오고 오류가 없어야 다음으로 넘어간다. 실패하면 성공한 앞 단계는 남는다. 원인을 고친 뒤 해당 단계의 **새 Plan → 검토 → Apply** 순서로 재시도한다. 코드·설정·공개키가 바뀐 뒤에는 이전 Plan을 재사용하지 않는다.

## 6. 현재 EC2 주소로 인벤토리 생성

**Windows PowerShell**에서 실행한다. 대상 EC2가 실행 중이어야 한다.

```powershell
& $deployScript -Action Inventory -ProfileDirectory $deploymentProfile
```

정상 완료 메시지:

```text
Ansible 인벤토리 갱신: C:\third_project\aws-platform\platform\inventory\hosts.current.yml
```

이 명령은 Terraform 출력의 EC2 ID를 기준으로 AWS에서 현재 주소를 조회한다. 실제 소유 계정·태그·기동 상태·사양과 선택한 노드 구성이 일치하는지도 검사한다. `mongo` 역할은 기본 설정에 따라 Ansible `mongodb` 그룹으로 연결한다.

이후 Ansible에는 **항상 `-i inventory/hosts.current.yml`을 지정**한다. 기본 **hosts.yml**과 혼동하지 않는다. 다른 프로필을 쓰면 **platform.json**의 `inventory_name`에 맞춰 경로도 바꾼다.

## 7. 내 PC의 WSL에 Ansible과 키 준비

Windows Terminal의 **Ubuntu 탭**을 연다. PowerShell에서 여는 경우 기본 구성 기준 명령은 다음과 같다.

```powershell
wsl -d Ubuntu
```

이제부터 이 절의 명령은 **WSL**에서 실행한다. 이미 가상환경과 키가 준비됐다면 재설치·재복사는 생략하고 7.3절로 이동한다.

### 7.1 최초 가상환경 설치

```bash
# 내 PC의 WSL에 도구를 설치한다.
sudo apt update
sudo apt install -y python3-venv openssh-client
python3 -m venv "$HOME/.venvs/platform"
source "$HOME/.venvs/platform/bin/activate"
cd /mnt/c/third_project/aws-platform/platform
python -m pip install -r requirements.txt
```

이미 다른 경로에 Ansible을 설치했다면 그 환경을 사용하고 **platform.json**의 `ansible_venv`를 실제 경로와 맞춘다. 환경을 활성화한 WSL에서 `printf '%s\n' "$VIRTUAL_ENV"`로 확인할 수 있다.

### 7.2 기존 Windows 키를 WSL에 복사

WSL에 키가 없을 때만 실행한다. 다음 경로는 Windows 사용자 이름이 `Playdata`인 현재 PC 기준이다.

```bash
install -d -m 700 "$HOME/.ssh"
install -d -m 700 "$HOME/.ssh/project-key"

# 검증된 Windows 개인키를 WSL 사용자 전용 권한으로 복사한다.
for key in project-bastion.pem account2.pem account3.pem account4.pem account5.pem; do
  install -m 600 "/mnt/c/Users/Playdata/.ssh/project-key/$key" "$HOME/.ssh/project-key/$key" || break
done
```

복사 오류가 없어야 한다. 개인키 내용은 터미널이나 채팅에 출력하지 않는다.

### 7.3 WSL 실행 환경과 인벤토리 확인

WSL 터미널을 새로 열 때 아래 설정을 다시 실행한다.

```bash
source "$HOME/.venvs/platform/bin/activate"
cd /mnt/c/third_project/aws-platform/platform
export ANSIBLE_CONFIG=/mnt/c/third_project/aws-platform/platform/ansible.cfg
inventory=/mnt/c/third_project/aws-platform/platform/inventory/hosts.current.yml

ansible --version
ansible-inventory -i "$inventory" --graph
ansible -i "$inventory" all -m ansible.builtin.ping
```

모든 대상이 `SUCCESS`와 `"ping": "pong"`을 반환하면 SSH와 원격 Python 연결이 된 것이다. `changed: false`는 연결 검사에서 정상이다.

암호화된 Vault를 이미 사용하는 환경에서는 먼저 9.1절의 `ANSIBLE_VAULT_PASSWORD_FILE`을 설정해야 인벤토리 조회와 ping도 실행할 수 있다.

ping에서 인증 오류나 접속 시간 초과가 발생하면 [SSH 연결 장애](operations-recovery.md#72-ssh-인증-또는-접속-시간-초과)를 확인한다. 주소가 바뀐 경우는 [배스천 주소 갱신](operations-recovery.md#41-배스천-주소가-바뀐-뒤-다시-연결)으로 이동한다.

## 8. 전체 프록시와 APT 준비

기본 경로는 **Windows PowerShell**에서 실행하는 방법이다. WSL 창과 구분해서 선택한다.

```powershell
& $deployScript -Action Proxy -ProfileDirectory $deploymentProfile -Limit all
```

**deploy.ps1**이 **platform.json**을 읽고 WSL의 `aws-platform/platform/scripts/setup-proxy.sh`를 호출한다. 실행 순서는 다음과 같다.

1. 대상 호스트와 플레이북 문법 확인
2. SSH·원격 Python 연결 확인
3. 배스천 Squid 설치·접근 규칙과 APT 준비
4. 배스천 방화벽 적용 및 VPC에서 프록시 포트 접근 허용
5. 선택한 전체 서버의 Ubuntu 저장소 HTTPS 전환·APT 프록시 설정·목록 갱신
6. 방화벽 적용 후 HTTPS 연결과 파일 다운로드 재확인

`-Limit spark-3`은 spark-3을 클라이언트 대상으로 지정하는 값이다. **어떤 Limit을 사용해도 공용 배스천의 Squid·APT·방화벽은 먼저 준비한다.** `all`은 생성된 인벤토리에 있는 전체 서버를 뜻한다.

이미 WSL에 들어와 있거나 Vault 비밀번호 환경변수를 사용하는 경우에는 아래 방법으로 같은 작업을 실행한다. **두 방법을 모두 실행할 필요는 없다.**

```bash
# 7.3절의 환경 설정 후 실행한다. Vault가 있다면 9.1절의 환경변수도 설정한다.
bash /mnt/c/third_project/aws-platform/platform/scripts/setup-proxy.sh \
  --venv "$HOME/.venvs/platform" \
  --inventory "$inventory" \
  --limit all
```

성공 기준은 각 `PLAY RECAP`의 `failed=0`, `unreachable=0`과 마지막 **`프록시 준비 완료`**다. `changed`가 0보다 커도 실패가 아니다. 중간 오류가 발생하면 스크립트가 이후 단계를 중단하므로 마지막 완료 메시지까지 확인한다.

Squid 403·ERR_ACCESS_DENIED 또는 프록시 연결 시간 초과가 나오면 [프록시 장애 절차](operations-recovery.md#73-squid-접근-거부-또는-프록시-연결-실패)를 확인하고 이 단계부터 재실행한다.

## 9. 서비스 설치 전 준비

이 절부터는 **내 PC의 WSL**에서 진행한다. 먼저 7.3절의 가상환경·`ANSIBLE_CONFIG`·`inventory` 변수를 설정한다.

### 9.1 Vault 비밀번호와 DB Secret

DB 설치 전에는 MySQL·MongoDB 비밀번호와 MongoDB Replica Set 공유 키가 필요하다. 프록시만 준비할 때는 새 DB Secret을 만들 필요가 없다.

먼저 WSL 홈에 Vault 비밀번호 파일을 준비한다. 기존 파일이 있다면 같은 비밀번호를 유지한다. 편집기에는 Vault를 암호화할 비밀번호를 한 줄로 적는다.

```bash
install -d -m 700 "$HOME/.config/platform"
touch "$HOME/.config/platform/vault-pass"
chmod 600 "$HOME/.config/platform/vault-pass"
nano "$HOME/.config/platform/vault-pass"
export ANSIBLE_VAULT_PASSWORD_FILE="$HOME/.config/platform/vault-pass"
```

`ANSIBLE_VAULT_PASSWORD_FILE` 설정은 WSL 셸마다 필요하다. WSL에서 설정한 값은 PowerShell이 새로 여는 WSL 프로세스에 자동 전달되지 않으므로, Vault 생성 후 프록시를 다시 준비할 때는 8절의 **WSL 실행 방법**을 사용한다.

새 **vault.yml**이 아직 없을 때만 다음을 실행한다.

```bash
ansible-vault create inventory/group_vars/all/vault.yml
```

편집기에서 [vault.example.yml](../../aws-platform/platform/inventory/group_vars/all/vault.example.yml)의 형식을 참고하여 다음 값을 채운다. 값은 실제로 사용할 비밀값이어야 하며 빈 문자열이나 예시 문구를 남기지 않는다.

| 변수 | 필요한 항목 |
|---|---|
| `vault_mysql_passwords` | `root`, `dev`, `replication`, `monitor`, `failover`, `router` |
| `vault_mongodb_passwords` | `root`, `dev`, `monitor` |
| `vault_mongodb_keyfile` | MongoDB가 여러 대일 때 멤버들이 공유할 base64 키. YAML의 `\|` 아래에 들여써서 저장 |

현재 MySQL 역할은 비밀번호에 작은따옴표·큰따옴표·백슬래시·달러·백틱을 허용하지 않는다. 저장소 예시에 맞춰 8자 이상, 대문자·소문자·숫자·특수문자를 포함하고 각 비밀번호를 다르게 정한다. MongoDB 비밀번호도 예시 파일의 문자 제한을 따른다.

MongoDB 공유 키가 처음 필요할 때는 WSL에서 다음으로 생성하고 출력 전체를 Vault의 `vault_mongodb_keyfile`에 넣는다. 기존 Replica Set의 키는 재실행 때 다시 생성하지 않는다.

```bash
openssl rand -base64 756
```

이미 암호화된 파일이 있으면 생성 대신 수정 명령을 사용한다.

```bash
ansible-vault edit inventory/group_vars/all/vault.yml
```

현재 기본 인벤토리에는 `monitoring` 그룹이 없으므로 모니터링 SSH 키는 이 설치 순서의 필수 입력이 아니다. 모니터링을 추가할 때 예시 파일의 전용 키 쌍도 준비한다. 실제 Vault 파일·비밀번호 파일·개인키는 Git에 올리지 않는다.

Vault 복호화·Secret 오류는 [Vault 장애 확인](operations-recovery.md#74-vault-비밀번호-또는-secret-오류)으로 이동한다. 기존 Vault를 새 비밀번호·DB Secret으로 덮어쓰지 않는다.

### 9.2 데이터 EBS 사용 여부 확인

Terraform은 데이터 EBS 생성·연결까지 수행한다. **현재 이 설치 흐름에는 EBS 포맷·마운트 자동화가 없다.** 서비스 기본 데이터 경로와 실제 마운트를 먼저 맞춰야 데이터 EBS를 사용할 수 있다.

```bash
# 장치와 현재 파일시스템을 조회한다. 디스크를 변경하지 않는다.
ansible -i "$inventory" 'mysql:mongodb:kafka:spark' -b \
  -m ansible.builtin.command -a 'lsblk -f'
```

기본 경로는 MySQL `/var/lib/mysql`, Ubuntu MongoDB `/var/lib/mongodb`, Kafka `/var/lib/kafka/data`, Spark `/var/lib/spark`, ZooKeeper `/var/lib/zookeeper`다. 해당 디렉터리 또는 상위 디렉터리가 의도한 EBS를 사용하도록 마운트·영구 마운트 설정을 준비한 뒤 설치한다. 마운트하지 않으면 기본 경로는 OS 파일시스템에 만들어진다.

장치 이름을 추정한 `mkfs` 명령은 이 문서에 넣지 않는다. 실제 EBS ID, 기존 데이터 유무, 마운트 위치를 확인한 후 별도로 준비해야 한다. 상세 경계는 [서버 설치·배포 안내](../infra/bootstrap/bootstrap.md)를 참고한다.

### 9.3 현재 서비스 통신과 선택한 구성 확인

프록시 성공과 클러스터 통신 성공은 별개다. 기본 traffic과 플랫폼에는 아래 ZooKeeper·Spark 설정이 반영돼 있다. 이전 NewProfile로 만든 복사본에는 자동으로 반영되지 않으므로 실제로 선택한 traffic을 대조한다.

| 항목 | 현재 선언 | 적용·확인 |
| --- | --- | --- |
| ZooKeeper | Spark → Spark TCP 2181·2888·3888 | 선택한 traffic에 모두 있는지 확인하고 해당 계정 workload Plan·Apply |
| Spark Master·Worker | RPC 7077·7100, 내부 Master UI 8080, 데몬 재시도 0 | Spark SG 간 허용과 플랫폼 기본 변수·unit을 함께 확인 |
| Spark 작업 | Driver 7078–7094·BlockManager 7079–7095, 재시도 16 | port_end 키와 실제 끝 값 확인. 단일 7078·7079만 허용하는 오래된 구성은 갱신 |
| MySQL Cluster·Router | MySQL 3~9대·멤버 간 3306, game·Spark·선택 backend → MySQL 3306 | 기본 MySQL 세 대와 최신 인벤토리·마운트·방화벽 확인. Cluster 준비 후 앱·JDBC 실행 노드의 로컬 Router 설치 |
| game | 로컬 Router 대상, MySQL 접근 허용 | 앱 런타임·Kafka 연결·그 밖의 OS 방화벽은 별도 확인 |
| ad·consumer | 전용 앱·평탄화 프로그램 설치 역할 없음 | 앱 역할·Kafka 권한·OS 방화벽을 별도 확정. 그룹 이름 변경만으로 앱이 설치되지는 않음 |

기본 배치의 Spark SG는 account2·3·4에 있다. 규칙 변경은 해당 구성의 각 계정 workload를 새 Plan → 검토 → Apply로 반영한다. [Spark 포트 범위 테스트](infra-routing/tests/README.md#spark-포트-범위)는 정적·모의 전달 검사용이며 AWS 반영이나 서비스 설치 성공을 증명하지 않는다. 전체 site.yml 한 번이 모든 애플리케이션까지 설치하는 명령은 아니다.

## 10. 공통 OS 설정과 방화벽

**WSL**에서 먼저 문법을 확인한다.

```bash
ansible-playbook -i "$inventory" bootstrap-proxy.yml --syntax-check
ansible-playbook -i "$inventory" prepare-proxy.yml --syntax-check
ansible-playbook -i "$inventory" site.yml --syntax-check
```

현재처럼 `backend` 그룹이 없으면 `Could not match supplied host pattern, ignoring: backend` 경고가 나올 수 있다. 사용할 다른 대상 그룹이 실제로 존재하고 명령이 성공했는지도 함께 확인한다. 문법 검사만으로 접속이나 서비스 동작이 확인되지는 않는다.

공통 패키지·SSH·시간 동기화 설정:

```bash
ansible-playbook -i "$inventory" site.yml --tags common --limit all
```

현재 플랫폼 방화벽 규칙이 있는 역할에 방화벽 적용:

```bash
# 최신 인벤토리로 Front·Backend를 포함한 기존 역할의 방화벽을 적용한다.
ansible-playbook -i "$inventory" site.yml --tags firewall \
  --limit 'bastion:game_frontend:ad_frontend:game:ad:mysql:mongodb:kafka:spark'
```

방화벽 적용 후 SSH와 프록시가 유지되는지 확인한다.

```bash
ansible -i "$inventory" all -m ansible.builtin.ping
ansible-playbook -i "$inventory" prepare-proxy.yml --tags proxy_verify --limit all
```

모든 대상에 `failed=0`, `unreachable=0`을 확인하고 다음으로 넘어간다. 역할 태그를 지정하면 프록시 준비가 생략될 수 있으므로 8단계 완료가 선행 조건이다.

## 11. 역할별 서비스 설치

전부 **WSL**에서 실행한다. Vault와 해당 역할의 데이터 저장 위치·통신 조건이 준비된 상태여야 한다. 클러스터 초기화는 같은 역할 전체를 대상으로 실행한다. 예를 들어 Kafka 세 대 설치를 `--limit kafka-1`로 임의로 줄이지 않는다.

### 11.1 MySQL InnoDB Cluster

현재 인프라 기본값은 MySQL 세 대다. mysql-1(account3 Private A)·mysql-2(account5 Private A)·mysql-3(account4 Private A)를 모두 포함해야 한다. 2026-10-10 current 프로필의 mysql-3 EC2·EBS·SG 반영은 완료됐지만 아래 설치 명령을 이번 작업에서 실행하지 않았다. 같은 프로필로 Inventory·Proxy를 다시 실행하고 새 서버의 데이터 EBS 마운트·공통 OS 설정·방화벽을 준비한다. 멤버 간 TCP 3306과 game·Spark·선택 backend → MySQL TCP 3306의 실제 연결도 확인한다. [MySQL 역할](../../aws-platform/platform/docs/platform-routing/roles/mysql/README.md)은 전체 mysql 그룹 3~9대를 요구하고 기존 ReplicaSet의 자동 데이터 이전은 제공하지 않는다.

```bash
ansible-playbook -i "$inventory" site.yml --tags mysql --limit mysql
```

단일 Primary InnoDB Cluster를 구성한다. Cluster OK·모든 멤버 ONLINE·Primary 한 대·Secondary 읽기 전용과 계정 검사가 통과해야 완료다. 정상 설치 검증과 실제 Primary 중단·자동 선출 검증은 구분한다.

### 11.2 MongoDB

```bash
ansible-playbook -i "$inventory" site.yml --tags mongodb --limit mongodb
```

1대면 Standalone, 현재처럼 3대면 Replica Set을 구성한다. Ubuntu에서 실행 중인 커널이 역할의 차단 기준에 해당하면 커널 교체와 재부팅이 수행될 수 있다. 재부팅 후 연결 복구와 Replica Set 검증까지 기다린다.

### 11.3 Kafka

```bash
ansible-playbook -i "$inventory" site.yml --tags kafka --limit kafka
```

Java 의존성과 Kafka를 설치하고 KRaft 구성·쿼럼 검증을 수행한다. 현 역할의 지원 구성은 Kafka 3대다.

### 11.4 ZooKeeper와 Spark — 통신 조건 반영 후

**9.3절의 ZooKeeper·Spark 통신 조건을 먼저 맞춘 뒤** 실행한다.

```bash
ansible-playbook -i "$inventory" site.yml --tags zookeeper,spark --limit spark
```

Spark 서버에 ZooKeeper를 먼저 설치하고 Spark를 설치한다. zookeeper 태그만 선택하면 Spark unit·서비스는 설치되지 않으므로 둘을 구분한다. 기본 구성은 Master 2대, 전체 Worker 3대다. Master 선출·Worker 등록·작은 PySpark 작업과 커넥터 검증까지 성공해야 완료다.

ZooKeeper Mode 조회가 반복 실패하거나 Spark 설치가 중단되면 [ZooKeeper·Spark 장애 확인](operations-recovery.md#75-zookeeper-역할-조회-실패-또는-spark-설치-중단)에서 로그·통신 조건을 먼저 확인한다.

### MySQL Router 설치와 연동

Cluster와 Spark 설치가 끝난 뒤 game·Spark·선택 backend 서버에 적용한다. 별도 Router EC2는 만들지 않는다.

```bash
# 앱과 JDBC 실행 노드에 로컬 Router를 설치·bootstrap하고 Primary 연결을 검사한다.
ansible-playbook -i "$inventory" site.yml --tags mysql_router --limit 'game:spark:backend'
```

앱의 읽기·쓰기 접속은 127.0.0.1:6446, 읽기 전용은 6447이다. Spark JDBC를 수행하는 모든 실행 노드에 Router가 필요하다. 앱 연결 풀·트랜잭션 재시도는 별도 구현이며 Primary 장애 시 Router 재접속·쓰기 성공·노드 복귀는 원격에서 별도로 검증한다. [Router 역할](../../aws-platform/platform/docs/platform-routing/roles/backend/README.md) · [공유 변수](../../aws-platform/platform/docs/platform-routing/inventory/group_vars/all/mysql.yml.md)

### 11.5 완료 범위 확인

각 명령 끝의 `PLAY RECAP`에서 해당 역할의 모든 서버가 `failed=0`, `unreachable=0`이어야 한다. 설치 역할 안에 검증 작업이 포함되므로 검증 작업도 성공했는지 확인한다. `--tags verify`만 따로 실행하면 일부 역할의 사전 변수 계산이 생략될 수 있어 이 문서에서는 설치 단계에 포함된 검증을 사용한다.

여기까지는 기반 서비스 설치다. Frontend·게임·광고 애플리케이션, Consumer·Spark 업무 잡 배포는 별도다. 현재 인벤토리에 없는 `backend`·`monitoring` 그룹의 작업은 건너뛰며, Backend 역할도 현재 MySQL Router 설치까지만 구현되어 있다.

## 12. 나중에 구성을 바꾸거나 다시 접속할 때

### 12.1 PowerShell 창을 새로 연 경우

```powershell
Set-Location 'C:\third_project\aws-infra'
$deployScript = 'C:\third_project\aws-infra\infra\scripts\deploy.ps1'
$deploymentProfile = 'C:\third_project\aws-infra\infra\config\profiles\current'
```

### 12.2 기존 서버의 사양 변경

선택한 프로필의 topology를 수정하고 영향받는 계정의 계획을 확인한다. 아래는 **account1의 기존 서비스 EC2 사양만 바꾼 경우의 예시**다.

```powershell
& $deployScript -Action Plan -Stage workload -Account account1 -ProfileDirectory $deploymentProfile
```

계획 검토 후:

```powershell
& $deployScript -Action Apply -Stage workload -Account account1 -ProfileDirectory $deploymentProfile
& $deployScript -Action Inventory -ProfileDirectory $deploymentProfile
```

배스천 사양 변경은 `-Stage bastion`을 사용한다. 노드 추가·삭제·계정 이동은 역할별 SG 등 선행 자원도 바뀔 수 있으므로 5단계의 순서에 따라 각 단계의 계획부터 다시 검토한다. DB·Kafka 데이터나 클러스터 멤버를 자동 이전하는 명령은 아니다.

### 12.3 배스천 재시작·EC2 재생성으로 주소가 바뀐 경우

[배스천 상태·중지·시작](operations-recovery.md#4-배스천-상태-조회와-중지시작)과 [주소 변경 후 다시 연결](operations-recovery.md#41-배스천-주소가-바뀐-뒤-다시-연결)을 따른다. 인벤토리 갱신 후 프록시·방화벽·서비스 설정의 IP 영향을 확인하고 필요한 배포 단계로 돌아온다.

### 12.4 단계별 Terraform 명령 대신 사용할 수 있는 Deploy

3~4절의 입력과 7절의 WSL·키 준비가 끝났을 때 **5~8단계의 별도 Plan·Apply·Inventory·Proxy 대신** 사용할 수 있다.

```powershell
& $deployScript -Action Deploy -ProfileDirectory $deploymentProfile
```

`foundation → connectivity → workload → bastion` 순서로 각 단계의 Plan을 출력한다. 검토 후 정확히 `APPLY`를 입력해야 그 단계를 적용하며, 다른 값을 입력하면 중단한다. 네 단계 후 Inventory와 Proxy까지 실행한다. Vault가 이미 있으면 마지막 Proxy 단계에도 비밀번호 전달이 필요하므로 이 경우에는 단계별 Terraform 실행 후 WSL에서 Proxy를 실행하는 방법을 사용한다.

**Deploy에도 9~11절의 Secret·디스크 준비와 역할별 서비스 설치는 포함되어 있지 않다.**

## 13. 자주 만난 출력과 다음 조치

성공 출력은 다음 배포 단계로 진행하고, 오류 출력은 아래 복원·운영 링크에서 해당 증상의 절차를 따른다. 전체 삭제는 배포 오류를 해결하는 자동 복구 단계가 아니다.

| 출력·상황 | 의미와 다음 조치 | 복원·운영 절차 |
| --- | --- | --- |
| Ansible 인벤토리 갱신: ...hosts.current.yml | 인벤토리 생성 완료. 8절 Proxy로 진행 | — |
| SUCCESS, ping: pong, changed: false | SSH·원격 Python 연결 검사 성공 | — |
| failed=0, unreachable=0, changed=1 | 해당 실행 성공. APT 갱신 등 변경이 있었음 | — |
| skipping: no hosts matched / 서비스 LoadState=not-found | 대상 그룹·Limit·역할 설치 여부 확인 | [대상·설치 범위](operations-recovery.md#71-실행-대상이-없거나-설치되지-않은-서비스) |
| S3 버킷 이름 누락·NoSuchBucket·backend 접근 실패 | 이전 버킷 설정과 인증·권한 구분 | [S3 설정 복원](operations-recovery.md#1-s3-상태-버킷-설정-복원) |
| AMI 값 누락·InvalidAMIID | 계정·리전·조회 결과 확인 | [Ubuntu AMI 설정](operations-recovery.md#2-account-1-ubuntu-ami-조회와-설정) |
| 학교·집 이동 뒤 게임 HTTP 접속 실패 | 현재 공인 IP와 게임 접속 허용 범위 확인 | [공인 IP 설정](operations-recovery.md#3-테스트용-공인-ip-조회와-게임-접속-허용-설정) |
| ERR_ACCESS_DENIED / Squid 403 / 프록시 시간 초과 | Squid ACL·수신 포트·프록시 네트워크 확인 | [프록시 장애](operations-recovery.md#73-squid-접근-거부-또는-프록시-연결-실패) |
| Permission denied (publickey) / 키 파일 권한 오류 | 사용자·개인키 경로·배스천/목적지 인증 구분 | [SSH 인증 확인](operations-recovery.md#72-ssh-인증-또는-접속-시간-초과) |
| SSH Connection timed out | 전원·현재 주소·관리자 CIDR·네트워크 확인 | [SSH 접속 경로](operations-recovery.md#72-ssh-인증-또는-접속-시간-초과) |
| 배스천 중지·시작 또는 IP 변경 | 전원 상태 확인 후 새 주소 반영 | [배스천 운영](operations-recovery.md#4-배스천-상태-조회와-중지시작)·[주소 갱신](operations-recovery.md#41-배스천-주소가-바뀐-뒤-다시-연결) |
| Attempting to decrypt but no vault secrets found 등 | 기존 Vault 비밀번호 전달·Secret 확인 | [Vault 장애](operations-recovery.md#74-vault-비밀번호-또는-secret-오류) |
| ZooKeeper Mode 조회 실패·not currently serving requests | 로그·수신 상태·노드 간 통신 확인 | [ZooKeeper·Spark 장애](operations-recovery.md#75-zookeeper-역할-조회-실패-또는-spark-설치-중단) |
| 문자열에 종결자가 없습니다 / 깨진 한글 / WSL 실행 오류 | PowerShell 구문·인코딩·WSL 환경 확인 | [PowerShell·WSL 장애](operations-recovery.md#76-powershell-또는-wsl-실행-오류) |
| 저장 Plan 변경·prevent_destroy·배포 중 일부 실패 | 원인 해결 후 실패 단계의 새 Plan부터 재개 | [Terraform 재개](operations-recovery.md#77-terraform-계획-오류와-배포-재개) |

계획된 기존 서버 키 전환은 [SSH 키 등록 절차](operations-recovery.md#5-계정별-새-ssh-키-준비와-기존-서버-등록), 환경을 종료하는 별도 작업은 [전체 인프라 삭제](operations-recovery.md#6-전체-인프라-삭제)에서 확인한다.

## 코드와 대조할 위치

- [deploy.ps1](../infra/scripts/deploy.ps1): 구성 생성, 단계별 Plan·Apply, Inventory, WSL Proxy 호출
- [배포 실행기 설명](infra-routing/scripts/deploy.ps1.md): 상태 공유와 검증 범위
- [플랫폼 setup-proxy.sh](../../aws-platform/platform/scripts/setup-proxy.sh): 프록시 준비 실행 순서
- [bootstrap-proxy.yml](../../aws-platform/platform/bootstrap-proxy.yml) / [prepare-proxy.yml](../../aws-platform/platform/prepare-proxy.yml): Squid·APT 준비
- [site.yml](../../aws-platform/platform/site.yml): 역할 실행 대상과 태그
- [플랫폼 방화벽 규칙](../../aws-platform/platform/roles/firewall/vars/main.yml): 역할 간 허용 관계
- [Spark 설정](../../aws-platform/platform/roles/spark/templates/spark-env.sh.j2) / [Worker 실행 설정](../../aws-platform/platform/roles/spark/templates/spark-worker.service.j2): 실제 실행 포트와 구성

문서의 명령·옵션·태그·경로는 위 로컬 코드와 대조했다. 외부 다운로드 저장소 접근, 전체 EC2의 현재 상태, 서비스 설치 성공은 각 실행 단계에서 운영자가 확인해야 한다.

## mysql-3 증설 후 현재 상태

2026-10-10 current 프로필에서 account4 foundation 1개와 workload account1~5 각각 3 / 1 / 3 / 17 / 2개를 추가했다. 기존 자원의 변경·삭제는 없었고 [AWS 검증 기록](infra-routing/verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)에 mysql-3 주소·EC2·EBS와 SG 확인 결과를 남겼다. 기존 두 MySQL의 데이터를 자동으로 이전하거나 새 Cluster에 가입시키는 작업은 이 Terraform 반영에 포함되지 않는다.

account1의 전체 Plan에는 MySQL과 관계없는 ALB 재생성 4개가 섞여 있었다. 사용자 요청으로 복원을 보류하고 이번에만 저장 계획의 MySQL 규칙 3개로 범위를 제한해 적용했다. 기본 배포 명령에 -target 기능을 새로 구현한 것이 아니다. 현재 ALB가 없으므로 ALB URL을 통한 웹 검증은 진행할 수 없다. 당시에는 alb.enabled=true를 유지했다. 2026-10-11 기본 및 current 설정은 false로 변경했으며, 다른 기존 프로필의 활성화 값과 전용 연결은 별도로 확인한다.

ALB를 추후 다시 만들면 workload Output의 새 alb_dns_name을 확인하고 브라우저 주소·Django 허용 호스트·주소가 직접 설정된 앱 값을 갱신한다. 현재 MySQL 작업에서는 ALB나 Django 설정을 바꾸지 않았다.


## 광고 서버 생성 위치

기본 topology의 nodes.ad-server.az는 a이며 account1 Private A(apne2-az1)에 새로 생성한다. 기존 프로필은 자동 갱신되지 않으므로 선택한 프로필의 동일 항목을 확인한다. profiles/current도 로컬에서 A로 변경했지만 Git 제외 대상이다. ALB 설정·클러스터 노드 수는 이 AZ 변경에 포함하지 않는다. 사용자는 전체 삭제 명령 후 VPC 등 자원 삭제를 확인했다고 알렸으며, 이번 작업에서 실제 AWS 상태를 조회하거나 재생성하지 않았다.

## 평탄화 Consumer 변경 연결

flatten-1은 account2 Private A의 t3a.medium·OS 20GiB·공인 IP 및 별도 데이터 디스크 없음으로 정의한다. role=consumer를 유지하고 Kafka·Spark 그룹에 넣지 않는다. traffic의 consumer_kafka는 consumer→Kafka TCP 9092, consumer_mongo는 consumer→MongoDB TCP 27017, forward_proxy는 consumer→Bastion TCP 3128, SSH 연결은 Bastion→consumer TCP 22를 허용한다. 역할별 흐름은 송신·수신 보안그룹 규칙으로 펼쳐진다. 플랫폼 방화벽의 Kafka·MongoDB 허용 출처에도 consumer를 포함한다. Consumer 프로그램 배포와 원격 방화벽 적용은 별도다. foundation의 account2_private, workload의 account2_three_nodes·flatten.tftest.hcl·console-ssh.tftest.hcl과 fixtures.json의 consumer SG가 관련 검사 위치다. 이번 문서 작업은 테스트 실행 결과를 새로 주장하지 않는다.

## ALB 비활성화 적용 순서

2026-10-11 기본 및 current 설정에만 반영했으며 AWS Apply는 실행하지 않았다. 기존 배포에서 foundation의 ALB SG는 workload의 ALB·연결 규칙이 참조할 수 있으므로 일반 생성 순서인 foundation 우선 적용을 그대로 사용하지 않는다.

1. 선택한 topology의 alb.enabled=false와 traffic의 alb_front·alb_game·alb_ad 제거를 함께 확인한다. 이전 저장 계획은 재사용하지 않는다.
2. 기존 foundation 출력을 유지한 채 account1 workload의 새 Plan을 확인한다. ALB·리스너·대상 그룹·연결 규칙 정리 외에 EC2·EIP·디스크 변경이나 이전 미적용 변경이 섞였는지 검토한 뒤 적용한다.
3. ALB와 참조 규칙이 제거된 후 account1 foundation의 새 Plan에서 ALB SG 제거와 다른 자원의 유지 여부를 확인하고 적용한다.
4. 새 foundation 출력으로 account1 workload를 다시 계획하고 Inventory를 갱신한다. 다른 미적용 변경은 별도로 검토한다.

ALB 제거만으로 Front HTTPS 설치가 완료되지는 않는다. 현재 코드의 Front 외부 80·443 규칙 적용과 아래 Front별 Nginx·Certbot 설치가 필요하다. 실제 AWS 상태·잔존 SG 참조와 삭제 성공은 아직 확인하지 않았다.

## Account 1의 현재 배치와 전환 확인

기본 및 current 설정에는 edge-1이 없다. 모든 서버는 논리 A(apne2-az1)에 배치하며 C 서브넷은 유지한다. Account 1 서비스 구성은 다음과 같다.

| 서버 | 역할 | 서브넷 | 사양 | 공인 주소 |
| --- | --- | --- | --- | --- |
| front-a | game_frontend | Public A | t3.small | 게임 Front EIP |
| front-b | ad_frontend | Public A | t3.small | 광고 Front EIP |
| game-server | game | Private A | t3.large | 없음 |
| ad-server | ad | Private A | t3.large | 없음 |

선택 Bastion은 별도 bastion 상태에서 생성·삭제하며 자동 공인 IP를 사용한다. Front 각각에 Nginx·Certbot을 설치하고 자기 EIP의 인증서를 발급·갱신한다. edge라는 Ansible 역할·플레이북 이름은 설치 코드 재사용을 위한 이름이며 별도 edge EC2를 생성한다는 뜻이 아니다.

빈 환경에서는 본문의 foundation 5계정 → connectivity → workload → 선택 Bastion 순서를 따른다. 기존 환경은 옛 edge·frontend SG를 EC2나 다른 계정 규칙이 참조하는지 먼저 확인한다. 최신 foundation을 바로 적용하면 사용 중인 SG 제거와 충돌할 수 있다. 저장 상태와 새 Plan으로 참조 정리·새 SG 준비·EC2 변경 범위를 확인하기 전에는 일괄 Apply하지 않는다. 이 문서는 기존 AWS 자원의 삭제나 이관 완료를 확인한 기록이 아니다.

## Front별 HTTPS 설치

현재 프로필로 인프라 Plan·검토·Apply를 마친 뒤 Inventory를 재생성한다. 다른 프로필을 사용한다면 같은 ProfileDirectory와 그 platform.json의 inventory_name을 끝까지 사용한다.

```powershell
# aws-infra 폴더에서 현재 주소로 플랫폼 인벤토리를 갱신한다.
.\infra\scripts\deploy.ps1 -ProfileDirectory .\infra\config\profiles\current -Action Inventory
```

생성 인벤토리에서 다음 값을 확인한다. Inventory는 현재 구현상 서비스 서버와 Bastion이 실행 중이어야 생성할 수 있다.

- game_frontend와 ad_frontend 그룹에 각각 front-a·front-b가 있다.
- 각 Front의 public_ip는 자기 EIP이고 edge_frontend_upstreams는 대응 Backend 사설 IP:8000 한 개다.
- edge_frontend_mode=true, edge_http_redirect=true, edge_https_allowed_cidrs=[0.0.0.0/0]이다.
- 광고 Front만 edge_client_max_body_size=3m이며 게임 Front는 역할 기본값 1m을 사용한다.
- Account 1 네 서비스에는 account1_service_restricted=true가 있고 SSH는 준비된 Bastion·개인키를 경유한다.

공통 WSL·SSH 준비 후 플랫폼 폴더에서 실행한다. 이 명령은 실제 서버 설정과 인증서 발급을 수행한다. 아래 예시는 current의 inventory_name=hosts.current.yml 기준이다.

```bash
# aws-platform/platform 폴더에서 두 Front에 각각 Nginx·Certbot과 방화벽을 설치한다.
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
"$HOME/.venvs/platform/bin/ansible-playbook" \
  -i inventory/hosts.current.yml edge.yml \
  --limit 'game_frontend:ad_frontend'
```

게임 Front는 게임 Backend, 광고 Front는 광고 Backend의 사설 IP:8000으로 전달한다. /static/·/assets/도 해당 Backend로 넘기며 두 Front 사이의 전달은 구성하지 않는다. 각 Front 80·443은 전체 IPv4 공개이고 송신도 전체 IPv4를 허용한다. Account 1 Backend 8000 수신은 해당 Front SG만, 네 서비스 SSH 22는 Bastion SG만 허용한다. 동일한 제한이 서버 방화벽에도 적용되도록 인벤토리와 Ansible 적용 결과를 확인한다.

HTTP의 /.well-known/acme-challenge/는 검증 파일을 제공하고 나머지 경로는 HTTPS로 308 리다이렉트한다. 공인 IP HTTPS 구성에는 HSTS를 추가하지 않는다. 설치 후 각 Front에서 인증서·갱신 타이머, HTTP 리다이렉트, 대응 Backend 응답을 따로 확인한다. TLS 성공만으로 Django·광고 앱 배포까지 완료된 것은 아니다. 앱 실행·정적 파일 제공·환경변수는 별도 작업이다.

접속 장소의 공인 IP가 바뀌어도 공개 웹 80·443의 허용 목록은 바꾸지 않는다. 관리 SSH가 필요하면 admin_public_cidrs를 확인한다. Front 재생성으로 EIP가 바뀌면 Inventory를 다시 생성하고 각 Front의 인증서·Nginx와 앱에서 사용하는 외부 주소를 갱신한다.

<a id="진입용-edge-1-추가"></a>
<a id="edge-단독-초기-구축"></a>
<a id="edge-https-설치와-허용-ip-갱신"></a>

## 과거 edge 단독 구축 기록

2026-10-11의 edge-1 생성·설치 결과는 [과거 AWS 검증 기록](infra-routing/verification.md#2026-10-11-edge-https-실제-구축)에 남긴다. 당시의 설치 확인 페이지나 별도 hosts.edge.yml을 현재 Front 배포 결과로 보지 않는다. -EdgeBootstrapOnly는 이전 edge 전용 구성에 남은 옵션이며 현재 기본·current 프로필에는 사용하지 않는다. 현재 실행 절차는 위의 Front별 HTTPS 설치를 따른다.
