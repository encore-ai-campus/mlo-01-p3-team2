# Ubuntu 24.04 LTS 포팅 계획

| 항목 | 내용 |
|---|---|
| 상태 | **구현·검증 완료** (2026-10-08). 기본 OS를 Ubuntu 24.04 LTS로 전환함 (7장, 10장) |
| 작성일 | 2026-10-08 |
| 대상 | `platform/`의 Amazon Linux 2023(AL2023) 구현 전체를 Ubuntu 24.04 LTS에서도 동작하게 한다 |
| 관련 문서 | [설계](infra-automation-design.md), [구현 계획](implementation-plan.md) |

---

# 1. 목적과 범위

- **포팅이다.** 새 기능은 없다. AL2023에서 구현·검증된 범위(P0~P8: 공통 보안, 방화벽, MySQL, MongoDB, Kafka, ZooKeeper·Spark, Backend·Frontend, Monitoring, 통합)를 Ubuntu 24.04 LTS에서 같은 결과로 동작하게 한다.
- **둘 다 선택할 수 있어야 한다.** OS는 서버의 `ansible_facts['distribution']`(AL2023 = `Amazon`, Ubuntu = `Ubuntu`)로 자동 감지한다. 입력 YAML에 OS 항목을 새로 두지 않는다. 같은 인벤토리·같은 playbook으로 두 OS를 모두 구성하고, 한 클러스터에 두 OS를 섞는 구성은 지원 범위로 잡지 않는다(시험하지 않는다).
- **기본 OS 전환.** Ubuntu에서 AL2023과 같은 범위의 구현·검증이 끝나면 프로젝트의 기본 대상 OS를 Ubuntu 24.04 LTS로 바꾼다 (7장). 인프라 구현 메인 쪽에서 24.04로 확정했다.
- **범위 밖:** Ubuntu 24.04 이외 버전, ARM 아키텍처, AWS 환경 자체(AMI 선택은 시험용으로만 다룬다).

# 2. 시험 기준 이미지와 접속

- 이미지: Canonical 공식 Ubuntu 24.04 LTS, x86_64. 서울 리전에서 공개 SSM 파라미터 `/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id`로 찾는다. 2026-10-08 조사에 쓴 이미지는 `ubuntu-noble-24.04-amd64-server-20261004`(24.04.5 LTS, 커널 `7.0.0-1014-aws`)다.
- 접속 사용자는 `ec2-user`가 아니라 `ubuntu`다. 인벤토리의 `ansible_user`만 바꾸면 되며, role 코드는 접속 사용자 이름을 쓰지 않는다 (`common` 주석의 `ec2-user` 언급만 고친다).
- 시스템 Python은 3.12.3이고 `/usr/bin/python3`이다. `ansible.cfg`의 `interpreter_python = /usr/bin/python3`는 그대로 쓸 수 있고, 주석(AL2023의 3.9 고정 사유)만 두 OS 기준으로 고친다.

---

# 3. 사전 조사 결과 (실서버, 2026-10-08)

Ubuntu 24.04 서버 1대(`t3a.small`)를 띄워 기본 상태와 저장소·패키지를 확인했다. 구현은 하지 않았고 서버는 조사 직후 폐기했다. 아래는 AL2023과 달라서 포팅에서 다뤄야 하는 지점이다.

## 3.1 기본 환경

