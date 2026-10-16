> Status: Approved  
> 기준 문서: [infra-automation-design.md](infra-automation-design.md)  
> 목적: 인프라 자동화(`platform/`)를 어떤 순서로, 어떤 완료 기준으로 구현할지 정의하는 계획 문서

> 아래 P0~P8은 당시 구현·서버 시험의 기록이다. 현재 MySQL은 3~9대의 InnoDB Cluster와 앱 서버의 로컬 Router를 사용하며, 이전 ReplicaSet·Standalone 완료 기록은 새 Cluster의 원격 검증 결과가 아니다. 현재 설치 조건과 실행 방법은 [플랫폼 README](../platform/README.md)와 [라우팅 문서](../platform/docs/ROUTING-README.md)를 따른다.

---

# 1. 구현 원칙

- 설계 문서의 실행 순서를 따른다: 공통 보안 → 방화벽 → 서비스 → Backend/Frontend → Monitoring → 통합.
- 역할(role) 하나는 독립적으로 실행하고 검증할 수 있어야 한다 (`--limit`, `--tags`).
- 각 단계는 **자기 검증을 포함**한다. 설치가 끝난 것이 아니라 검증이 통과해야 완료다.
- 가장 작은 구성(VM 한 대)에서 먼저 확인하고 구성을 늘린다.
- 구현 중 확인된 사실은 설계 문서의 14장 "구현하며 확인할 것"에 반영하고, 구현 상태는 [platform/README.md](../platform/README.md)의 표에 반영한다.

---

# 2. 단계별 계획

| 단계 | 내용 | 선행 | 상태 |
|---|---|---|---|
| P0 | 골격 + 공통 보안 | - | 구현 완료, 서버 1대(`t3a.nano`)에서 검증 완료 |
| P1 | 방화벽 | P0 | 구현 완료, 서버 2대(Bastion + 사설 서버)에서 검증 완료 |
| P2 | MySQL | P1 | 구현 완료, 서버 2대(ReplicaSet)와 1대(Standalone)에서 검증 완료 |
| P3 | MongoDB | P1 | 구현 완료, 서버 3대(Replica Set)와 1대(Standalone)에서 검증 완료 |
| P4 | Kafka | P1 | 구현 완료, 서버 3대에서 검증 완료 |
| P5 | ZooKeeper + Spark | P1 | 구현 완료, 서버 3대에서 검증 완료 |
| P6 | Backend, Frontend | P2 | 구현 완료, 서버 4대에서 검증 완료 (Router 전용 계정 반영, 2026-10-06 서버 3대에서 검증) |
| P7 | Monitoring | P2~P5 | 구현 완료, 서버 15대(설계 구성 전체)에서 검증 완료 |
| P8 | 통합과 멱등성 | P1~P7 | 완료, 설계 구성 15대와 작은 구성 2대에서 검증 (2026-10-06) |

P2~P5는 서로 의존하지 않는다. 설계 문서의 실행 순서(MySQL → MongoDB → Kafka → Spark)대로 구현하되, 막히는 단계가 있으면 건너뛰어도 된다.

## P0. 골격 + 공통 보안

- 산출물: `platform/` 골격(`ansible.cfg`, `site.yml`, `inventory/`), `roles/common`
- 내용: sshd 보안 설정, 팀원 계정과 sudo, 시간 동기화와 UTC, 검증
- 검증 결과 (AL2023 `t3a.nano` 1대, 2026-10-05)
  - 첫 실행에서 검증이 모두 통과했고, 재실행은 변경 없음(`changed=0`)이었다.
  - sshd: `sshd_config.d`의 drop-in이 적용되었다 (`Include` 앞에 활성 지시문이 없어 `00-` 파일이 우선). 비밀번호·root 접속은 거부되고, 팀원 계정의 키 접속과 비밀번호 없는 sudo가 동작한다.
  - 시간: chrony 기본 설정이 Amazon Time Sync를 쓰고, 동기화와 UTC가 확인되었다.
  - Bastion 분기(`AllowTcpForwarding`)와 Bastion 경유 접속(ProxyCommand)이 동작했다. 경유 접속은 Bastion 자신의 loopback을 대상으로 한 시험이라 별도 서버 간 경로는 확인되지 않았다.
  - `raw` 부트스트랩은 필요 없었다 (시스템 Python 3.9가 기본 설치).
  - 작은 VM에서 `dnf` 모듈이 메모리 부족으로 종료되어, 이미 설치된 패키지는 패키지 관리자를 거치지 않도록 고쳤다.
  - 이 서버에는 `nftables`가 없고 `rsync`는 기본 설치되어 있다.

## P1. 방화벽

- 산출물: `roles/firewall`, 역할 간 허용 관계 데이터(`roles/firewall/vars/rules.yml`), nftables 규칙 템플릿
- 내용
  - 허용 관계를 한 곳의 데이터로 정의하고, 템플릿이 그룹을 실제 IP로 치환해 전용 테이블을 만든다.
  - 파일을 `nft -f`로 원자적으로 교체하고, 부팅 때 같은 파일을 로드한다.
  - 적용 순서: Bastion SSH 허용 → 연결 검증 → default deny.
  - 포트 목록이 확정되기 전에는 허용된 출처의 **모든 포트**를 연다. 단 SSH(22)는 제외하고 Bastion·Monitoring 규칙으로만 허용한다. Frontend는 외부에 80/443만 연다. 포트가 확정되면 규칙 데이터만 고친다.
