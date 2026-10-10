# Terraform VPC·EC2 생성부터 Ansible 설치까지

기준: 2026-10-10의 저장소 코드. Windows PC의 `C:\third_project\aws-infra`와 `C:\third_project\platform`을 함께 사용한다. 서버 OS는 현재 프록시 준비 코드가 지원하는 **Ubuntu 24.04 x86_64**를 기준으로 한다.

이 문서는 운영자가 실행할 명령과 완료 조건을 정리한 것이다. 문서 작성 과정에서 AWS 배포나 원격 Ansible 작업을 실행하지 않았다. **각 단계가 성공한 것을 확인한 뒤 다음 명령을 실행한다.**

## 지금 진행하던 작업에서 이어가기

이미 `current` 구성을 만들고 다음 메시지까지 확인했다면 VPC·EC2 생성과 인벤토리 생성은 반복하지 않는다.

```text
Ansible 인벤토리 갱신: C:\third_project\platform\inventory\hosts.current.yml
```

**기존 Windows PowerShell 창**에서 다음을 실행한다. 프롬프트가 `PS C:\third_project\aws-infra>`인 창이다.

```powershell
Set-Location 'C:\third_project\aws-infra'
$deployScript = 'C:\third_project\aws-infra\infra\scripts\deploy.ps1'
$deploymentProfile = 'C:\third_project\aws-infra\infra\config\profiles\current'

# 전체 인벤토리 서버의 프록시·APT 다운로드 환경을 준비한다.
& $deployScript -Action Proxy -ProfileDirectory $deploymentProfile -Limit all
```

WSL 가상환경과 SSH 키가 준비되어 있어야 한다. 아직 준비하지 않았다면 **6단계**부터 진행한다. 암호화된 `vault.yml`이 이미 있다면 **8.1단계**에서 비밀번호 파일을 준비하고, **7단계의 WSL 실행 방법**을 사용한다.

마지막에 `프록시 준비 완료`가 나오면 **8단계의 서비스 설치 전 확인**으로 넘어간다. 이 명령은 Kafka·Spark·MySQL·MongoDB를 설치하지 않는다.

## 1. 어느 터미널에서 실행하는가

| 구분 | 프롬프트 예시 | 실행할 작업 |
|---|---|---|
| Windows PowerShell | `PS C:\third_project\aws-infra>` | Terraform 실행, 구성 선택, 인벤토리 생성, `deploy.ps1` 실행 |
| 내 PC의 WSL Ubuntu | `(platform) playdatawsl@DESKTOP-...:/mnt/c/third_project/platform$` | Ansible 설치·실행, Vault 준비 |
| SSH로 들어간 EC2 | `ubuntu@ip-10-...:~$` | 이 문서의 배포 명령을 입력하는 곳이 아님 |

`C:\...`는 Windows 경로이고 `/mnt/c/...`는 같은 파일을 WSL에서 보는 경로다. 코드 블록 안의 명령만 복사한다. 프롬프트의 `PS ...>`나 `$`는 복사하지 않는다.

실행 순서는 다음과 같다.

```text
도구·AWS 인증·키 확인
→ 구성 선택
→ foundation: VPC·서브넷·기본 보안그룹
→ connectivity: 계정 간 VPC Peering·라우팅
→ workload: 서비스 EC2·EBS·보안그룹 규칙·ALB
→ bastion: 배스천 EC2
→ Inventory: 실제 주소로 Ansible 인벤토리 생성
→ Proxy: Squid·APT·다운로드 준비
→ Vault·디스크·서비스 통신 조건 확인
→ 공통 설정·방화벽
→ MySQL·MongoDB·Kafka·ZooKeeper·Spark 설치 및 역할 내 검증
```

## 2. 최초 준비

### 2.1 Windows 도구와 AWS 인증

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