| 항목 | AL2023 (구현됨) | Ubuntu 24.04 (조사) | 포팅 영향 |
|---|---|---|---|
| 패키지 관리 | `dnf`, `yum_repository`, `rpm_key` | `apt`, 저장소는 `deb822_repository`와 `/etc/apt/keyrings` | 저장소 등록 task를 OS별로 분리 (4장) |
| sshd 서비스 이름 | `sshd` | `ssh` (별칭 `sshd.service`가 있으나 `is-active sshd`는 inactive). **소켓 활성화(`ssh.socket`)도 active** | 서비스 이름 변수, 반영 방식 시험 필요 (reload가 소켓 방식에서도 동작하는지) |
| sshd 기본값 | - | `Include sshd_config.d/*.conf`, cloud-init이 `60-cloudimg-settings.conf`(`PasswordAuthentication no`)를 둠. 유효 `PermitRootLogin`은 `without-password` | 기존 `00-hardening.conf`(첫 값 우선)로 `no`를 강제하고 `sshd -T`로 검증 |
| 시간 동기화 | `chronyd`, 기본이 Amazon Time Sync | `chrony`(서비스 이름 `chrony`), timesyncd는 inactive. **기본 시간원이 Ubuntu 풀(`ntp.ubuntu.com` 등)이고 Amazon Time Sync가 아님** | 설계의 시간원(`169.254.169.123`)을 맞추려면 설정 추가가 필요. `/etc/chrony/sources.d/amazon.sources`에 `server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4`를 두면 `^* 169.254.169.123`, `Leap status: Normal`, `NTPSynchronized=yes`가 되는 것을 확인함 |
| 방화벽 | `nftables`를 설치 | `nftables` 설치됨(`/usr/sbin/nft`), `nftables.service`는 disabled. `ufw`는 설치되고 서비스는 enabled지만 `ufw status`는 inactive, iptables 규칙 없음 | 전용 테이블(`inet infra_fw`) 방식은 그대로 가능. **`nftables.service`가 켜지면 `/etc/nftables.conf`의 `flush ruleset`이 우리 테이블을 지우므로 켜지지 않게 한다.** `ufw`는 비활성 상태를 검증하고 서비스는 꺼 둔다 |
| 기본 설치 | `rsync`, `logrotate`, `python3-apt` 등은 role이 설치 | `rsync`, `logrotate`, `curl`, `python3-apt`, `nftables`, `chrony`, `sudo`는 이미 설치됨. `acl`은 없음(쓰지 않음) | 설치할 패키지 목록 변수만 OS별로 |
| 자동 업데이트 | 없음 | `unattended-upgrades` enabled, `apt-daily*.timer` 동작, `needrestart` 설치(기본 설정은 대화형) | apt 잠금 충돌과 서비스 자동 재시작 위험 (5장 D2) |
| 보안 모듈 | SELinux 비활성(영향 없음) | **AppArmor 활성**(프로파일 122개, `mysqld`·`mysqlrouter`에 프로파일이 있음. `mongod`·Java는 없음) | MySQL·Router의 비표준 경로 사용 시 거부될 수 있음 (4.4) |
| journald | 디스크 저장 설정을 role이 추가 | `/var/log/journal`이 이미 있음(기본은 `Storage=auto`) | 기존 설정(`Storage=persistent`)을 그대로 적용 |
| 로그 읽기 그룹 | 서비스 로그별 그룹 | `adm` 그룹이 `/var/log`의 로그를 읽음 | `monitor`를 `adm`에 추가 (4.5) |
| 디스크 | 기본 8GiB | 기본 8GiB(사용 가능 6.8GiB, 사용 2.0GiB) | Spark 노드는 설치 용량을 확인 (U2) |
| `/sbin/nologin` | 있음 | 있음(`/usr/sbin/nologin`과 같은 파일) | 변경 없음 |
| sudo | `ec2-user` NOPASSWD | `ubuntu` 사용자가 비밀번호 없이 `sudo` 가능(`sudo -n` 확인) | 변경 없음 |

## 3.2 서비스 패키지

| 서비스 | AL2023 (구현됨) | Ubuntu 24.04 (조사) |
|---|---|---|
| MySQL 저장소 | `repo.mysql.com/yum/mysql-8.4-community/el/9/` (el9 RPM) | `repo.mysql.com/apt/ubuntu`, suite `noble`, 컴포넌트 **`mysql-8.4-lts`**와 **`mysql-tools`** (2025 GPG 키 `RPM-GPG-KEY-mysql-2025`를 `Signed-By`로 사용). Ubuntu 기본 저장소는 `mysql-server` 8.0이라 쓰지 않음 |
| MySQL 패키지 | `mysql-community-server`, `mysql-shell` | 같은 이름 `mysql-community-server`(8.4.11), `mysql-shell`(8.4.10) |
| MySQL Router | `mysql-router-community` | 같은 이름(8.4.10) |
| MySQL 서비스·경로 | 서비스 `mysqld`, 설정 `/etc/my.cnf` + `/etc/my.cnf.d/`, 소켓 `/var/lib/mysql/mysql.sock`, 오류 로그 `/var/log/mysqld.log` | 서비스 **`mysql`**, 설정 `/etc/mysql/my.cnf`(`conf.d`, `mysql.conf.d`를 포함), 소켓 `/var/run/mysqld/mysqld.sock`, 오류 로그 `/var/log/mysql/error.log`(`mysql:adm 0640`), 사용자 `mysql`(셸 `/bin/false`) |
| MySQL root 초기 인증 | 첫 시작 때 임시 비밀번호를 오류 로그에 기록, 만료 상태 | **`auth_socket`, 비밀번호 없음. 임시 비밀번호 없음.** 서버 안에서 `sudo mysql`로 접속됨 |
| 비밀번호 정책 | `validate_password` 적용(`MEDIUM`) | 조사한 설치 직후 `validate_password%` 변수가 없음(컴포넌트 미설치) |
| MongoDB 저장소 | `repo.mongodb.org/yum/amazon/2023/...` | `repo.mongodb.org/apt/ubuntu`, suite `noble/mongodb-org/8.0`, 컴포넌트 `multiverse` |
| MongoDB 패키지·경로 | `mongodb-org-server`, `mongodb-mongosh`, 사용자·그룹 `mongod`, 데이터 `/var/lib/mongo` | 같은 패키지 이름(8.0.32, mongosh 2.13.0). 사용자·그룹 **`mongodb`**, 데이터 **`/var/lib/mongodb`**, 로그 `/var/log/mongodb/mongod.log`, 서비스 `mongod`(설치 직후 disabled·inactive), 기본 `bindIp: 127.0.0.1`. logrotate·AppArmor 프로파일 없음 |
| Java | `java-17-amazon-corretto-headless` (AL2023 저장소) | Corretto는 **Amazon Corretto APT 저장소**(`apt.corretto.aws`, suite `stable`, 컴포넌트 `main`)에서 `java-17-amazon-corretto-jdk`(17.0.20)만 있고 headless 패키지는 없음. `JAVA_HOME`은 같은 `/usr/lib/jvm/java-17-amazon-corretto`. Ubuntu 자체 `openjdk-17-jre-headless`(17.0.20)도 있음 |
| Python (Spark 노드) | `python3.12` 패키지 설치, 시스템 3.9는 유지 | 시스템 `python3`가 이미 **3.12.3**. 추가 설치 불필요 |
| 저장소 도달성 | - | 위 저장소·키 URL 모두 HTTP 200 |