- 검증: 규칙 적용 확인, 허용 출처에서 접속 성공, 허용되지 않은 출처에서 접속 거부, 서비스 포트가 열린 출처에서도 SSH는 거부(Bastion·Monitoring 제외), 재실행 후에도 SSH 유지
- 주의: 잠김 위험이 가장 큰 단계이므로 서버 한 대에서 먼저 확인한다.
- 주의: `nftables`는 AL2023 기본 이미지에 없어 설치가 필요하다. `t3a.nano`(RAM 약 418MiB)에서는 `dnf`가 메모리 부족으로 종료되므로, 이 단계는 1GiB 이상의 VM에서 확인한다. 인터넷이 없는 서버에서는 `dnf`가 오래 멈추므로 임시 NAT가 연결되어 있어야 한다.
- 구현: 규칙은 후보 파일로 만들어 `nft -c`로 문법을 검사하고, 복구 타이머를 예약한 뒤 원자적으로 적용한다. 새 SSH 연결이 확인되면 타이머를 해제하고 후보 파일을 정식 파일로 교체한다 (접속이 안 되는 규칙이 재부팅 후에 되살아나지 않게 하기 위함). 부팅 때는 `infra-firewall.service`가 정식 파일을 로드한다.
- 검증 결과 (AL2023 `t3a.micro` 2대, 2026-10-05)
  - 한 대(Bastion 없음): 설치·적용·재실행(`changed=0`)이 통과했고, 외부 출처에서 80은 열리고 443은 방화벽을 통과했으며 8080과 3306은 차단되었다.
  - 접속이 막히는 규칙을 일부러 적용했을 때 새 연결 확인이 실패했고, 복구 타이머가 방화벽 테이블을 지워 약 2분 뒤 접속이 복구되었다. 정식 파일에는 SSH 규칙이 남아 있었다.
  - Bastion + 사설 서버: Bastion 경유로 적용되었고, 사설 서버는 Bastion의 사설 IP에서 오는 SSH만 허용하며 낯선 출처의 22·80·8080은 차단되었다. 재부팅 후 서비스가 규칙을 로드했고 재실행은 변경 없음이었다.
  - 확인하지 못한 것: Bastion 출처에서 SSH 외 모든 포트가 열리는지(보안 그룹이 막아 실제 연결로는 확인 불가), 여러 클러스터 서버 사이의 규칙.

## P2. MySQL

- 산출물: `roles/mysql`
- 내용
  - MySQL Yum 저장소 설치와 GPG 키 처리, Server·Shell 설치, root 임시 비밀번호 변경
  - 계정 6종(`root`, `dev`, `replication`, `monitor`, `failover`, `router`)과 접속 허용 출처 (`router`는 P6 결정으로 추가)
  - 서버 RAM에서 `innodb_buffer_pool_size` 계산, 사설 IP에 바인딩
  - 대수에서 모드 결정: 1대 Standalone, 2대 InnoDB ReplicaSet (MySQL Shell로 구성)
- 검증: `SELECT 1`, 복제 상태
- 확인할 것: GPG 키 경로, 8.4 인증 플러그인과 클라이언트 호환, `failover` 계정의 필요 권한
- 구현 메모
  - AL2023 저장소에는 `python3-PyMySQL`이 없어 Ansible의 MySQL 모듈 대신 `mysql` 클라이언트와 MySQL Shell 명령을 쓴다. 비밀번호는 명령줄이 아니라 환경 변수와 표준 입력으로 넘기고, 출력은 숨긴다(`mysql_no_log`, 문제를 찾을 때만 끈다).
  - 저장소 파일은 릴리스 RPM 대신 직접 만든다(`yum_repository`). GPG 키는 2025 키를 등록하므로 키 경로 수정이 필요 없다.
  - 두 번째 노드는 root 비밀번호와 `failover` 계정을 복제 없이(`sql_log_bin=0`) 만들고, Primary에서 `clone`으로 복구한다 (불일치한 GTID가 생기지 않게 하기 위함).
  - `replication` 계정은 설계대로 만들지만, AdminAPI가 복제용 계정을 자동으로 만들므로 쓰이지 않을 수 있다.
  - `monitor` 계정은 `localhost`에서만 쓴다.
- 서버 시험에 필요한 것: 인터넷이 되는 서버(저장소 등록), 2GiB 이상의 VM(`t3a.small` 이상), 노드 사이 통신.
- 검증 결과 (AL2023 `t3a.small`, MySQL 8.4.11, 2026-10-05)
  - ReplicaSet(2대): 구성과 검증이 통과했고, 재실행은 변경 없음(`changed=0`)이었다. Primary에서 `dev`로 쓴 데이터가 Secondary에서 읽혔고, Secondary에서의 쓰기는 읽기 전용 오류로 거부되었다. Secondary를 재부팅하자 ReplicaSet에 자동으로 다시 합류했다(`AVAILABLE`, 두 노드 `ONLINE`).
  - `failover` 계정으로 Primary 전환(`setPrimaryInstance`)과 복귀가 동작해 권한이 충분함을 확인했다.
  - Standalone(1대): 구성과 검증이 통과했고, 재실행은 변경 없음이었다.
  - 계정은 기본 인증 플러그인 `caching_sha2_password`로 만들어졌고, 비밀번호 정책(`validate_password`)은 `MEDIUM`이 적용되어 있다.
  - Secondary의 계정은 합류할 때 Primary에서 복제되어 왔다. AdminAPI가 복제용 계정(`mysql_innodb_rs_*`)을 자동으로 만들어, 설계의 `replication` 계정은 쓰이지 않는다.
  - 시험 중 고친 것: 비밀번호가 만료된 세션에서는 `SET sql_log_bin`을 쓸 수 없어 Secondary는 변경 뒤 `RESET BINARY LOGS AND GTIDS`로 정리한다. `addInstance`는 접속 정보를 문자열로만 받아 비밀번호를 퍼센트 인코딩한 URI로 넘긴다. 합류한 노드는 읽기 전용이라 계정 단계를 건너뛴다.
  - 확인하지 못한 것: 첫 번째 서버가 Primary가 아닌 상태(Primary 전환 후)에서의 재실행(지원하지 않는다. 재실행 전에 Primary를 첫 번째 서버로 되돌린다).
- 검토 반영 (2026-10-05)
  - `dev` 권한: 전역(`*.*`)으로 부여하되 시스템 스키마 `mysql`, `sys`는 부분 revoke(`partial_revokes = ON`)로 뺀다. 계정·권한 테이블을 읽거나 고칠 수 없는 것을 서버에서 확인했다(`mysql.user` 조회·수정, `sys` 생성 모두 거부, 업무 DB의 생성·쓰기·삭제는 성공). `performance_schema`는 root도 revoke할 수 없어 제외했고, `dev`는 그 안에서 `setup_*` 테이블 UPDATE 정도만 할 수 있다. 검증 단계에 이 차단 확인을 추가했다.
  - 계정 단계의 멱등성: 계정 SQL이 `ALTER USER`(비밀번호 재설정)를 포함해 실행할 때마다 DB가 바뀌므로, 마지막으로 적용한 SQL의 해시(`/etc/mysql-infra-accounts.sha256`)를 서버에 남기고 같으면 건너뛴다. 실제로 적용했을 때만 변경으로 보고한다. 재실행은 `changed=0`이다. DB를 직접 바꾼 경우 이 파일을 지우고 재실행하면 되돌린다.
  - `addInstance` 연결 문자열: 비밀번호의 `/`가 인코딩되지 않던 문제를 고쳤다(`urlencode` 뒤에 `/`를 `%2F`로 바꾼다).
  - 추가 확인: `partial_revokes` 켠 상태에서 ReplicaSet 구성, 재실행, `setPrimaryInstance` 전환과 복귀가 동작한다.