현재 실행기는 PowerShell 5.1 이상, Terraform `>= 1.11, < 2.0`, AWS CLI와 WSL을 사용한다. 도구가 없다면 [Windows 설치 안내](../infra/setup-windows/README.md)를 먼저 따른다. WSL 배포판 이름은 이후 `platform.json`의 `wsl_distribution`과 같아야 한다.

기본 AWS 프로필 이름을 사용하는 경우 다음 조회가 모두 성공해야 한다. 이름을 바꿨다면 선택한 topology의 `accounts.*.profile` 값으로 바꾼다.

```powershell
# 반환된 Account가 해당 계정의 topology.accounts.*.id와 같은지 확인한다.
aws sts get-caller-identity --profile account1
aws sts get-caller-identity --profile account2
aws sts get-caller-identity --profile account3
aws sts get-caller-identity --profile account4
aws sts get-caller-identity --profile account5
```

다음 입력도 준비되어 있어야 한다. `deploy.ps1`이 AWS 인증이나 상태 버킷을 자동으로 만들지는 않는다.

| 입력 | 확인할 내용 |
|---|---|
| `infra/config/backend.json` | 기존 S3 상태 버킷, 리전, 접근 프로필, `key_prefix`. 버킷 버전 관리 및 상태·잠금 파일 접근 권한 |
| 선택한 `topology.tfvars.json` | 계정 ID·프로필, 리전, Ubuntu 24.04 x86_64 AMI, VPC CIDR, 역할·사양·디스크, 공개키 경로 |
| 선택한 `traffic.tfvars.json` | 관리자 공인 IP의 `/32` CIDR, 서비스 공개 범위, 역할 간 포트 |
| 계정별 개인키 | 아래 파일이 실제 EC2에 등록할 공개키와 쌍을 이루는지 확인 |

### 2.2 계정별 SSH 키

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

이 명령은 로컬 키 권한과 `infra/config/keys/account1.pub`~`account5.pub`, 기본 topology를 갱신한다. 기존 EC2의 로그인 키를 바꾸는 명령은 아니다. 이미 생성한 `current` 프로필도 자동 갱신하지 않는다. 현재처럼 새 EC2 접속까지 확인했다면 이 단계는 건너뛴다.

생성되는 Ansible 인벤토리는 **배스천 접속 키와 목적지 계정 키를 분리해서 사용**한다. 개인키를 배스천에 복사하는 단계는 필요하지 않다.

## 3. 구성 프로필 선택

**Windows PowerShell**에서 실행한다. `current` 프로필이 없을 때만 생성한다.

```powershell
& $deployScript -Action NewProfile -ProfileDirectory $deploymentProfile
```

이미 `infra/config/profiles/current/`에 아래 세 파일이 있으면 생성 명령을 생략한다. `NewProfile`은 기존 파일을 덮어쓰지 않는다.

| 파일 | 바꾸는 내용 |
|---|---|
| `topology.tfvars.json` | `nodes`의 계정 배치, `instance_type`, 노드 항목, 디스크 용량 등 |
| `traffic.tfvars.json` | 관리자 IP, 허용 포트, 역할 간 연결 |
| `platform.json` | 인벤토리 이름, WSL 배포판·가상환경 경로, 계정별 키 경로, 역할 그룹 연결 |

`current` 기본값은 인벤토리 `hosts.current.yml`, WSL 배포판 `Ubuntu`, 가상환경 `~/.venvs/platform`이다. 실제 환경과 다르면 이 파일에서 수정한다.

구성 변경 시 다음 경계를 지킨다.