설치 시간은 MySQL(Server·Shell·Router)이 약 1분 5초였다.

조사에서 확인하지 못한 것: `ssh.socket` 환경에서 sshd 설정 반영 방식, `needrestart`의 비대화형 동작, MySQL InnoDB ReplicaSet·Router가 AppArmor 아래서 동작하는지, Ubuntu에서의 방화벽·모니터링 동작. 해당 단계에서 시험한다.

---

# 4. 영향 범위와 변경 방침

## 4.1 구조 (OS 분기 방식)

- 이미 `common`, `firewall`은 `vars/<배포판 소문자>.yml`(`amazon.yml`, `ubuntu.yml`)을 `include_vars`로 읽는다. **같은 방식을 나머지 role에도 확장한다**: 패키지 이름, 서비스 이름, 경로, 서비스 사용자·그룹처럼 값이 다른 것은 `vars/`로 분리한다.
- 저장소 등록처럼 task 자체가 다른 부분은 `tasks/repo-redhat.yml`, `tasks/repo-debian.yml`로 나누고 `ansible_facts['os_family'] | lower`(Amazon = `redhat`, Ubuntu = `debian`)로 `include_tasks`한다. `when: distribution == ...`을 곳곳에 흩뿌리지 않는다.
- 공통 규칙은 기존 방침을 그대로 따른다: 이미 설치된 패키지는 패키지 관리자를 거치지 않고(`package_facts`), 인터넷이 없어도 재실행이 통과해야 한다. apt에서는 키 파일(`/etc/apt/keyrings/...`)이 이미 있으면 내려받지 않고, 저장소 메타데이터 갱신(`apt update`)도 설치할 패키지가 있을 때만 한다.
- **AL2023 회귀 금지:** 모든 단계에서 AL2023 시험이 기존 결과(15대 `changed=0`)를 유지해야 한다.

## 4.2 role별 변경