## P3. MongoDB

- 산출물: `roles/mongodb`
- 내용: MongoDB Yum 저장소와 설치, keyfile 배포와 인증 활성화, 계정(`root`, `dev`, `monitor`), RAM 기반 캐시 크기, 대수에서 모드 결정(1대 Standalone, 3대 Replica Set), 초기 멤버 구성
- 검증: `dev` 계정으로 쓰기·읽기 확인. 3대 Replica Set이면 `rs.status()`의 멤버 상태(PRIMARY 1, SECONDARY 2)도 확인
- 확인할 것: 인증 활성화와 keyfile 적용 순서
- 구현 메모
  - 인증은 처음부터 켠다(`authorization: enabled`, Replica Set이면 `keyFile`). 첫 번째 서버에서 localhost exception으로 Replica Set 초기화(`replSetInitiate`)와 `root` 생성을 하고, 이어서 `root`로 `dev`(`readWriteAnyDatabase`)와 `monitor`(`clusterMonitor`)를 만든다. keyfile은 Vault 값을 `0400`, `mongod` 소유로 배포한다.
  - 비밀번호는 명령줄이 아니라 환경 변수로 `mongosh` 스크립트(표준 입력)에 넘기고 출력은 숨긴다(`mongodb_no_log`).
  - 계정 단계는 실제 상태를 확인한다. 계정이 없으면 만들고, 비밀번호(로그인해 확인)나 권한이 다를 때만 고친다.
  - 접속은 Replica Set 주소(`replicaSet=infra`)를 써서, 첫 번째 서버가 Secondary여도 Primary로 연결된다.
  - 노드 ID는 서버 이름의 숫자에서, WiredTiger 캐시는 RAM의 40%(최소 0.25GB)에서 계산한다.
- 서버 시험에 필요한 것: 인터넷이 되는 서버, 2GiB 이상의 VM(`t3a.small`), 노드 사이 통신.
- 검증 결과 (AL2023 `t3a.small`, MongoDB 8.0.32, 2026-10-05)
  - Replica Set(3대): 구성과 검증이 통과했고(PRIMARY 1, SECONDARY 2), 재실행은 변경 없음(`changed=0`)이었다. 로그인 없이는 조회가 거부되고, `monitor`는 상태 조회만 되고 쓰기가 거부되며, `dev`는 계정 정보(`admin.system.users`)를 읽을 수 없다. Primary에 쓴 문서가 모든 노드에서 `dev`로 읽혔다.
  - Primary 중지: 약 20초 안에 새 Primary가 선출되었고 `dev`로 쓰기가 성공했다. 중지했던 노드를 다시 시작한 뒤(첫 번째 서버가 Secondary인 상태) 재실행도 통과했다.
  - 계정이 어긋난 경우: DB에서 `dev` 비밀번호를 바꾼 뒤 재실행하면 그 계정만 Vault 값으로 복구되었다(변경 1건).
  - 멤버 재부팅 뒤 `mongod`가 자동으로 시작되어 Replica Set에 다시 합류했다.
  - Standalone(1대): 구성과 검증이 통과했고, 재실행은 변경 없음이었다.
  - 시작 로그에 8.0의 메모리 할당기(tcmalloc) 권장 경고가 있다(`transparent_hugepage` 설정). 성능 조정 항목이라 적용하지 않았다.

## P4. Kafka

- 산출물: `roles/java`(Corretto 17), `roles/kafka`
- 내용: tarball 다운로드와 sha512 검증, 서비스 전용 사용자와 systemd unit, 브로커 기본 설정(설계 문서 5장), 데이터 경로와 로그 경로 분리(`LOG_DIR`), RAM 기반 JVM heap
  - KRaft: 클러스터 ID는 한 번만 생성해 전체 노드가 공유하고 재실행에도 유지한다. 스토리지 포맷은 `meta.properties`가 없을 때만 한 번 실행한다. 노드 ID는 서버 이름에서 만들고, controller quorum은 노드별 디렉터리 UUID를 모아 전체에 전달하거나 정적 voters를 쓴다.
- 검증: broker 연결, controller quorum, 임시 토픽으로 produce와 consume, ISR 3
- 확인할 것: 다운로드 출처(`archive.apache.org`), 4.3.1에서 브로커 설정 키의 유효성, controller quorum 방식
- 구현 메모
  - `roles/java`(Corretto 17, `java-17-amazon-corretto-headless`)를 `roles/kafka`의 의존 role로 둔다. ZooKeeper·Spark도 같은 role을 쓴다.
  - 다운로드: `dlcdn.apache.org`를 먼저, 실패하면 `archive.apache.org`를 쓴다. archive는 시험에서 약 50KB/s로 느려(120MB에 40분 이상) 예비로만 쓴다. sha512는 role 변수에 고정해 어느 미러에서 받아도 검증하고(버전을 바꾸면 같이 바꾼다), 이미 설치되어 있으면 내려받지 않는다(임시 NAT 제거 후 재실행 대비).
  - controller quorum은 정적 voters(`controller.quorum.voters`)로 정한다. 노드 ID는 서버 이름의 숫자다.
  - 경로: 설치 `/opt/kafka_2.13-4.3.1`(링크 `/opt/kafka`), 설정 `/etc/kafka/server.properties`, 데이터 `/var/lib/kafka/data`, 로그 `/var/log/kafka`(`LOG_DIR`), 사용자 `kafka`(로그인 불가), `LimitNOFILE=100000`.
  - JVM heap은 RAM의 25%(최소 256MB, 최대 6GB)로 계산해 unit의 `KAFKA_HEAP_OPTS`로 준다.
  - 클러스터 ID: 이미 포맷된 노드의 `meta.properties`에서 읽어 이어 쓰고, 없으면 한 번만 만든다. 노드마다 다르면 실패한다. 포맷은 `meta.properties`가 없는 노드에서만 한다.
  - 설정이나 unit이 바뀌면, 이미 실행 중인 서비스만 다시 시작한다(처음 시작할 때는 다시 시작하지 않는다). 모든 노드를 동시에 다시 시작하므로, 운영 중 설정을 바꿀 때는 노드를 나누어 실행한다(`--limit`).
