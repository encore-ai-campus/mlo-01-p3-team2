# platform

실행 코드·설정·문서를 저장소 루트의 `aws-platform/platform/`에 함께 둔다. 아래 명령은 이 디렉터리에서 실행한다.

막 생성된 Ubuntu 24.04 LTS(기본) 또는 Amazon Linux 2023 VM에 Ansible로 보안 설정과 역할별 구축을 한다. OS는 서버에서 자동 감지한다. 설계와 결정 사항은 [자동화 설계](../design/infra-automation-design.md)에 있다.

코드·설정의 위치와 역할은 [Platform 라우팅 문서](platform-routing/ROUTING-README.md)에서 찾는다. 소스 상대경로에 대응하는 파일별 문서, 역할별 README와 [정적 검증 기록](platform-routing/verification.md)을 제공한다.

## 구현 상태와 과거 검증

아래 표는 기존 구현 당시의 실험 기록이다. 현재 aws-infra에서 생성한 서버의 설치 완료를 뜻하지 않으며, 2026-10-10의 Proxy·Spark 포트 변경을 원격 재검증한 결과도 아니다. 현재 기본 배치는 MySQL 2·MongoDB 3·Kafka 3·Spark/ZooKeeper 3·Front 2·game 1·ad 1과 선택 Bastion 1이다. backend·monitoring 그룹은 생성 인벤토리에 없을 수 있다.

| 단계 | 상태 |
|---|---|
| 공통 보안 (`roles/common`: sshd, 팀원 계정, sudo, 시간 동기화·UTC, 검증) | 구현, 서버 1대(`t3a.nano`)에서 검증 |
| 방화벽 (`roles/firewall`: nftables 전용 테이블, 역할 간 허용 관계, 복구 타이머, 부팅 때 로드) | 구현, 서버 2대(Bastion + 사설 서버)에서 검증 |
| MySQL (`roles/mysql`: 설치, 계정 6종, Standalone 또는 InnoDB ReplicaSet, 검증) | 구현, 서버 3대(ReplicaSet 2대, Standalone 1대)에서 검증 |
| MongoDB (`roles/mongodb`: 설치, keyfile·인증, 계정 3종, Standalone 또는 Replica Set, 검증) | 구현, 서버 4대(Replica Set 3대, Standalone 1대)에서 검증 |
| Kafka (`roles/java`, `roles/kafka`: Corretto 17, KRaft combined 3대, sha512 검증, 검증) | 구현, 서버 3대에서 검증 |
| ZooKeeper·Spark (`roles/zookeeper`, `roles/spark`: ZooKeeper ensemble, Master 2 + Worker 3 이중화, Python 3.12, 커넥터 JAR, 검증) | 구현, 서버 3대에서 검증 |
| Backend (`roles/backend`: MySQL Router 설치까지), Frontend (공통 보안·방화벽만) | 구현, 서버 4대에서 검증 |
| Monitoring (`roles/monitoring`: `monitor` 사용자, 수집 루프(리소스 10초·서비스 30초·로그 10초), 하트비트, 로그 회전·보관) | 구현, 서버 15대(설계 구성 전체)에서 검증 |
| Ubuntu 24.04 LTS 지원 (기본 OS. `roles/pkg`의 apt 설치·저장소, OS별 `vars/`, MongoDB 커널 호환, chrony 시간원, needrestart, AppArmor 고려) | 구현, 설계 구성 15대와 작은 구성 2대에서 검증. AL2023도 15대 회귀 통과 |
| 통합 (전체 구성 실행·재실행, 인터넷 차단 후 재실행, 작은 구성, 방화벽 허용 관계, 서비스 연동, 수동 장애 확인) | 설계 구성 15대와 작은 구성 2대에서 검증 |

## 실행

운영 PC의 WSL에서 준비한 Ansible 가상환경을 활성화한다. 생성한 인벤토리는 해당 배포 프로필의 파일을 선택한다. 수동 인벤토리를 쓰면 [예시](inventory/hosts.example.yml)를 참고해 hosts.yml을 별도로 작성한다.

```bash
cd /mnt/c/third_project/aws-platform/platform
source "$HOME/.venvs/platform/bin/activate"
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
inventoryFile="$PWD/inventory/hosts.current.yml"
# 이미 암호화된 Vault가 있으면 아래 Secret 절차의 비밀번호도 준비한다.
ansible-playbook -i "$inventoryFile" site.yml --syntax-check
ansible 'bastion:spark-3' -i "$inventoryFile" -m ansible.builtin.ping
```