| role | 변경 내용 |
|---|---|
| `common` | `vars/ubuntu.yml` 완성: `common_ssh_service: ssh`, `common_chrony_service: chrony`, 패키지. chrony 시간원 추가(`sources.d/amazon.sources`)와 검증(`^* 169.254.169.123`) 보강. `ssh.socket`에서 설정 반영 확인. `ec2-user` 주석 수정 |
| `firewall` | `vars/ubuntu.yml` 완성(`nftables`), `nftables.service` 비활성 유지 보장, `ufw` 비활성 검증·서비스 정지. 규칙 템플릿·복구 타이머·`infra-firewall.service`는 `/usr/sbin/nft`가 같아 그대로 쓸 수 있을 것으로 본다(시험으로 확인) |
| `java` | Ubuntu: Corretto APT 저장소 등록 + `java-17-amazon-corretto-jdk` (D1). `java_home`은 동일 |
| `mongodb` | `repo-debian.yml`(deb822), 서비스 사용자·그룹 `mongodb`, 데이터 경로 `/var/lib/mongodb`(템플릿의 `dbPath`를 변수로), keyfile 소유자 변수, `rpm_key`/`rpm -q` 대신 키 파일 존재 확인 |
| `mysql` | `repo-debian.yml`(컴포넌트 `mysql-8.4-lts`, `mysql-tools`), 서비스 `mysql`, 설정 경로(`/etc/mysql/mysql.conf.d/` 또는 `conf.d`에 `infra.cnf`), 소켓·오류 로그 경로 변수, **root 비밀번호 설정 흐름 분기**(Ubuntu: `auth_socket` root로 접속해 `ALTER USER`. 임시 비밀번호 조회 없음. 비밀번호가 만료 상태가 아니므로 Secondary의 `SET sql_log_bin` 제약이 없어 처리 순서를 다시 확인), 비밀번호 정책 컴포넌트 처리(D4), `Restart`·`활성화` 서비스 이름 변수. `/etc/my.cnf`의 `includedir` 줄 추가 task는 Debian 계열에서 불필요 |
| `backend` | `mysql` role의 `repo-debian.yml` 재사용. 패키지 이름 동일. Router AppArmor 프로파일과 bootstrap 디렉터리의 관계 확인 |
| `kafka`, `zookeeper` | tarball 설치는 OS 무관. 의존 `java` role만 바뀐다. `/sbin/nologin` 동일. 시험으로 확인 |
| `spark` | Python 패키지 설치 task를 Ubuntu에서는 건너뛰고(`spark_python_package` 없음) `spark_python: /usr/bin/python3`(3.12). 나머지 동일 |
| `monitoring` | 서비스 목록의 OS별 이름(`ssh`/`sshd`, `chrony`/`chronyd`, `mysql`/`mysqld`), 서비스 로그 경로(MySQL: `/var/log/mysql/error.log`), 로그 읽기 그룹(`adm`, `mongodb`/`mongod`), `service.sh`의 MySQL 소켓 경로를 변수로. 로그 파일이 이미 다른 logrotate 설정에 있으면 중복 오류가 나므로 확인(조사한 서버에는 MySQL·MongoDB용 logrotate 설정이 없었음) |
| `ansible.cfg`, `site.yml`, `tests/` | 주석 수정. 구조 변경 없음 |

## 4.3 변수 정리 (OS별로 갈라지는 값)

`service_ssh`, `service_chrony`, `service_mysql`, `service_mongod`(동일), `mysql_socket`, `mysql_error_log`, `mysql_config_dir`, `mongodb_user`·`mongodb_group`, `mongodb_data_dir`, `mongodb_log_group`, `monitor_extra_groups`, `java_package`, `spark_python_package`/`spark_python`, 저장소 URL·키·컴포넌트. 값은 role의 `vars/<배포판>.yml`에 두고 `defaults/`에는 기본값만 둔다.

## 4.4 MySQL·Router와 AppArmor

`mysqld`와 `mysqlrouter`는 AppArmor 프로파일로 접근 경로가 제한된다. 기본 경로(데이터 `/var/lib/mysql`, 로그 `/var/log/mysql/`, 설정 `/etc/mysql/`)는 허용되므로 우리 설정은 기본 경로를 벗어나지 않는다. `mysql_clone.so`처럼 플러그인 이름만 쓰는 설정은 영향이 없을 것으로 본다. 다만 Router의 `--bootstrap --directory`에 임의 경로(예: `/tmp/...`)를 쓰면 거부될 수 있으므로, 시험에서 `/etc/mysqlrouter` 기본 경로로 bootstrap한 결과를 기록한다 (AL2023 시험에서 쓴 `/tmp` 경로는 Ubuntu에서 그대로 쓸 수 없을 수 있다).

## 4.5 모니터링 읽기 권한

| 로그 | Ubuntu 읽기 방법 |
|---|---|
| MySQL `/var/log/mysql/error.log` (`mysql:adm 0640`) | `monitor`를 `adm`에 추가 |
| MongoDB `/var/log/mongodb/mongod.log` | `monitor`를 `mongodb` 그룹에 추가 (파일 권한은 설치 후 확인) |
| Kafka·ZooKeeper·Spark | 우리가 만드는 파일(전체 읽기) |
| 시스템 로그(journald) | `systemd-journal` 그룹 (그룹이 Ubuntu에도 있음) |

---

# 5. 결정 사항

각 항목에 권장안을 적었고, 달리 정하지 않아 **모두 권장안으로 구현했다** (D1~D5, D6은 7장).