- 서버 시험에 필요한 것: 인터넷이 되는 서버, 2GiB 이상의 VM(`t3a.small`), 노드 사이 통신.
- 검증 결과 (AL2023 `t3a.small` 3대, Kafka 4.3.1, 2026-10-05)
  - 구성과 검증이 통과했고, 재실행은 변경 없음(`changed=0`)이었다. controller quorum은 voter 3, Leader 1이고, 임시 토픽(RF=3)의 ISR이 3이며, `acks=all` produce와 consume이 성공했다. 임시 토픽은 검증 끝에 지운다.
  - 브로커 1대를 중지한 상태에서 `acks=all` produce와 consume이 성공했다(`min.insync.replicas=2`). 재부팅한 노드는 `kafka`가 자동으로 시작되어 ISR에 다시 들어왔다.
  - heap 비율을 바꿔 실행하면 설정이 반영되어 서비스가 다시 시작되었고(변경 2건: 설정, unit), 원래 값으로 되돌려도 같았다. 클러스터는 두 번 모두 검증을 통과했다.
  - 4.3.1에서 설계 문서의 브로커 기본 설정 키가 모두 유효했다. 콘솔 producer의 `--producer-property`는 더 이상 쓰지 않는 옵션이라 `--command-property`를 쓴다.

## P5. ZooKeeper + Spark

- 산출물: `roles/zookeeper`, `roles/spark`
- 내용: ZooKeeper 3노드 ensemble(`myid`는 서버 이름에서 생성, 상태 조회 명령 허용), Spark Master 2(YAML 순서의 앞 2대) + Worker 3, ZooKeeper 기반 recovery mode, `spark-env.sh` 설정(`SPARK_LOCAL_IP`가 서버에 할당된 IP인지 확인 포함), 로그 경로 분리(`SPARK_LOG_DIR`), systemd unit
- PySpark: Spark 노드에 Python 3.12를 설치하고 `PYSPARK_PYTHON`, `PYSPARK_DRIVER_PYTHON`을 지정한다 (시스템 Python 3.9는 유지).
- 커넥터 JAR 사전 설치: Kafka 커넥터, MySQL JDBC 드라이버, MongoDB Spark 커넥터와 전이 의존성 JAR을 체크섬 검증 후 Spark 노드의 JAR 폴더에 배포한다. 임시 NAT가 있을 때 받아 둔다.
- 검증: ZooKeeper 상태 응답, Master ALIVE 1·STANDBY 1, Worker 3 등록, 작은 PySpark 작업(client mode) 제출 성공
- 주의: Spark 노드는 Master, Worker, ZooKeeper가 한 VM에 동거하므로 Worker 메모리는 전체 RAM에서 OS 몫, Master·Worker 데몬 메모리, ZooKeeper heap을 뺀 값으로 계산한다.
- 확인할 것: Python 3.12 설치와 실행 경로, 커넥터 JAR의 전이 의존성 목록·체크섬·호환, 작업 제출 위치(미확정, Backend로 예상)
- 구현 메모
  - 같은 서버 그룹(`spark`)에 `roles/zookeeper`를 먼저, `roles/spark`를 이어 적용한다. 둘 다 `roles/java`를 의존 role로 쓴다.
  - 다운로드는 Kafka와 같다(`dlcdn` 우선, `archive` 예비, sha512 고정, 설치되어 있으면 건너뜀). ZooKeeper `3.9.6`(`dlcdn`에 있음)과 Spark `4.2.0`.
  - ZooKeeper: 사용자 `zookeeper`, 설치 `/opt/apache-zookeeper-3.9.6-bin`(링크 `/opt/zookeeper`), 설정 `/etc/zookeeper`, 데이터·`myid` `/var/lib/zookeeper`, 로그 `/var/log/zookeeper/zookeeper.log`, heap 256MB. `myid`는 서버 이름의 숫자, 상태 조회 허용(`4lw.commands.whitelist=ruok,srvr,mntr,stat`), 내장 관리 서버(8080)는 Spark UI 포트와 겹쳐 끈다. ZooKeeper 3.9는 logback을 써서, 파일 로그를 남기려면 설정 디렉터리에 `logback.xml`을 직접 배포해야 한다(파일 한 개에 쓰고 회전은 logrotate가 맡는다).
  - Spark: 사용자 `spark`, 설치 `/opt/spark-4.2.0-bin-hadoop3`(링크 `/opt/spark`), 설정 `/etc/spark`(`spark-env.sh`, `spark-defaults.conf`), Worker 작업 경로 `/var/lib/spark/work`(완료된 앱 정리 켬), 로그 `/var/log/spark/{master,worker}.log`. Master(`spark-master`)와 Worker(`spark-worker`)는 각각 systemd 서비스(`spark-class` 포그라운드 실행)이며, Master는 YAML 순서의 앞 2대, Worker는 전체다. 이중화는 `spark.deploy.recoveryMode=ZOOKEEPER`로 한다.
  - 메모리: Worker 메모리 = RAM - OS 1024MB - 데몬 512MB × (Master 있으면 2, 없으면 1) - ZooKeeper 256MB. 결과가 512MB 미만이면 중단한다 (`t3a.medium` 4GiB에서 Worker 1543MB). `SPARK_LOCAL_IP`가 서버에 할당된 IP인지 확인한다.
  - PySpark: `python3.12`를 설치하고 `PYSPARK_PYTHON`, `PYSPARK_DRIVER_PYTHON`을 지정한다(시스템 Python 3.9는 그대로).
  - 커넥터 JAR 10개를 Maven Central에서 받아 `/opt/spark/jars`에 둔다(sha256 고정): `spark-sql-kafka-0-10_2.13` 4.2.0, `spark-token-provider-kafka-0-10_2.13` 4.2.0, `kafka-clients` 3.9.2, `commons-pool2` 2.13.1, `mongo-spark-connector_2.13` 11.1.0, `mongodb-driver-sync`·`mongodb-driver-core`·`bson`·`bson-record-codec` 5.1.4, `mysql-connector-j` 9.7.0. 각 JAR의 `.pom` 의존을 따라 정했고, Spark 배포판에 이미 있는 `scala-parallel-collections` 1.2.0, `slf4j`, `lz4`, `snappy`, `jsr305`는 뺐다. MySQL JDBC의 `protobuf-java`는 X 프로토콜용이라 뺐다. sha256은 내려받은 파일을 Maven Central의 `.sha1`과 대조해 확인한 값이다.