- `NewProfile`은 기본 `infra/config`를 복사한다. 비용을 자동 계산하거나 저렴한 사양으로 자동 변경하지 않는다.
- 현재 실행기는 `account1`~`account5`와 **account1의 bastion 한 대**를 전제로 한다. 서비스 노드는 계정 간에 배치할 수 있다.
- 서로 다른 프로필도 **같은 원격 Terraform 상태를 사용**한다. `budget` 같은 이름을 만들어도 독립된 인프라 복사본이 생기는 것이 아니다.
- 노드 삭제·계정 이동은 기존 EC2·데이터에 영향을 준다. 현 코드의 데이터 EBS는 prevent_destroy=false이며 삭제·교체될 수 있다. 데이터 이전·백업은 자동화되어 있지 않다.
- Terraform에서 대수를 바꿀 수 있는 것과 플랫폼 역할이 지원하는 대수는 별개다. 현재 플랫폼 안내 기준은 MySQL 1 또는 2대, MongoDB 1 또는 3대, Kafka 3대, Spark 3대다. 노드 이름 끝 숫자는 서비스 ID에 쓰이므로 임의로 변경하지 않는다.

이후 모든 명령에서 **같은 `$deploymentProfile`**을 사용한다. `infra.ps1`을 구성 옵션 없이 직접 호출하면 기본 `infra/config`를 읽으므로 선택한 프로필과 다른 계획이 나올 수 있다.

## 4. Terraform으로 네트워크와 EC2 생성

전부 **Windows PowerShell**에서 실행한다. `Plan`과 `Apply`는 각각 따로 실행한다. `Plan` 결과의 생성·변경·삭제 목록을 검토한 후에만 다음 `Apply`를 실행한다. **개별 `Apply`는 추가 확인 질문 없이 저장된 계획을 적용한다.**

### 4.1 VPC·서브넷·기본 보안그룹: foundation

```powershell
& $deployScript -Action Plan -Stage foundation -ProfileDirectory $deploymentProfile
```

계획을 검토한 뒤 적용한다. `-Account`를 생략했으므로 다섯 계정을 순서대로 처리한다.

```powershell
& $deployScript -Action Apply -Stage foundation -ProfileDirectory $deploymentProfile
```

### 4.2 계정 간 Peering과 라우팅: connectivity

다섯 계정의 foundation이 모두 성공한 뒤 실행한다.

```powershell
& $deployScript -Action Plan -Stage connectivity -ProfileDirectory $deploymentProfile
```

```powershell
& $deployScript -Action Apply -Stage connectivity -ProfileDirectory $deploymentProfile
```

이 단계는 공동 단계이므로 `-Account account4` 같은 개별 계정 옵션을 붙이지 않는다.

### 4.3 서비스 EC2·EBS·통신 규칙·ALB: workload

```powershell
& $deployScript -Action Plan -Stage workload -ProfileDirectory $deploymentProfile
```

```powershell
& $deployScript -Action Apply -Stage workload -ProfileDirectory $deploymentProfile
```

### 4.4 배스천 EC2: bastion

```powershell
& $deployScript -Action Plan -Stage bastion -ProfileDirectory $deploymentProfile
```

```powershell
& $deployScript -Action Apply -Stage bastion -ProfileDirectory $deploymentProfile
```

각 단계의 모든 대상에 `Apply complete!`가 나오고 오류가 없어야 다음으로 넘어간다. 실패하면 성공한 앞 단계는 남는다. 원인을 고친 뒤 해당 단계의 **새 Plan → 검토 → Apply** 순서로 재시도한다. 코드·설정·공개키가 바뀐 뒤에는 이전 Plan을 재사용하지 않는다.

## 5. 현재 EC2 주소로 인벤토리 생성

**Windows PowerShell**에서 실행한다. 대상 EC2가 실행 중이어야 한다.

```powershell
& $deployScript -Action Inventory -ProfileDirectory $deploymentProfile
```

정상 완료 메시지:

```text
Ansible 인벤토리 갱신: C:\third_project\platform\inventory\hosts.current.yml
```

이 명령은 Terraform 출력의 EC2 ID를 기준으로 AWS에서 현재 주소를 조회한다. 실제 소유 계정·태그·기동 상태·사양과 선택한 노드 구성이 일치하는지도 검사한다. `mongo` 역할은 기본 설정에 따라 Ansible `mongodb` 그룹으로 연결한다.