| # | 결정 | 선택지 | 권장 |
|---|---|---|---|
| D1 | Ubuntu의 Java | (a) Amazon Corretto APT 저장소(`java-17-amazon-corretto-jdk`), (b) Ubuntu `openjdk-17-jre-headless` | **(a)**. 설계 문서의 "Corretto 17"과 일치하고 `JAVA_HOME`이 같다. 대신 저장소 하나가 늘고 JDK 전체가 설치된다 |
| D2 | `unattended-upgrades`·`needrestart` | (a) 기본 유지, (b) `needrestart`는 자동 재시작 안 함(list only)으로, `unattended-upgrades`는 유지, (c) `unattended-upgrades` 중지 | **(b)**. 서드파티 저장소(MySQL, MongoDB, Corretto)의 패키지는 기본 허용 출처가 아니라 자동 업데이트되지 않는다. 다만 OS 보안 업데이트 때 `needrestart`가 서비스를 자동으로 다시 시작하면 클러스터가 흔들릴 수 있으므로 끈다. 첫 부팅 직후 `apt` 잠금 충돌은 `apt`의 `lock_timeout`으로 흡수한다 |
| D3 | 시간 동기화 | (a) Amazon Time Sync만 쓰도록 Ubuntu 풀을 제거, (b) Amazon 소스를 추가하고 풀은 예비로 둠 | **(b)**. 설정 파일 수정 없이 `sources.d` 파일만 추가하며, 인터넷이 없으면 풀은 단순히 닿지 않을 뿐이다. 검증은 `^* 169.254.169.123`(선택됨)으로 한다 |
| D4 | Ubuntu MySQL의 비밀번호 정책 | (a) 컴포넌트를 설치(`INSTALL COMPONENT 'file://component_validate_password'`)해 AL2023과 같은 `MEDIUM` 정책 유지, (b) 설치하지 않음 | **(a)**. Vault 비밀번호 규칙과 동작을 두 OS에서 같게 한다 |
| D5 | MySQL 설정 파일 위치 | `/etc/mysql/mysql.conf.d/infra.cnf` vs `/etc/mysql/conf.d/infra.cnf` | `mysql.conf.d`(서버 설정 전용 폴더). 읽는 순서·덮어쓰기는 시험에서 `SHOW VARIABLES`로 확인한다 |
| D6 | 기본 OS 전환 방식 | 7장 참고 | 7장의 권장안 |

---

# 6. 단계

서버 시험은 AL2023과 같은 방식으로 한다(시험 서버를 띄우고 시험한 뒤 모두 종료하고, 남은 리소스가 없는지 조회로 확인한다). 각 단계는 **Ubuntu 시험 통과 + AL2023 회귀 통과**가 완료 기준이다. 단계별 시험 서버는 필요한 최소 구성으로 한다.

| 단계 | 내용 | 시험 구성 |
|---|---|---|
| U0 | 준비: 시험 환경(Ubuntu AMI, `ubuntu` 사용자 인벤토리), apt 공통 처리(`lock_timeout`, `needrestart` 설정, D2), OS별 `vars/` 구조 정리와 AL2023 회귀 | 서버 1대 |
| U1 | `common`, `firewall`: 서비스 이름, 시간 동기화(D3), `ssh.socket` 반영, `nftables.service`·`ufw` 처리, 복구 타이머(잠금 시험 포함) | Bastion 1 + 사설 서버 1 (P1과 같은 구성) |
| U2 | `java`, `kafka`, `zookeeper`, `spark`: Corretto(D1), 시스템 Python 3.12, tarball·커넥터 JAR, Spark 노드 디스크 용량, Master 이중화 | Kafka 3대 + Spark 3대(`t3a.medium`) |
| U3 | `mongodb`: 저장소, 사용자·경로, keyfile, 인증, Replica Set과 Standalone | 3대 + 1대 |
| U4 | `mysql`, `backend`: 저장소, 서비스·경로, root 인증 분기, 비밀번호 정책(D4), 계정 6종, ReplicaSet·Standalone, 전환(`setPrimaryInstance`), Router bootstrap(AppArmor 포함) | MySQL 2대 + Backend 1대 + 1대(Standalone) |
| U5 | `monitoring`: 서비스·로그 경로, 읽기 권한(그룹), logrotate 중복 확인, 수집·하트비트·정리 | 전체 구성에 포함 (U6과 함께) |
| U6 | 통합: 설계 구성 15대 한 번에 구축·재실행(`changed=0`), 인터넷 차단 후 재실행, 작은 구성, 방화벽 허용 관계 27개, Spark 커넥터 연동, 수동 장애 확인(MongoDB, Kafka, Spark). 마지막으로 **AL2023 전체 회귀** | 15대 + 작은 구성 2대 (Ubuntu), AL2023 15대 |
| U7 | 문서 갱신과 기본 OS 전환 (7장) | - |

의존: U0 → U1 → (U2, U3, U4 병렬 가능) → U5 → U6 → U7. U1이 통과하기 전에는 다른 단계를 시작하지 않는다(공통 보안·방화벽이 모든 서버의 전제).