- 서버 시험에 필요한 것: 인터넷이 되는 서버, 4GiB 이상의 VM(`t3a.medium`), 노드 사이 통신.
- 검증 결과 (AL2023 `t3a.medium` 3대, ZooKeeper 3.9.6, Spark 4.2.0, 2026-10-05)
  - 구성과 검증이 통과했고 재실행은 변경 없음(`changed=0`)이었다. ZooKeeper는 leader 1·follower 2, Master는 ALIVE 1·STANDBY 1(활성 Master에 Worker 3 등록), PySpark 작업(client mode)은 실행기의 Python 3.12 확인, 계산, 커넥터 클래스 8개 로딩이 모두 성공했다.
  - 활성 Master를 중지하자 약 43초 만에 Standby가 ALIVE가 되었고 Worker 3대가 다시 등록되었다. Master 1대가 내려간 상태에서 작업 제출도 성공했다(제출 로그에 내려간 Master 연결 실패 경고는 남는다). 중지했던 Master를 시작하면 STANDBY로 돌아오고, Worker 노드를 재부팅해도 서비스가 자동으로 올라와 재실행 검증이 통과했다.
  - 설정·unit이 바뀐 상태에서 재실행하면 이미 실행 중인 서비스만 다시 시작했고, 이후 검증이 통과했다.
  - 시험 중 고친 것: ZooKeeper의 파일 로그(logback 설정 배포). systemd `Environment=`에 공백이 든 값은 따옴표로 감싸야 한다(`JVMFLAGS`의 `-Xmx`가 무시되고 있었다). Kafka unit의 `KAFKA_HEAP_OPTS`도 같은 문제여서 고쳤고, P7 시험에서 `-Xmx`가 적용되는 것을 확인했다.
  - 확인하지 못한 것: 커넥터로 실제 Kafka·MongoDB·MySQL에 연결하는 작업(클래스 로딩까지만 확인했다. 서비스 연동은 P8), Python 3.12 외 서비스 패키지.

## P6. Backend, Frontend

- 산출물: `roles/backend`(MySQL Router 설치), Frontend는 별도 role 없이 공통 보안과 방화벽만 적용
- 내용: Backend에 MySQL Router 설치까지만 한다. 애플리케이션 런타임은 범위 밖이다.
- 확인할 것: Router bootstrap에 쓰는 계정과 접속 출처 (필요하면 `failover` 계정의 허용 출처에 Backend 추가)
- 구현 메모
  - `roles/backend`는 MySQL 저장소(`roles/mysql/tasks/repo.yml`을 재사용)를 등록하고 `mysql-router-community`를 설치한 뒤 버전(8.4)을 확인한다. Router 설정(bootstrap)과 실행은 서비스 영역이다.
  - Frontend는 role이 없고 공통 보안과 방화벽만 적용한다.
- 서버 시험에 필요한 것: 인터넷이 되는 서버, 2GiB 이상의 VM(`t3a.small`), MySQL ReplicaSet(bootstrap 확인용).
- 검증 결과 (AL2023 `t3a.small` 4대: MySQL 2, Backend 1, Frontend 1, Router 8.4.10, 2026-10-05)
  - 구성과 검증이 통과했고 재실행은 변경 없음(`changed=0`)이었다. MySQL role의 저장소 단계를 분리한 뒤에도 MySQL 구성이 같다.
  - Frontend: 다른 서버에서 80은 응답하고 8080은 막힌다(역할 간 허용 관계에 없는 포트).
  - Router bootstrap(Backend에서 ReplicaSet에 대해 실제로 수행):
    - 기본 설정(`failover`는 MySQL 노드·Bastion에서만 허용): `failover`로 bootstrap하면 Backend IP가 거부된다(`Access denied`).
    - `failover`의 허용 출처에 `backend`를 추가(`mysql_failover_extra_source_groups: [bastion, backend]`)하면 bootstrap이 성공하고, Router의 읽기·쓰기 포트가 동작한다. 6446은 Primary, 6447은 Secondary로 연결되고 `dev`로 쓰기도 된다.
    - 전용 계정: ReplicaSet에서 `rs.setupRouterAccount('router@<Backend IP>', {password: ...})`로 만든 계정은 메타데이터 읽기·라우터 등록 권한만 가진다. 이 계정으로 `mysqlrouter --bootstrap router@<MySQL IP>:3306 --account router --account-create never`를 실행하면 성공하고 Router가 그 계정으로 동작한다. 같은 계정을 `--account` 없이 쓰면 Router용 계정을 새로 만들 권한이 없어 실패한다.
    - 비밀번호는 Router가 표준 입력으로 받는다(`--bootstrap` 때 두 번 입력).
  - 결정: 전용 `router` 계정으로 한다(최소 권한). `failover`의 허용 출처는 바꾸지 않는다. 아래 "Router 전용 계정"에 구현과 검증 결과가 있다.

### Router 전용 계정 (P6 결정 반영)

- 구현: `roles/mysql`의 ReplicaSet 스크립트가 Backend IP마다 `rs.setupRouterAccount('router@<Backend IP>', {password})`로 계정을 만든다. ReplicaSet(MySQL 2대)이고 `backend` 그룹이 있을 때만 만들며, 이미 있으면 건드리지 않는다. 비밀번호는 Vault의 `vault_mysql_passwords.router`다(값 형식은 `vault.example.yml`). Secondary에는 복제되어 온다. 계정이 어긋난 것(비밀번호 변경 등)은 고치지 않으므로, 바꿔야 하면 `rs.setupRouterAccount(..., {update: true})`를 수동으로 실행한다.
- 검증: ReplicaSet의 각 노드에서 `router` 계정의 출처가 Backend IP와 같은지 확인한다.
- 사용(서비스 영역, Backend에서): 비밀번호는 표준입력으로 두 번 받는다.
  - `mysqlrouter --bootstrap router@<MySQL IP>:3306 --account router --account-create never --directory <경로> --user=mysqlrouter`
  - `--account router --account-create never`가 없으면 Router용 계정을 새로 만들 권한이 없어 실패한다.
- 검증 결과 (AL2023 `t3a.small` 3대: MySQL 2, Backend 1, 2026-10-06)
  - 새 ReplicaSet에서 계정이 만들어졌고 재실행은 변경 없음(`changed=0`)이었다.
  - Backend에서 위 명령으로 bootstrap이 성공했고, Router의 6446은 Primary, 6447은 Secondary로 연결되며 `dev`로 연결해 쓰기도 된다.
  - `router` 계정은 `mysql.user` 조회와 DB 생성이 거부되고 메타데이터만 읽을 수 있다. MySQL 노드 등 Backend 이외의 출처에서는 접속이 거부된다.
  - Standalone(MySQL 1대)에서는 Router용 ReplicaSet 메타데이터가 없어 이 계정을 만들지 않는다(시험하지 않았다).

## P7. Monitoring