이후 Ansible에는 **항상 `-i inventory/hosts.current.yml`을 지정**한다. 기본 `hosts.yml`과 혼동하지 않는다. 다른 프로필을 쓰면 `platform.json`의 `inventory_name`에 맞춰 경로도 바꾼다.

## 6. 내 PC의 WSL에 Ansible과 키 준비

Windows Terminal의 **Ubuntu 탭**을 연다. PowerShell에서 여는 경우 기본 구성 기준 명령은 다음과 같다.

```powershell
wsl -d Ubuntu
```

이제부터 이 절의 명령은 **WSL**에서 실행한다. 이미 가상환경과 키가 준비됐다면 재설치·재복사는 생략하고 6.3절로 이동한다.

### 6.1 최초 가상환경 설치

```bash
# 내 PC의 WSL에 도구를 설치한다.
sudo apt update
sudo apt install -y python3-venv openssh-client
python3 -m venv "$HOME/.venvs/platform"
source "$HOME/.venvs/platform/bin/activate"
cd /mnt/c/third_project/platform
python -m pip install -r requirements.txt
```

이미 다른 경로에 Ansible을 설치했다면 그 환경을 사용하고 `platform.json`의 `ansible_venv`를 실제 경로와 맞춘다. 환경을 활성화한 WSL에서 `printf '%s\n' "$VIRTUAL_ENV"`로 확인할 수 있다.

### 6.2 기존 Windows 키를 WSL에 복사

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

### 6.3 WSL 실행 환경과 인벤토리 확인

WSL 터미널을 새로 열 때 아래 설정을 다시 실행한다.

```bash
source "$HOME/.venvs/platform/bin/activate"
cd /mnt/c/third_project/platform
export ANSIBLE_CONFIG=/mnt/c/third_project/platform/ansible.cfg
inventory=/mnt/c/third_project/platform/inventory/hosts.current.yml

ansible --version
ansible-inventory -i "$inventory" --graph
ansible -i "$inventory" all -m ansible.builtin.ping
```

모든 대상이 `SUCCESS`와 `"ping": "pong"`을 반환하면 SSH와 원격 Python 연결이 된 것이다. `changed: false`는 연결 검사에서 정상이다.

암호화된 Vault를 이미 사용하는 환경에서는 먼저 8.1절의 `ANSIBLE_VAULT_PASSWORD_FILE`을 설정해야 인벤토리 조회와 ping도 실행할 수 있다.

## 7. 전체 프록시와 APT 준비

기본 경로는 **Windows PowerShell**에서 실행하는 방법이다. WSL 창과 구분해서 선택한다.

```powershell
& $deployScript -Action Proxy -ProfileDirectory $deploymentProfile -Limit all
```

`deploy.ps1`이 `platform.json`을 읽고 WSL의 `platform/setup-proxy.sh`를 호출한다. 실행 순서는 다음과 같다.

1. 대상 호스트와 플레이북 문법 확인
2. SSH·원격 Python 연결 확인
3. 배스천 Squid 설치·접근 규칙과 APT 준비
4. 배스천 방화벽 적용 및 VPC에서 프록시 포트 접근 허용
5. 선택한 전체 서버의 Ubuntu 저장소 HTTPS 전환·APT 프록시 설정·목록 갱신
6. 방화벽 적용 후 HTTPS 연결과 파일 다운로드 재확인

`-Limit spark-3`은 spark-3을 클라이언트 대상으로 지정하는 값이다. **어떤 Limit을 사용해도 공용 배스천의 Squid·APT·방화벽은 먼저 준비한다.** `all`은 생성된 인벤토리에 있는 전체 서버를 뜻한다.

이미 WSL에 들어와 있거나 Vault 비밀번호 환경변수를 사용하는 경우에는 아래 방법으로 같은 작업을 실행한다. **두 방법을 모두 실행할 필요는 없다.**