## 예상 비용

U0~U5의 단계별 시험은 소규모 서버 몇 대를 짧게 쓰므로 합계 약 $1이고, U6의 Ubuntu 15대와 AL2023 회귀 15대가 약 $1.5씩이다. 전체 약 $4 안팎으로 추정했다. 실제로는 서버를 약 3시간(최대 17대) + 클린 구축·회귀 30대 약 1시간 쓴 합계로 약 $2.5~3로 추정한다. 실제 청구 금액은 Cost Explorer가 조직 정책으로 막혀 있어 조회하지 못한다.

# 7. 기본 OS 전환 (완료)

저장소에는 `default_os` 같은 설정 변수가 **없다.** OS는 서버에서 자동 감지하므로 코드에는 "기본 OS"가 존재하지 않고, 기본 OS는 문서·예시·시험 기준에만 나타난다. 지시에 따라 아래를 Ubuntu 24.04 LTS 기준으로 바꿨다.

- 설계 문서 3장의 OS 항목, 11장 소프트웨어 버전 표(두 OS의 설치 출처), 입력 예시의 `ansible_user: ubuntu`
- `platform/README.md`(지원 OS, 접속 사용자), `inventory/hosts.example.yml`
- 구현 계획 4장(기본 시험 OS는 Ubuntu, AL2023은 회귀 시험으로 유지), `docs/README.md`

AL2023은 "지원(회귀 시험 유지)"로 남는다. 코드에는 새 변수를 추가하지 않았다. 메인 인프라 쪽에서 `default_os`라는 실제 설정 항목을 따로 두고 이 저장소가 그 값을 참조해야 한다면, 항목의 위치와 형식을 알려 주면 반영한다.

---

# 8. 위험

| 위험 | 대응 |
|---|---|
| 첫 부팅 직후 `unattended-upgrades`/`apt-daily`가 dpkg 잠금을 잡아 첫 설치가 실패 | `apt`의 `lock_timeout`, 필요하면 첫 task에서 잠금 해제 대기 |
| `needrestart`가 설치 중 서비스를 자동으로 다시 시작 | D2의 설정, 시험에서 서비스 재시작 이력 확인 |
| `nftables.service`가 켜져 우리 테이블이 지워짐 | 비활성 유지 + 검증 항목 추가 |
| `ssh.socket` 환경에서 sshd 설정이 반영되지 않음 | U1에서 유효 설정(`sshd -T`)과 새 연결로 확인 |
| MySQL root가 `auth_socket`이라 기존 비밀번호 설정 흐름이 맞지 않음 | U4에서 분기 구현, ReplicaSet·재실행 시험 |
| AppArmor가 MySQL·Router의 경로를 거부 | 기본 경로 사용, 거부 로그(`dmesg`·`journalctl`)를 시험 항목에 포함 |
| 두 OS를 모두 유지하면서 AL2023이 깨짐 | 모든 단계에 AL2023 회귀, 마지막에 전체 회귀 |
| Ubuntu 저장소의 패키지 버전이 AL2023과 달라 행동이 다름(예: Router 8.4.10 vs Server 8.4.11) | 시험에서 기록, 필요하면 버전 고정 |

# 9. 완료 기준

1. Ubuntu 24.04에서 설계 구성 15대의 구축과 재실행(`changed=0`), 인터넷 차단 후 재실행이 통과한다.
2. 작은 구성(MySQL 1대 + MongoDB 1대)이 통과한다.
3. 방화벽 허용 관계, Spark 커넥터 연동, 수동 장애 확인이 AL2023과 같은 결과다.
4. AL2023 전체 회귀가 통과한다.
5. 설계 문서·구현 계획·`platform/README.md`가 두 OS 기준으로 갱신되고, 기본 OS가 Ubuntu 24.04 LTS로 바뀐다.

---

# 10. 구현 결과 (2026-10-08)

## 10.1 구현 요약