프록시 준비·Vault·데이터 마운트 후 필요한 역할을 실행한다. `--tags common`은 공통 OS 설정, `--tags zookeeper`는 ZooKeeper만 설치한다. 별도 `--tags verify` 실행은 역할의 사전 변수 계산을 생략할 수 있으므로 설치 역할에 포함된 검증을 사용한다. 상세 설치 순서는 [배포 절차](../../aws-infra/docs/deployment-runbook.md)에 있다.

```bash
# 클러스터 초기화와 검증은 해당 역할의 모든 서버를 대상으로 한다.
ansible-playbook -i "$inventoryFile" site.yml --tags mysql --limit mysql --ask-vault-pass
ansible-playbook -i "$inventoryFile" site.yml --tags mongodb --limit mongodb --ask-vault-pass
ansible-playbook -i "$inventoryFile" site.yml --tags kafka --limit kafka --ask-vault-pass
ansible-playbook -i "$inventoryFile" site.yml --tags zookeeper,spark --limit spark --ask-vault-pass
```

각 실행의 failed=0·unreachable=0과 역할별 DB 복제·Kafka 송수신·ZooKeeper ensemble·Spark Worker 등록·작업 검증을 확인한다. 전체 실행은 인벤토리의 역할·방화벽을 모두 준비한 경우에만 `ansible-playbook -i "$inventoryFile" site.yml --ask-vault-pass`로 진행한다. game·ad 앱은 이 명령이 설치하지 않는다.

## 알아 둘 것

프록시를 사용하는 구성은 아래 "배스천 프록시로 설치 준비" 절차를 먼저 진행한다.

- 지원 OS는 Ubuntu 24.04 LTS(기본)와 Amazon Linux 2023이다. 접속 사용자는 Ubuntu는 `ubuntu`, AL2023은 `ec2-user`다(인벤토리 `ansible_user`). Ubuntu에서 MongoDB 서버는 첫 실행 때 커널을 GA 6.8로 바꾸고 재부팅한다.

- 서버를 지우고 다시 만들 때 사설 IP가 같으면 SSH가 `Host key verification failed`로 거부된다. 개발자 PC에서 `ssh-keygen -R <IP>`로 옛 항목을 지운다.
- 설치된 패키지·tarball·JAR·GPG 키는 재실행 때 다운로드를 생략하는 작업이 있지만, Proxy 준비는 외부 검사를 포함한다. NAT 0개 기본 구성에서는 Bastion Proxy를 사용하며 전체 실행을 무조건 오프라인 실행으로 해석하지 않는다.
- 구축 후 Spark와 Kafka·MongoDB·MySQL의 연동은 [tests/spark_integration.py](tests/spark_integration.py)로 확인할 수 있다 (Spark 노드에서 `spark-submit`으로 제출, 환경변수는 파일 맨 위 설명 참고).

## Secret(Vault)

프록시 준비와 배스천 방화벽만 검사할 때는 DB Secret을 만들 필요가 없다. 이미 암호화된 vault.yml이 있다면 아래 비밀번호 설정은 필요하다.

Secret은 `inventory/group_vars/all/vault.yml`에 두고 암호화한다. 형식과 값을 채우는 방법은 [vault.example.yml](inventory/group_vars/all/vault.example.yml)에 적혀 있다.

```bash
# 예제의 DB 값을 실제 값으로 채운 후 대화형 Vault 암호로 암호화한다.
cp inventory/group_vars/all/vault.example.yml inventory/group_vars/all/vault.yml
ansible-vault encrypt inventory/group_vars/all/vault.yml
```

New Vault password와 Confirm New Vault password에 암호를 입력한다. 이후 설치 명령에 --ask-vault-pass를 추가해 같은 암호를 입력하거나 운영자가 관리하는 비밀번호 파일을 ANSIBLE_VAULT_PASSWORD_FILE로 지정한다. Vault 암호와 파일 안의 DB 계정 비밀번호는 별개다. 기존 vault.yml을 사용하는 경우 위 복사·암호화 명령을 다시 실행해 덮어쓰지 않는다.