```bash
# 6.3절의 환경 설정 후 실행한다. Vault가 있다면 8.1절의 환경변수도 설정한다.
bash /mnt/c/third_project/platform/setup-proxy.sh \
  --venv "$HOME/.venvs/platform" \
  --inventory "$inventory" \
  --limit all
```

성공 기준은 각 `PLAY RECAP`의 `failed=0`, `unreachable=0`과 마지막 **`프록시 준비 완료`**다. `changed`가 0보다 커도 실패가 아니다. 중간 오류가 발생하면 스크립트가 이후 단계를 중단하므로 마지막 완료 메시지까지 확인한다.

## 8. 서비스 설치 전 준비

이 절부터는 **내 PC의 WSL**에서 진행한다. 먼저 6.3절의 가상환경·`ANSIBLE_CONFIG`·`inventory` 변수를 설정한다.

### 8.1 Vault 비밀번호와 DB Secret

DB 설치 전에는 MySQL·MongoDB 비밀번호와 MongoDB Replica Set 공유 키가 필요하다. 프록시만 준비할 때는 새 DB Secret을 만들 필요가 없다.

먼저 WSL 홈에 Vault 비밀번호 파일을 준비한다. 기존 파일이 있다면 같은 비밀번호를 유지한다. 편집기에는 Vault를 암호화할 비밀번호를 한 줄로 적는다.

```bash
install -d -m 700 "$HOME/.config/platform"
touch "$HOME/.config/platform/vault-pass"
chmod 600 "$HOME/.config/platform/vault-pass"
nano "$HOME/.config/platform/vault-pass"
export ANSIBLE_VAULT_PASSWORD_FILE="$HOME/.config/platform/vault-pass"
```

`ANSIBLE_VAULT_PASSWORD_FILE` 설정은 WSL 셸마다 필요하다. WSL에서 설정한 값은 PowerShell이 새로 여는 WSL 프로세스에 자동 전달되지 않으므로, Vault 생성 후 프록시를 다시 준비할 때는 7절의 **WSL 실행 방법**을 사용한다.

새 `vault.yml`이 아직 없을 때만 다음을 실행한다.

```bash
ansible-vault create inventory/group_vars/all/vault.yml
```

편집기에서 [vault.example.yml](../../platform/inventory/group_vars/all/vault.example.yml)의 형식을 참고하여 다음 값을 채운다. 값은 실제로 사용할 비밀값이어야 하며 빈 문자열이나 예시 문구를 남기지 않는다.

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

### 8.2 데이터 EBS 사용 여부 확인

Terraform은 데이터 EBS 생성·연결까지 수행한다. **현재 이 설치 흐름에는 EBS 포맷·마운트 자동화가 없다.** 서비스 기본 데이터 경로와 실제 마운트를 먼저 맞춰야 데이터 EBS를 사용할 수 있다.

```bash
# 장치와 현재 파일시스템을 조회한다. 디스크를 변경하지 않는다.
ansible -i "$inventory" 'mysql:mongodb:kafka:spark' -b \
  -m ansible.builtin.command -a 'lsblk -f'
```

기본 경로는 MySQL `/var/lib/mysql`, Ubuntu MongoDB `/var/lib/mongodb`, Kafka `/var/lib/kafka/data`, Spark `/var/lib/spark`, ZooKeeper `/var/lib/zookeeper`다. 해당 디렉터리 또는 상위 디렉터리가 의도한 EBS를 사용하도록 마운트·영구 마운트 설정을 준비한 뒤 설치한다. 마운트하지 않으면 기본 경로는 OS 파일시스템에 만들어진다.

장치 이름을 추정한 `mkfs` 명령은 이 문서에 넣지 않는다. 실제 EBS ID, 기존 데이터 유무, 마운트 위치를 확인한 후 별도로 준비해야 한다. 상세 경계는 [서버 설치·배포 안내](../infra/bootstrap/README.md)를 참고한다.