- **`roles/pkg`(신규)**: 패키지 설치(`install.yml`)와 apt 저장소 등록(`apt_repo.yml`)을 한 곳에 모았다. 이미 설치된 패키지는 패키지 관리자를 거치지 않고(dnf/apt 공통), apt는 `lock_timeout`과 `needrestart` 목록 모드로 설치하며 저장소를 방금 추가했을 수 있어 설치할 때마다 목록을 갱신한다. 키는 `/etc/apt/keyrings`에 파일로 두고 `Signed-By`로 지정한다(`deb822_repository`는 대상 서버에 `python3-debian`이 필요해 쓰지 않았다). 기존 8곳의 설치 코드를 이것으로 교체했다.
- **OS별 `vars/<배포판>.yml`**: `common`, `firewall`(기존) + `java`, `mongodb`, `mysql`, `spark`, `monitoring`. 저장소 등록은 `repo-redhat.yml`/`repo-debian.yml`로 분리했다.
- **`common`(Ubuntu)**: 서비스 이름 `ssh`/`chrony`, `needrestart`는 목록만(D2), chrony에 Amazon Time Sync 소스 추가(D3).
- **`firewall`(Ubuntu)**: `nftables.service`는 비활성 유지, `ufw` 비활성 확인과 서비스 비활성화.
- **`java`(Ubuntu)**: Corretto APT 저장소의 `java-17-amazon-corretto-jdk`(D1).
- **`mongodb`(Ubuntu)**: APT 저장소, 사용자·그룹 `mongodb`, 데이터 `/var/lib/mongodb`, **커널 호환 단계**(10.2).
- **`mysql`(Ubuntu)**: APT 저장소(`mysql-8.4-lts`, `mysql-tools`), 서비스 `mysql`, 설정 `/etc/mysql/mysql.conf.d/infra.cnf`, 소켓 `/var/run/mysqld/mysqld.sock`, root가 `auth_socket`이므로 소켓으로 접속해 비밀번호 방식으로 바꾸는 흐름, 비밀번호 정책 컴포넌트 설치(D4). 기존 임시 비밀번호 흐름은 `root-password-redhat.yml`로 분리했다.
- **`spark`(Ubuntu)**: 시스템 `python3`(3.12)를 쓰므로 Python 패키지 설치가 없다.
- **`monitoring`(Ubuntu)**: 서비스 이름, MySQL 로그 `/var/log/mysql/`(그룹 `adm`로 읽기), MongoDB 로그 `0640`으로 맞춤, MongoDB 그룹 `mongodb`.

## 10.2 조사 때 예상하지 못했던 것 (시험에서 발견)

| 발견 | 대응 |
|---|---|
| **MongoDB 8.0.32가 Linux 커널 6.19 이상에서 시작을 거부**한다(SERVER-121912, 수정 버전 없음). Ubuntu 24.04 AWS 이미지는 커널 `7.0.0-1014-aws`(HWE)라 `mongod`가 시작하지 않는다 | `mongodb` role(Ubuntu)이 커널이 6.19 이상이면 `linux-aws-lts-24.04`(GA 6.8)를 설치하고, HWE 메타 패키지와 실행 중인 커널 패키지를 지운 뒤(`noninteractive`로 실행 중 커널 제거 확인을 통과) 재부팅한다. 커널이 기준 미만이면 아무것도 하지 않는다. 재실행은 변경 없음 |
| `get_url`은 대상 파일이 이미 있어도 갱신 확인 요청을 보내 인터넷이 없으면 실패한다 | 키 파일이 있으면 `get_url`을 실행하지 않는다 (`stat`로 확인) |
| 첫 번째 미러(`dlcdn`)의 일시적 읽기 시간 초과 한 번으로 느린 `archive`로 넘어가 Spark 내려받기가 사실상 멈춘다 | 미러를 `dlcdn` → `downloads.apache.org` → `archive`의 3단으로 하고 읽기 제한 시간을 60초로 올렸다 (Kafka, ZooKeeper, Spark 공통. AL2023에도 적용) |
| Ubuntu의 `mongod.log`가 `0600`으로 만들어져 `monitor`(그룹 `mongodb`)가 읽을 수 없다 | 서비스 umask를 바꾸지 않고(데이터 파일까지 열릴 수 있다) 로그 파일만 `0640`으로 맞췄다. 데이터 파일이 그룹에 노출되지 않는 것을 확인했다. `copytruncate` 회전은 원본 파일을 유지해 권한이 유지된다 |
| Router를 `/tmp` 아래에 bootstrap하면 AppArmor(`/usr/bin/mysqlrouter` 프로파일)가 거부한다 | 기본 경로(`/etc/mysqlrouter`)로 bootstrap하고 `mysqlrouter` 서비스를 쓴다 (설계 문서 14장에 기록) |
| 시험 스크립트에서 `ssh ... 'bash -s'`로 보낸 스크립트를 `apt-get`이 표준입력으로 읽어 갔다 | 시험 방식의 문제이며 role 코드는 해당 없음 (apt는 표준입력을 쓰지 않는다) |

조사에서 계획했지만 문제가 없었던 것: `ssh.socket` 환경에서의 sshd 반영(`ssh` 서비스 reload로 정상), MySQL 설정 파일 순서(Oracle의 `mysqld.cnf`는 경로 설정만 있어 `infra.cnf`와 충돌이 없었다), AppArmor가 `mysqld`를 막는 일(없었다. 거부 기록은 Ubuntu 자체 구성요소 1건뿐), `nftables.service`(비활성 유지로 해결), `ufw`(비활성).