- 산출물: `roles/monitoring`, 수집 셸 스크립트
- 내용
  - 모든 서버: `monitor` 읽기 전용 사용자(`systemd-journal` 그룹, 로그 읽기 권한), 공개키 등록, `rsync` 설치, logrotate(일 단위, 3일), journald 보존 한도
  - Monitoring 서버: 수집 스크립트와 systemd timer, 수집 결과 저장과 일 단위 회전, 로그 수집 폴더와 보관 폴더, 14일 정리
  - 수집 주기: 리소스 10초, 서비스 상태 30초, 로그 10초. 연속 3회 실패 시 down, 이후에도 계속 시도.
- 검증: 모든 서버의 리소스, 서비스 상태, 로그가 수집됨
- 확인할 것: `journalctl` cursor 유실, `rsync`의 마지막 줄 잘림과 회전 시점 중복, 10초 주기의 CPU 부담
- 구현 메모
  - role은 `roles/monitoring` 하나이고, 모든 서버에 같은 play로 적용한다. 대상 설정(`target.yml`, 모든 서버)이 끝난 뒤 수집 설정(`collector.yml`, Monitoring 서버)이 실행되도록 한 play 안에서 순서대로 돌린다. `monitoring` 그룹이 없으면 건너뛴다.
  - 수집은 systemd timer가 아니라 **상시 실행 루프 서비스**(`infra-monitor.service`, `collector.sh`)로 한다. timer가 10초마다 새 프로세스를 띄우면 SSH 연결 재사용(ControlMaster)이 매번 끊기기 때문이다. 일 단위 정리만 timer(`infra-monitor-archive.timer`, 매일 03:30 UTC)로 한다.
  - 대상 서버: `monitor` 사용자(로그인 셸 `bash`, 그룹 `systemd-journal`과 있으면 `mysql`·`mongod`), 공개키는 Monitoring IP에서만 쓰도록 `from=`과 `no-port-forwarding,no-pty` 등을 붙인다. `rsync`, `logrotate` 설치, 원격 수집 스크립트(`/usr/local/libexec/infra-monitor/{resource,service}.sh`).
  - 읽기 권한: MySQL 로그(`/var/log/mysqld.log`)와 MongoDB 로그(`0640`)는 그룹 읽기, Kafka·Spark·ZooKeeper 로그는 기본이 전체 읽기다. 설정 변경은 필요 없었다.
  - 로그 형태 정리: Kafka는 `log4j2.yaml`을 직접 배포해 `server.log` 한 파일에 쓰고(기본 설정은 기능별 파일을 날짜 접미사로 회전하며 지우지 않는다), ZooKeeper는 `logback.xml`을 직접 배포한다. 회전은 모두 logrotate가 맡는다.
  - 서버 logrotate: 일 단위, 3일, `dateext`(회전 파일 이름이 날짜로 고정되어 수집 폴더에서 덮어쓰이지 않는다), `copytruncate`. `copytruncate`는 O_APPEND로 쓰는 로그에만 안전하므로 회전 대상 파일을 명시한다(Kafka의 JVM GC 로그는 JVM이 직접 회전하므로 제외).
  - journald: 디스크에 저장(`Storage=persistent`)하고 `SystemMaxUse=200M`.
  - 수집 서버: 사용자 `infra-monitor`, 설정 `/etc/infra-monitor`(`monitor.conf`, `hosts.conf`는 매 주기 읽음, `id_ed25519`와 `secrets`는 수집 사용자만 읽는 `0400`), 데이터 `/var/lib/infra-monitor/{metrics,logs,state}`, 보관 `/var/archive/infra`.
  - 저장: `metrics/<서버>/{resource,service}-<날짜>.log`(한 줄에 한 샘플, `키=값`), `logs/<서버>/journal/journal-<날짜>.log`, `logs/<서버>/<서비스 로그 폴더>/`.
  - 하트비트: 리소스 수집(10초)의 SSH 성공 여부로 판단한다. 실패하면 `reach=fail fails=N`, 연속 3회째부터 `state=down`이며 계속 시도하고, 성공하면 즉시 `state=up`.
  - 리소스 샘플: CPU와 네트워크는 누적 값이라 비율은 샘플 간 차이로 계산한다. 서비스 상태: systemd unit 상태, MySQL(읽기 전용 여부, 연결 수, `monitor` 계정), MongoDB(PRIMARY/SECONDARY, `monitor` 계정), Kafka(포트), ZooKeeper(`srvr`의 Mode), Spark(Master ALIVE/STANDBY와 Worker 수, Worker UI). DB 비밀번호는 SSH 표준입력으로 넘긴다(명령줄에 노출하지 않는다).
  - 일 단위 정리: 하루 지난 파일은 압축 복사해 보관 폴더에 두고(원본이 바뀌면 다시), 수집 폴더의 원본은 4일 뒤, 보관 폴더의 파일은 14일 뒤 지운다.
- 서버 시험에 필요한 것: 인터넷이 되는 서버, 서버 15대(설계 구성. Bastion 경유), 서버 대수가 부담스러우면 일부 역할만으로도 시험할 수 있다.
- 검증 결과 (AL2023 `t3a.small` 12대 + `t3a.medium` 3대 = 설계 구성 15대, Bastion 경유, 2026-10-05)
  - 구성과 검증이 통과했고, 전체 플레이북의 재실행은 15대 모두 변경 없음(`changed=0`)이었다. 모든 서버에서 `monitor` 사용자가 시스템 로그와 서비스 로그를 읽을 수 있고, Monitoring 서버에 모든 서버의 리소스·서비스 상태·시스템 로그·서비스 로그가 모였다. `monitor` DB 계정(MySQL, MongoDB)이 처음으로 실제 쓰였고(MySQL 읽기 전용 여부와 연결 수, MongoDB PRIMARY/SECONDARY) 정상이었다.
  - 장애: 서버(`kafka-03`)를 중지하자 연속 실패 1, 2회는 `state=up`, 3회째(약 30초)에 `state=down`이 되었고 이후 계속 시도했다. 다른 서버의 수집은 영향이 없었다. 서버를 켜자 첫 성공에서 바로 `state=up`이 되었고, journald 수집(cursor)은 재부팅을 가로질러 이어졌다(디스크 저장 설정 덕분).
  - 로그 회전: 서버에서 logrotate를 강제로 돌리면 MySQL, MongoDB, Kafka, ZooKeeper 모두 이후 로그가 빈 구간 없이 이어졌다. 회전된 파일(`server.log-20261005`)은 날짜 이름이라 수집 폴더에 따로 남았다.
  - 정리: 인위적으로 오래된 파일로 시험했다. 하루 미만은 그대로, 하루 이상은 압축 복사(원본 유지), 4일 초과 원본은 삭제, 14일 초과 보관 파일은 삭제되었다.
  - CPU 부담(60초 측정, 15대 / 10초 주기): Monitoring 서버는 전체 6%(2 vCPU, 수집 루프 약 6.8초 CPU), 대상 서버는 `monitor` 세션 합계가 Kafka 약 0.9초, MongoDB 약 2.8초(30초마다 `mongosh`를 띄우는 비용)였다. 부담은 작다.
  - 시험 중 고친 것: `hosts.conf`의 주석 줄을 서버로 읽던 문제, Mongo 로그 권한을 위해 넣었던 존재하지 않는 설정(`processManagement.filePermissions`, 제거. 기본 `0640`으로 충분), 회전 대상 파일 명시.
  - 확인하지 못한 것: `rsync`의 마지막 줄 잘림(쓰는 중인 파일을 가져올 때). 다음 주기에 이어서 받으므로 영구 손실은 아니지만 별도로 확인하지는 않았다. 서버 수십 대 규모와 로그가 큰 경우의 `rsync` 부담, 수집 서버 재부팅 뒤 동작.

