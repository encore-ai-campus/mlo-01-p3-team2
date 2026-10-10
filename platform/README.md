# platform

막 생성된 Ubuntu 24.04 LTS(기본) 또는 Amazon Linux 2023 VM에 Ansible로 보안 설정과 역할별 구축을 한다. OS는 서버에서 자동 감지한다. 설계와 결정 사항은 [docs/platform/infra-automation-design.md](../docs/platform/infra-automation-design.md)에 있다.

## 구현 상태

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

```bash
mamba activate claude
pip install -r requirements.txt

cp inventory/hosts.example.yml inventory/hosts.yml   # 실제 서버 IP와 팀원 공개키로 수정

ansible-playbook site.yml                 # 전체
ansible-playbook site.yml --limit mysql   # 특정 역할(그룹)만
ansible-playbook site.yml --tags verify   # 검증만
```

- 개발자 PC에서 실행한다. Bastion은 공인 IP로 접속하고, 나머지 서버는 Bastion을 경유한다. Bastion이 없는 인벤토리는 사설 IP로 직접 접속한다.
- Secret(DB 비밀번호 등)은 `inventory/hosts.yml`에 쓰지 않고 Ansible Vault에 둔다. 아래 "Secret(Vault)"를 참고한다.

## 알아 둘 것

- 지원 OS는 Ubuntu 24.04 LTS(기본)와 Amazon Linux 2023이다. 접속 사용자는 Ubuntu는 `ubuntu`, AL2023은 `ec2-user`다(인벤토리 `ansible_user`). Ubuntu에서 MongoDB 서버는 첫 실행 때 커널을 GA 6.8로 바꾸고 재부팅한다.

- 서버를 지우고 다시 만들 때 사설 IP가 같으면 SSH가 `Host key verification failed`로 거부된다. 개발자 PC에서 `ssh-keygen -R <IP>`로 옛 항목을 지운다.
- 구축을 마친 뒤 임시 NAT를 제거해도 재실행할 수 있다(이미 설치된 패키지, tarball, JAR, GPG 키는 내려받지 않는다).
- 구축 후 Spark와 Kafka·MongoDB·MySQL의 연동은 `tests/spark_integration.py`로 확인할 수 있다 (Spark 노드에서 `spark-submit`으로 제출, 환경변수는 파일 맨 위 설명 참고).

## Secret(Vault)

Secret은 `inventory/group_vars/all/vault.yml`에 두고 암호화한다. 형식과 값을 채우는 방법은 [vault.example.yml](inventory/group_vars/all/vault.example.yml)에 적혀 있다.

```bash
echo '<Vault 비밀번호>' > .vault_pass                      # 저장소에 올라가지 않는다 (platform/.gitignore)
cp inventory/group_vars/all/vault.example.yml inventory/group_vars/all/vault.yml   # 값을 채운다
ansible-vault encrypt --vault-password-file .vault_pass inventory/group_vars/all/vault.yml
export ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass            # 실행하는 셸마다 설정한다
```

- 암호화한 `vault.yml`이 있으면 모든 실행에서 비밀번호 파일이 필요하다 (Secret을 쓰지 않는 단계도 같다).
- `vault.yml`(암호화한 것 포함), `.vault_pass`, `inventory/hosts.yml`은 저장소에 올리지 않는다(`platform/.gitignore`). 운영자가 각자 만든다.

## 가능한 구성

서버 대수는 프로그램이 검증하지 않는다. 아래 구성만 지원하므로 개발자가 유의한다. 모드는 대수에서 자동으로 정해진다.

| 역할 | 가능한 대수 | 모드 |
|---|---|---|
| Bastion, Frontend, Monitoring, Backend | 1 | - |
| MySQL | 1 또는 2 | 1대 Standalone, 2대 InnoDB ReplicaSet |
| MongoDB | 1 또는 3 | 1대 Standalone, 3대 Replica Set |
| Kafka | 3 | KRaft combined |
| Spark | 3 | Master 2 + Worker 3 + ZooKeeper 3 |

서버 이름 끝의 숫자(`kafka-01`)가 노드 ID가 되므로 이름을 바꾸거나 YAML 중간에서 서버를 빼지 않는다. 서버는 끝에만 추가한다.