## 10.3 검증 결과

- **Ubuntu 24.04 LTS, 설계 구성 15대(Bastion 경유, 새 서버)**: 한 번의 실행으로 구축 성공(실패 0), 재실행은 15대 모두 변경 없음(`changed=0`).
- **인터넷 차단 후 재실행(Ubuntu 15대, AL2023 15대)**: 모두 `failed=0`, `changed=0`.
- **작은 구성(MySQL 1대 + MongoDB 1대, Ubuntu)**: 구축 통과, 재실행과 인터넷 차단 후 재실행 모두 `changed=0`.
- **방화벽(Ubuntu)**: 실제 연결 30개를 시험해 모두 설계와 같았다. 복구 타이머 시험(일부러 SSH를 막는 규칙)도 통과: Ansible이 접속을 잃고, 타이머가 테이블을 지워 접속이 되살아났으며, 정식 규칙 파일은 오염되지 않았다.
- **Spark 커넥터 연동(Ubuntu)**: Kafka 100건 → Spark → MySQL, MongoDB에 쓰고 다시 읽어 건수 일치, MySQL 2대에 복제됨.
- **MySQL(Ubuntu)**: ReplicaSet, 수동 Primary 전환과 복귀, Secondary 재부팅 후 재합류. Router는 `router` 전용 계정으로 기본 경로에서 bootstrap, 6446은 Primary, 6447은 Secondary로 연결.
- **수동 장애 확인(Ubuntu)**: MongoDB Primary 중지 → 약 25초 안에 새 Primary와 쓰기, Kafka 브로커 1대 중지 → `acks=all` produce·consume, Spark 활성 Master 중지 → 35초 만에 Standby 승격과 작업 제출. 모두 Monitoring이 감지했다.
- **AL2023 회귀(새 서버 15대)**: 한 번의 실행으로 구축 성공, 인터넷 차단 후 재실행 `changed=0`.

## 10.4 확인하지 못한 것

- Ubuntu의 `needrestart`가 비대화형 설치 중 서비스를 실제로 다시 시작하는지(목록 모드로 설정했고, 시험 중 의도하지 않은 재시작은 없었다).
- Ubuntu의 `unattended-upgrades`가 운영 중 OS 보안 업데이트로 서비스에 미치는 영향 (서드파티 저장소 패키지는 기본 허용 출처가 아니라 자동으로 올라가지 않는다).
- `linux-aws-lts-24.04`가 앞으로 받을 6.8 커널 업데이트 뒤의 재부팅 시점 (자동 재부팅은 켜지 않았다).
- MongoDB가 새 커널을 지원하는 버전이 나왔을 때 커널 교체 단계를 빼는 시점.
- 두 OS를 한 클러스터에 섞는 구성 (지원 범위가 아니다).
- 서버 수십 대 규모, 수집 서버 재부팅 뒤 동작 (AL2023 때와 같음).

---

# 별도 참고: 현재 구성 안내 — 2026-10-10

이 아래 내용은 후속 문서 정리에서 추가한 현재 구성 안내이며, 위 원문 작성자의 작업·완료·시험 기록에 포함되지 않는다.

이 문서의 구현·검증 완료 상태와 2026-10-08 서버 시험은 당시 포팅 결과다. 이번 문서 갱신은 로컬 코드·라우팅 문서의 반영이며 새 AWS 배포나 외부 호환성 시험을 수행한 결과가 아니다.

포팅 후 추가된 prepare-proxy.yml과 bootstrap-proxy.yml은 Ubuntu 24.04 amd64 기본 이미지에 한정한다. 기존 서비스 역할의 AL2023 지원을 이 프록시 준비에도 적용할 수 있다고 해석하지 않는다. 현재 NAT 0개 구성에서는 Bastion의 Squid를 설치하고 HTTPS APT·원격 다운로드를 준비한 후 역할을 설치한다. 생성된 hosts.current.yml을 명시하는 실행·Vault 절차는 [플랫폼 README](../platform/README.md)를 따른다.

현재 Spark 통신은 Master 7077·8080, Worker 7100, Driver 7078–7094·BlockManager 7079–7095, ZooKeeper 2181·2888·3888이다. zookeeper만 실행해 성공했더라도 Spark 설치는 별도이므로 두 역할을 함께 선택한다. AWS 규칙 적용과 서비스 설치를 각각 확인한다. [Spark 설정 지도](../platform/docs/platform-routing/roles/spark/README.md), [준비 플레이북 지도](../platform/docs/platform-routing/prepare-proxy.yml.md)를 참고한다.