## P8. 통합과 멱등성

- 전체 구성으로 `ansible-playbook site.yml`을 한 번에 실행한다.
- 같은 명령을 한 번 더 실행해 **변경 없음(changed=0)**을 확인한다.
- P1에서 확인하지 못한 항목을 서비스 서버가 갖춰진 뒤 확인한다: Bastion 출처에서 SSH 외 모든 포트가 열리는지(보안 그룹이 해당 포트를 허용한 상태에서), 클러스터 서버 사이의 허용 규칙.
- 전체 구성이 갖춰진 뒤 설계 문서의 "수동 장애 확인"(MongoDB, Kafka, Spark)을 사람이 한 번 수행한다. 자동 검증이 아니며 role의 완료 기준에는 포함하지 않는다.
- 작은 구성(예: MySQL 1대 + MongoDB 1대)으로도 실행해 가변 구성이 동작하는지 확인한다.
- 임시 NAT를 제거한 뒤 재실행했을 때 패키지 task가 동작하는지 확인한다.
- 설계 문서의 14장 항목을 모두 확인하고 문서를 갱신한다.
- P7 시험에서 이미 확인한 것(2026-10-05, 설계 구성 15대, Bastion 경유): 전체 구성 실행과 재실행(`changed=0`), Bastion·Monitoring 출처의 SSH 허용 규칙, MongoDB 장애 후 재실행. 남은 것: 임시 NAT 제거 후 재실행, 작은 구성 실행, 수동 장애 확인(Kafka, Spark, MongoDB), 서비스 연동(Spark 커넥터로 Kafka·MongoDB·MySQL 접속).

### 결과 (2026-10-06, AL2023 `t3a.small` 14대 + `t3a.medium` 3대)

- **전체 구성(설계 15대, Bastion 경유)**: `ansible-playbook site.yml`로 구축했고, 재실행은 15대 모두 변경 없음(`changed=0`)이었다.
- **임시 NAT 제거 후 재실행**: Bastion을 뺀 14대의 외부 아웃바운드를 막은 상태(VPC·링크로컬만 허용)에서 전체를 재실행했고 15대 모두 `failed=0`, `changed=0`이었다. 시험에서 `rpm_key`가 매번 URL에서 키를 받아 인터넷이 없으면 실패하는 것을 찾아, 이미 등록된 키(`rpm -q gpg-pubkey-<ID>`)는 건너뛰게 고쳤다(MySQL, MongoDB). 나머지(패키지, tarball, 커넥터 JAR)는 이미 설치되어 있으면 네트워크를 쓰지 않는다.
- **작은 구성(MySQL 1대 Standalone + MongoDB 1대 Standalone, Bastion 없이 직접 접속)**: 구축과 검증이 통과했고, 재실행과 외부 차단 상태의 재실행이 모두 `changed=0`이었다.
- **방화벽 허용 관계**: 실제 연결 27개를 시험해 모두 설계와 같았다. Bastion은 SSH 외 서비스 포트(MySQL, MongoDB, Kafka, Spark, Backend)에 접근하고, Backend·Spark·클러스터 노드끼리의 허용이 열리며, 허용 관계에 없는 연결(예: Frontend→MySQL, Kafka→MySQL, MySQL→MongoDB, Monitoring→MySQL 3306)과 SSH(22, Bastion·Monitoring 외)는 막힌다.
- **Spark 커넥터 연동**(`platform/tests/spark_integration.py`, Spark 노드에서 제출): Kafka 토픽 100건을 Spark가 읽어 MySQL(JDBC, Connector/J 9.7.0)과 MongoDB(커넥터 11.1.0)에 쓰고 다시 읽어 건수가 일치했다. MySQL 2대와 MongoDB 3대 모두에 100건이 복제되어 있었다. 이로써 Kafka 4.3.1 브로커(kafka-clients 3.9.2), MySQL 8.4(기본 인증 `caching_sha2_password`), MongoDB 8.0(드라이버 5.1.4)과의 호환이 확인되었다.
- **수동 장애 확인**(통합 환경, Monitoring이 함께 감지)
  - MongoDB: Primary 중지 → 약 25초 안에 새 Primary 선출, `dev`로 `w:majority` 쓰기 성공. Monitoring은 중지된 노드를 `unit_mongod=inactive`로, 새 Primary를 `mongo_primary=1`로 표시했다.
  - Kafka: 브로커 1대 중지 → `acks=all` produce와 consume 성공(`min.insync.replicas=2`). Monitoring은 `unit_kafka=failed kafka_port=down`으로 표시했다.
  - Spark: 활성 Master 중지 → 44초 만에 Standby가 ALIVE(Worker 3대 등록), Master 1대 중지 상태에서 작업 제출 성공. Monitoring은 `unit_spark-master=failed`로 표시했다.
  - 서비스를 되돌린 뒤 15대 모두 `state=up`이고 이상 없음이었다.
- **시험 환경에서 알게 된 것**: 새 서버가 이전에 종료된 서버의 사설 IP를 재사용하면 개발자 PC의 `known_hosts`에 남은 옛 호스트 키와 충돌해 SSH가 거부된다(`Host key verification failed`). 서버를 지우고 다시 만든 환경에서는 `ssh-keygen -R <IP>`로 옛 항목을 지운다.
- **확인하지 못한 것**: Standalone MySQL에서 Router(메타데이터 없음), 운영 중 ReplicaSet에 `router` 계정을 추가하는 재실행, 수집 서버 재부팅 뒤 동작, 서버 수십 대 규모, `rsync`의 마지막 줄 잘림(14장).