### 8.3 현재 서비스 통신과 선택한 구성 확인

프록시 성공과 클러스터 통신 성공은 별개다. 기본 traffic과 플랫폼에는 아래 ZooKeeper·Spark 설정이 반영돼 있다. 이전 NewProfile로 만든 복사본에는 자동으로 반영되지 않으므로 실제로 선택한 traffic을 대조한다.

| 항목 | 현재 선언 | 적용·확인 |
| --- | --- | --- |
| ZooKeeper | Spark → Spark TCP 2181·2888·3888 | 선택한 traffic에 모두 있는지 확인하고 해당 계정 workload Plan·Apply |
| Spark Master·Worker | RPC 7077·7100, 내부 Master UI 8080, 데몬 재시도 0 | Spark SG 간 허용과 플랫폼 기본 변수·unit을 함께 확인 |
| Spark 작업 | Driver 7078–7094·BlockManager 7079–7095, 재시도 16 | port_end 키와 실제 끝 값 확인. 단일 7078·7079만 허용하는 오래된 구성은 갱신 |
| game·ad | 전용 설치 역할·플랫폼 방화벽 그룹 규칙 없음 | 앱 역할·DB/Kafka 권한·OS 방화벽을 별도 확정. 그룹 이름 변경만으로 앱이 설치되지는 않음 |