- 암호화한 vault.yml이 있으면 이를 읽는 실행에 Vault 암호가 필요하다. 비밀번호 파일 또는 --ask-vault-pass를 사용한다. Secret을 쓰지 않는 단계도 해당 파일을 읽으면 암호가 필요하다.
- `vault.yml`(암호화한 것 포함), `.vault_pass`, `inventory/hosts.yml`은 저장소에 올리지 않는다(`aws-platform/platform/.gitignore`). 운영자가 각자 만든다.

## 가능한 구성

서비스 역할의 대수 제한은 프로그램이 일괄 검증하지 않는다. 아래 서비스 구성을 기준으로 사용하며 다른 대수의 클러스터는 별도 검토·검증이 필요하다. 모드는 대수에서 자동으로 정해진다.

| 역할 | 가능한 대수 | 모드 |
|---|---|---|
| Bastion | Proxy 활성 구성에서 1 | 별도 EC2이며 모든 목적지 연결의 경유점 |
| Frontend, Monitoring, Backend | 그룹별 배치. 현재 Frontend 2대, 나머지는 없을 수 있음 | 공통 설정·방화벽, Backend는 Router 설치까지 |
| MySQL | 1 또는 2 | 1대 Standalone, 2대 InnoDB ReplicaSet |
| MongoDB | 1 또는 3 | 1대 Standalone, 3대 Replica Set |
| Kafka | 3 | KRaft combined |
| Spark | 3 | Master 2 + Worker 3 + ZooKeeper 3 |

서버 이름 끝의 숫자(`kafka-01`)가 노드 ID가 되므로 이름을 바꾸거나 YAML 중간에서 서버를 빼지 않는다. 노드 ID와 최초 Primary/Master 선택 순서가 달라지지 않게 기존 이름·순서를 유지하고 추가·삭제 시 클러스터 재구성 절차를 검토한다.

## 구성별 프록시 준비 스크립트

[scripts/setup-proxy.sh](scripts/setup-proxy.sh)는 아래 수동 명령들을 한 번에 실행한다. 계정·서버명·IP를 고정하지 않고 선택한 인벤토리와 대상 그룹을 읽는다. WSL의 기존 Ansible 가상환경을 활성화한 뒤 실행한다.

~~~bash
# 현재 인벤토리로 account1의 프록시를 준비한다. 필요하면 account4, spark 또는 all로 바꾼다.
bash /mnt/c/third_project/aws-platform/platform/scripts/setup-proxy.sh \
  --inventory /mnt/c/third_project/aws-platform/platform/inventory/hosts.current.yml \
  --limit account1
~~~

대상 확인·문법 검사 → SSH 확인 → 새 배스천의 Squid 설치와 접근 규칙 → 배스천 APT·방화벽 → 대상 서버의 APT·다운로드 검사 순서다. 대상 그룹에 배스천을 넣지 않아도 공용 배스천은 준비한다. 실패하면 다음 단계로 넘어가지 않는다.