---

# 3. 단계별 완료 기준

각 단계는 아래를 모두 만족해야 완료다.

1. 해당 role의 검증이 통과한다.
2. 같은 명령을 다시 실행하면 변경이 없다.
3. 설계 문서 14장에서 해당 단계의 확인 항목이 처리되었다 (확인됨 또는 문서 보완).
4. [platform/README.md](../platform/README.md)의 구현 상태 표가 갱신되었다.

---

# 4. 테스트 환경과 진행 방식

- 테스트는 사전에 구성된 AWS 서버에서 한다. 패키지 설치를 위해 임시 NAT가 연결되어 있어야 한다. 기본 시험 OS는 Ubuntu 24.04 LTS이고, Amazon Linux 2023은 회귀 시험으로 유지한다 ([ubuntu-porting-plan.md](ubuntu-porting-plan.md)). 위 P0~P8의 시험 결과는 AL2023에서 얻은 것이다.
- 구성은 작은 것부터 늘린다.
- 서비스 사용자, systemd unit, 설치·데이터 경로, OS 한도 같은 세부 값은 각 role을 구현할 때 기본값을 정해 설계 문서에 기록한다.
| 순서 | 구성 | 확인 대상 |
|---|---|---|
| 1 | VM 1대 | P0, P1 |
| 2 | MySQL 1대 → 2대 | P2 (Standalone, ReplicaSet) |
| 3 | MongoDB 1대 → 3대 | P3 |
| 4 | Kafka 3대 | P4 |
| 5 | Spark 3대 | P5 |
| 6 | Backend + MySQL | P6 |
| 7 | Monitoring + 위 서버들 | P7 |
| 8 | 전체 | P8 |

- 서버 대수는 프로그램이 검증하지 않으므로, 테스트용 inventory 예시는 `platform/inventory/`에 두고 README의 "가능한 구성"과 일치시킨다.
- 메모리가 작은 VM에서는 Kafka, Spark, MongoDB를 정상 검증할 수 없다. 해당 단계는 서비스가 올라갈 수 있는 크기의 VM에서 한다.

---

# 5. 주요 위험과 대응

| 위험 | 대응 |
|---|---|
| 방화벽 적용 중 SSH 접속이 끊긴다 | Bastion SSH 허용 → 연결 검증 → default deny 순서, 서버 한 대에서 먼저 확인, nftables 원자적 교체 |
| sshd 설정이 적용되지 않거나 깨진다 | 문법 검사와 실패 시 설정 롤백, 유효 설정 검증 (P0에 구현) |
| MySQL 8.4 설치와 호환 문제 | P2를 서버 한 대에서 먼저 확인하고 설계 문서 14장에 기록 |
| NAT 제거 후 재실행이 실패한다 | P8에서 확인하고, 필요하면 NAT 재연결을 절차로 문서화 |
| Spark 노드의 메모리 부족 (3개 데몬 동거) | RAM 기반 메모리 분배, P5에서 실제 확인 |
| 로그 수집(셸)이 복잡하다 | P7을 마지막에 두고, 문제가 되면 수집 대상을 단계적으로 줄인다 |
| 가정에 기댄 항목이 틀렸다 | 해당 단계에서 확인하고 설계 문서를 보완한다 |

---

# 6. 이 계획에 포함하지 않는 것

- 포트 목록 확정 (확정되면 P1의 규칙 데이터에 반영)
- Monitoring UI, 보관된 로그의 후처리, MySQL 자동 failover
- 일정과 담당자 (프로젝트 운영 문서에서 관리한다)

---

# 별도 참고: 현재 구성 안내 — 2026-10-10

이 아래 내용은 후속 문서 정리에서 추가한 현재 구성 안내이며, 위 원문 작성자의 작업·완료·시험 기록에 포함되지 않는다.

위 P0~P8의 날짜별 시험 결과는 과거 시험 구성의 기록이다. 이번 문서 갱신에서 원격 Ansible·AWS·서비스 시험을 재실행하지 않았고, 과거 완료 표가 새 EC2의 설치 완료를 뜻하지 않는다. 현재 AWS 기본 구성은 서비스 16대와 선택적 Bastion 1대이며 Frontend 2대·game·ad·평탄화 Consumer flatten-1을 포함한다. Backend·Monitoring은 선택 그룹이고 Consumer 프로그램은 별도로 배포한다.

현재 실행은 서버 생성 → Inventory → Proxy 준비 → 플랫폼 역할 설치 → 역할별 검증 순서다. Squid·APT 준비와 common 태그만으로 DB·Kafka·Spark를 설치하지 않는다. --tags zookeeper만 실행하면 Spark는 설치되지 않으므로 --tags zookeeper,spark --limit spark를 실행한다. DB Secret과 생성 인벤토리 경로를 명시하는 명령은 [README](../platform/README.md)를 따른다.

Spark는 Master 7077·내부 UI 8080, Worker 7100, Driver 7078–7094, BlockManager 7079–7095를 사용한다. 작업 포트 재시도는 16회, 데몬은 0회다. ZooKeeper 2181·2888·3888은 Spark 3개 노드 간 AWS 규칙과 함께 허용해야 한다. Worker UI 8081은 원격 공개 SG 규칙이 없다. 현재 파일 위치와 검증 작업은 [Spark 라우팅 문서](../platform/docs/platform-routing/roles/spark/README.md), [ZooKeeper 라우팅 문서](../platform/docs/platform-routing/roles/zookeeper/README.md)를 따른다.

## MySQL InnoDB Cluster 전환 — 2026-10-10

기존 P2/P6의 ReplicaSet·Router 설치 서버 검증은 과거 구현 기록으로 유지한다. 현재 코드는 MySQL 그룹 전체 3~9대의 단일 Primary InnoDB Cluster와 game·Spark·선택 Backend의 로컬 Router bootstrap·서비스·Primary 연결 검증으로 전환했다. GTID 초기화를 제거하고 실제 Primary 계정 적용, 신규 clone 데이터 보호, 기존 멤버 증분 재가입, 기존 토폴로지·정족수 보호를 추가했다. 로컬 템플릿·AdminAPI 모의 27개·Ansible 인벤토리·재실행 보호 11개·playbook 문법 검사를 통과했다. 현재 생성 인벤토리의 MySQL 2대 확장, 실제 EC2 설치, 자동 선출·Router 재접속·쓰기·복귀 검증은 남아 있다.