기본 배치의 Spark SG는 account2·3·4에 있다. 규칙 변경은 해당 구성의 각 계정 workload를 새 Plan → 검토 → Apply로 반영한다. [Spark 포트 범위 테스트](infra-routing/tests/README.md#spark-포트-범위)는 정적·모의 전달 검사용이며 AWS 반영이나 서비스 설치 성공을 증명하지 않는다. 전체 site.yml 한 번이 모든 애플리케이션까지 설치하는 명령은 아니다.

## 9. 공통 OS 설정과 방화벽

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
# game·ad는 8.3절의 역할·통신 규칙을 정한 뒤 별도로 적용한다.
ansible-playbook -i "$inventory" site.yml --tags firewall \
  --limit 'bastion:frontend:mysql:mongodb:kafka:spark'
```

방화벽 적용 후 SSH와 프록시가 유지되는지 확인한다.

```bash
ansible -i "$inventory" all -m ansible.builtin.ping
ansible-playbook -i "$inventory" prepare-proxy.yml --tags proxy_verify --limit all
```

모든 대상에 `failed=0`, `unreachable=0`을 확인하고 다음으로 넘어간다. 역할 태그를 지정하면 프록시 준비가 생략될 수 있으므로 7단계 완료가 선행 조건이다.

## 10. 역할별 서비스 설치

전부 **WSL**에서 실행한다. Vault와 해당 역할의 데이터 저장 위치·통신 조건이 준비된 상태여야 한다. 클러스터 초기화는 같은 역할 전체를 대상으로 실행한다. 예를 들어 Kafka 세 대 설치를 `--limit kafka-1`로 임의로 줄이지 않는다.

### 10.1 MySQL

```bash
ansible-playbook -i "$inventory" site.yml --tags mysql --limit mysql
```

1대면 Standalone, 현재처럼 2대면 InnoDB ReplicaSet을 구성한다. 설치와 계정·복제 상태 검사가 모두 통과해야 완료다.

### 10.2 MongoDB

```bash
ansible-playbook -i "$inventory" site.yml --tags mongodb --limit mongodb
```

1대면 Standalone, 현재처럼 3대면 Replica Set을 구성한다. Ubuntu에서 실행 중인 커널이 역할의 차단 기준에 해당하면 커널 교체와 재부팅이 수행될 수 있다. 재부팅 후 연결 복구와 Replica Set 검증까지 기다린다.

### 10.3 Kafka

```bash
ansible-playbook -i "$inventory" site.yml --tags kafka --limit kafka
```

Java 의존성과 Kafka를 설치하고 KRaft 구성·쿼럼 검증을 수행한다. 현 역할의 지원 구성은 Kafka 3대다.

### 10.4 ZooKeeper와 Spark — 통신 조건 반영 후

**8.3절의 ZooKeeper·Spark 통신 조건을 먼저 맞춘 뒤** 실행한다.

```bash
ansible-playbook -i "$inventory" site.yml --tags zookeeper,spark --limit spark
```

Spark 서버에 ZooKeeper를 먼저 설치하고 Spark를 설치한다. zookeeper 태그만 선택하면 Spark unit·서비스는 설치되지 않으므로 둘을 구분한다. 기본 구성은 Master 2대, 전체 Worker 3대다. Master 선출·Worker 등록·작은 PySpark 작업과 커넥터 검증까지 성공해야 완료다.

### 10.5 완료 범위 확인

각 명령 끝의 `PLAY RECAP`에서 해당 역할의 모든 서버가 `failed=0`, `unreachable=0`이어야 한다. 설치 역할 안에 검증 작업이 포함되므로 검증 작업도 성공했는지 확인한다. `--tags verify`만 따로 실행하면 일부 역할의 사전 변수 계산이 생략될 수 있어 이 문서에서는 설치 단계에 포함된 검증을 사용한다.

여기까지는 기반 서비스 설치다. Frontend·게임·광고 애플리케이션, Consumer·Spark 업무 잡 배포는 별도다. 현재 인벤토리에 없는 `backend`·`monitoring` 그룹의 작업은 건너뛰며, Backend 역할도 현재 MySQL Router 설치까지만 구현되어 있다.

## 11. 나중에 구성을 바꾸거나 다시 접속할 때

### 11.1 PowerShell 창을 새로 연 경우

```powershell
Set-Location 'C:\third_project\aws-infra'
$deployScript = 'C:\third_project\aws-infra\infra\scripts\deploy.ps1'
$deploymentProfile = 'C:\third_project\aws-infra\infra\config\profiles\current'
```

### 11.2 기존 서버의 사양 변경

선택한 프로필의 topology를 수정하고 영향받는 계정의 계획을 확인한다. 아래는 **account1의 기존 서비스 EC2 사양만 바꾼 경우의 예시**다.

```powershell
& $deployScript -Action Plan -Stage workload -Account account1 -ProfileDirectory $deploymentProfile
```

계획 검토 후:

```powershell
& $deployScript -Action Apply -Stage workload -Account account1 -ProfileDirectory $deploymentProfile
& $deployScript -Action Inventory -ProfileDirectory $deploymentProfile
```

배스천 사양 변경은 `-Stage bastion`을 사용한다. 노드 추가·삭제·계정 이동은 역할별 SG 등 선행 자원도 바뀔 수 있으므로 4단계의 순서에 따라 각 단계의 계획부터 다시 검토한다. DB·Kafka 데이터나 클러스터 멤버를 자동 이전하는 명령은 아니다.

### 11.3 배스천 재시작·EC2 재생성으로 주소가 바뀐 경우

Windows PowerShell에서 인벤토리를 다시 만든다.

```powershell
& $deployScript -Action Inventory -ProfileDirectory $deploymentProfile
```

WSL에서 6.3절의 환경과, Vault를 사용한다면 8.1절의 비밀번호 환경변수를 다시 설정한다. 7절의 WSL 프록시 준비 명령을 실행해 현재 주소를 반영한다. 기존 역할 방화벽도 인벤토리의 IP를 사용하므로 9절의 방화벽을 다시 적용한다. 서비스 설정에도 IP가 들어가므로 주소가 바뀐 클러스터는 각 역할의 재구성과 데이터 유지 절차를 검토한다.

### 11.4 단계별 Terraform 명령 대신 사용할 수 있는 Deploy

2~3절의 입력과 6절의 WSL·키 준비가 끝났을 때 **4~7단계의 별도 Plan·Apply·Inventory·Proxy 대신** 사용할 수 있다.

```powershell
& $deployScript -Action Deploy -ProfileDirectory $deploymentProfile
```

`foundation → connectivity → workload → bastion` 순서로 각 단계의 Plan을 출력한다. 검토 후 정확히 `APPLY`를 입력해야 그 단계를 적용하며, 다른 값을 입력하면 중단한다. 네 단계 후 Inventory와 Proxy까지 실행한다. Vault가 이미 있으면 마지막 Proxy 단계에도 비밀번호 전달이 필요하므로 이 경우에는 단계별 Terraform 실행 후 WSL에서 Proxy를 실행하는 방법을 사용한다.

**Deploy에도 8~10절의 Secret·디스크 준비와 역할별 서비스 설치는 포함되어 있지 않다.**

## 12. 자주 만난 출력과 다음 조치

| 출력 | 의미와 조치 |
|---|---|
| `Ansible 인벤토리 갱신: ...hosts.current.yml` | 인벤토리 생성 완료. Proxy로 진행 |
| `SUCCESS`, `ping: pong`, `changed: false` | SSH·원격 Python 연결 검사 성공 |
| `failed=0`, `unreachable=0`, `changed=1` | 해당 실행은 성공했고 설정 변경 또는 APT 갱신 등이 있었음 |
| `skipping: no hosts matched` | Limit 밖의 플레이나 없는 그룹일 수 있음. 의도한 대상까지 0대인지 확인 |
| `ERR_ACCESS_DENIED` 또는 Squid 403 | 프록시에는 도달했지만 Squid 접근 규칙에서 거부. bootstrap-proxy 실행 결과와 allow/deny 순서 확인 |
| `Permission denied (publickey)` | 키·사용자·인벤토리의 목적지/배스천 인증 확인. 현재 account1 기본 키는 `project-bastion.pem` |
| `Connection timed out` | 현재 IP, 서버 상태, 관리자 CIDR, Peering·라우팅·SG 확인. 키 형식 오류와 구분 |
| `Attempting to decrypt but no vault secrets found` 등 Vault 오류 | WSL의 `ANSIBLE_VAULT_PASSWORD_FILE` 및 기존 Vault 비밀번호 확인 |
| `문자열에 " 종결자가 없습니다`와 깨진 한글 | PowerShell 5.1에서 한국어 `.ps1`을 UTF-8 BOM으로 저장했는지 확인 |
| 배포 도중 실패 | 뒤 단계를 이어서 실행하지 말고 원인 해결. Terraform은 새 Plan부터, Ansible은 실패한 역할 전체부터 재실행 |

## 코드와 대조할 위치

- [deploy.ps1](../infra/scripts/deploy.ps1): 구성 생성, 단계별 Plan·Apply, Inventory, WSL Proxy 호출
- [배포 실행기 설명](infra-routing/scripts/deploy.ps1.md): 상태 공유와 검증 범위
- [플랫폼 setup-proxy.sh](../../platform/setup-proxy.sh): 프록시 준비 실행 순서
- [bootstrap-proxy.yml](../../platform/bootstrap-proxy.yml) / [prepare-proxy.yml](../../platform/prepare-proxy.yml): Squid·APT 준비
- [site.yml](../../platform/site.yml): 역할 실행 대상과 태그
- [플랫폼 방화벽 규칙](../../platform/roles/firewall/vars/main.yml): 역할 간 허용 관계
- [Spark 설정](../../platform/roles/spark/templates/spark-env.sh.j2) / [Worker 실행 설정](../../platform/roles/spark/templates/spark-worker.service.j2): 실제 실행 포트와 구성

문서의 명령·옵션·태그·경로는 위 로컬 코드와 대조했다. 외부 다운로드 저장소 접근, 전체 EC2의 현재 상태, 서비스 설치 성공은 각 실행 단계에서 운영자가 확인해야 한다.