계정별 서버 수·EC2 크기·배치를 바꾸고 생성부터 연결하려면 [배포 실행 안내](../../aws-infra/infra/scripts/README.md#비용별-구성-선택과-일괄-배포)의 deploy.ps1을 사용한다. 구성별 topology·traffic과 플랫폼 연결 설정을 선택하고, 현재 IP로 만든 hosts.구성이름.yml을 이 스크립트에 전달한다.

배스천의 기존 project_ec2 수동 규칙은 관리 블록으로 전환한다. 다른 Squid 규칙은 보존하고 문법·서비스 적용 실패 시 squid.conf를 복원한다. 기존 키 파일·가상환경·인벤토리 준비는 실행 전 조건이다. 상세 흐름은 [스크립트 라우팅](platform-routing/scripts/setup-proxy.sh.md)에 있다.

## 배스천 프록시로 설치 준비

Squid 설치와 프로젝트 VPC 허용이 끝난 배스천을 사용한다. 선택한 인벤토리의 `all.vars`에 `proxy_enabled: true`를 지정하면 `site.yml`이 첫 패키지 설치 전에 `prepare-proxy.yml`을 실행한다. 지정하지 않은 인벤토리는 프록시 준비를 생략한다.

- 실제 서버의 사설 IP는 `ip`, 배스천 공인 IP는 `public_ip`에 등록한다. 프록시 주소는 배스천의 `ip`와 포트로 계산하며, 배스천은 정확히 1대여야 한다.
- `inventory/group_vars/all/proxy.yml`에서 포트(기본 3128), 프로젝트 VPC CIDR과 원격 환경변수를 관리한다. `no_proxy`에는 localhost, 메타데이터, 인벤토리 호스트명과 내부 IP를 넣는다.
- 준비 대상은 Ubuntu 24.04 amd64의 기본 `ubuntu.sources`다. 공식 URI만 HTTPS로 바꾸고 변경 전 파일을 백업한다. Components, Suites, Signed-By와 다른 저장소 파일은 보존한다. 기본 파일이 없거나 처리하지 않은 HTTP 주소가 남으면 실패 원인을 표시한다.
- `/etc/apt/apt.conf.d/90-project-proxy`는 배스천에 DIRECT, 다른 서버에 배스천 프록시를 지정한다. 원격 root 작업의 HTTPS 연결·파일 다운로드를 확인하고 APT 목록을 갱신한다.
- 방화벽을 적용할 때 프록시 활성 배스천에만 지정 VPC CIDR의 TCP 3128을 추가 허용한다.

Windows에서는 PC의 WSL에서 실행한다. Ansible이 Windows 마운트의 설정 파일을 읽도록 `ANSIBLE_CONFIG`를 명시한다. 키는 Linux 사용자 소유의 `~/.ssh/project-key/`에 권한 600으로 둔다. deploy.ps1이 생성한 인벤토리는 목적지 계정의 키와 배스천 계정의 키를 구분해 ProxyCommand에 지정한다. 개인키 복사나 모든 계정의 공개키를 배스천에 등록하는 단계는 필요하지 않다. 수동 인벤토리는 각각의 인증 경로를 따로 맞춘다. 개인 키와 실제 인벤토리는 Git에 올리지 않는다.

```bash
# WSL에서 기존 플랫폼 디렉터리와 설치한 Ansible 환경을 사용한다.
cd /mnt/c/third_project/aws-platform/platform
export ANSIBLE_CONFIG=/mnt/c/third_project/aws-platform/platform/ansible.cfg

inventoryFile="$PWD/inventory/hosts.current.yml"

# 문법 및 SSH 검사: 서버 설정을 적용하지 않는다.
ansible-playbook -i "$inventoryFile" --syntax-check prepare-proxy.yml
ansible-playbook -i "$inventoryFile" --syntax-check site.yml
ansible 'bastion:spark-3' -i "$inventoryFile" -m ansible.builtin.ping

# 배스천과 account4의 spark-3에 프록시 준비만 적용한다.
ansible-playbook -i "$inventoryFile" prepare-proxy.yml --limit 'bastion:spark-3'

# 배스천 방화벽을 적용한 뒤 클라이언트의 새 요청을 검사한다.
ansible-playbook -i "$inventoryFile" site.yml --tags firewall --limit bastion
ansible-playbook -i "$inventoryFile" prepare-proxy.yml --tags proxy_verify --limit spark-3
```

검사가 성공하면 `ansible-playbook -i "$inventoryFile" prepare-proxy.yml`로 다른 서버의 프록시도 준비한다. `proxy_verify`는 APT 설정·목록을 변경하지 않고 HTTPS와 임시 파일 다운로드만 다시 검사한다. 태그로 역할만 선택하면 준비 단계가 생략될 수 있으므로 해당 서버에서 준비를 먼저 실행한다. 프록시 활성 상태의 일반 실행은 외부 접속 검사를 포함하므로 오프라인 재실행 시에는 기존 설치 상태와 실행 태그를 확인한다.

이 단계는 Kafka·Spark 등의 서비스를 설치하지 않는다. 서비스 설치 전에 Vault 값과 역할 그룹을 준비한다. 인프라의 `mongo`는 `mongodb`에 대응한다. `game`·`ad`는 프록시 준비 대상이지만 전용 설치 역할과 애플리케이션 방화벽 규칙이 없으므로 전체 `site.yml` 적용 전에 역할과 통신 규칙을 확정해야 한다.

## 현재 Spark 사설 통신

Master RPC 7077·내부 Master UI 8080, Worker RPC 7100, Driver 7078–7094·BlockManager 7079–7095, ZooKeeper 2181·2888·3888을 AWS traffic과 함께 맞춘다. 작업의 포트 재시도는 16회, Master·Worker 데몬은 0회다. Worker UI 8081은 원격 공개 SG 규칙이 없다. [Spark 설정 지도](platform-routing/roles/spark/README.md#프라이빗-서버의-통신-포트)와 [인프라 규칙 검사](../../aws-infra/docs/infra-routing/tests/README.md#spark-포트-범위)를 함께 확인한다.
