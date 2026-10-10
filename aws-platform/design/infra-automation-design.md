> Status: Approved  
> 승격일: 2026-10-05  
> 목적: 막 생성된 Linux VM에 Ansible로 보안 설정과 역할별 구축을 수행하는 인프라 자동화의 범위, 구성, 결정 사항을 정의하는 기준 문서

---

# 현재 구현 반영 — 2026-10-10

위 Approved·승격일은 원래 설계의 승인 기록이다. 이번 갱신은 현재 로컬 구현의 문서 반영이며 새 설계 승인이나 EC2 재검증 결과가 아니다. 과거 서버 시험·외부 버전 확인은 당시 기록으로 읽는다. 현재 실행 절차는 [플랫폼 README](../platform/README.md), 구현 파일 위치는 [라우팅 문서](../platform/platform-routing/ROUTING-README.md)를 따른다.

AWS 서버 생성과 비용별 프로필 변경은 별도 aws-infra의 deploy.ps1이 맡는다. Inventory는 hosts.current.yml을 생성하고 Proxy는 설치용 네트워크를 준비한다. 이 단계와 플랫폼 서비스 설치를 구분한다.

# 1. 문서 목적과 범위

본 문서는 인프라 자동화(`aws-platform/platform/`)가 무엇을 구축하고 무엇을 구축하지 않는지, 그리고 구현 전에 확정한 결정 사항을 정의한다.

## 범위 안

- 서버 보안 설정: sshd, 사용자, sudo, 방화벽, 시간 동기화
- 서비스 구축: MySQL, MongoDB, Kafka, Spark, ZooKeeper
- Monitoring 서버의 수집과 로그 보관
- Backend 서버의 MySQL Router 설치

## 범위 밖

- AWS 환경 생성: VPC, Peering, Security Group, VM, 인터넷 연결 경로. aws-infra가 담당하며 현재 기본값은 NAT 0개와 중앙 Bastion Proxy다.
- Frontend/Backend의 서비스와 비즈니스 로직
- Monitoring UI
- 보관된 로그의 후처리
- MySQL 자동 failover

---

# 2. 목표와 전제

막 생성된 x86_64 Linux VM에 Ansible로 보안 설정과 역할별 구축을 한다. Python 오케스트레이터는 두지 않고 Ansible만 쓴다. 전체 구축은 `ansible-playbook`, 역할별 실행은 `--limit`(또는 태그)로 한다.

- 전제: VM·VPC·Peering·Security Group·SSH 경로가 준비되어 있다. 프록시 활성 구성은 Ubuntu 24.04 amd64의 prepare-proxy.yml을 첫 패키지 설치 전에 실행한다. 이 도구는 AWS 환경을 만들지 않는다.
- 현재 기본 다운로드 경로는 Bastion Squid TCP 3128이고 Bastion은 HTTPS로 직접 나간다. 설치 파일이 남아 있으면 일부 다운로드를 생략하지만, 전체 실행은 프록시 외부 검사를 포함하므로 오프라인 재실행을 보장하지 않는다. AL2023 역할 지원과 Ubuntu 전용 프록시 준비의 지원 범위를 구분한다.
- 프로젝트 위치: 저장소의 `aws-platform/platform/` (inventory, role, 플레이북, `requirements.txt`)
- 대상 서버의 Python: Ansible은 시스템 Python(`/usr/bin/python3`, Ubuntu 24.04는 3.12, AL2023은 3.9)을 쓴다. 기본 이미지에 이미 있어 `raw` 부트스트랩은 필요 없다 (확인됨).
- 실행 위치: 개발자 PC의 WSL에서 Ansible을 실행한다. Bastion은 SSH ProxyCommand 경유지이자 설치용 Squid 프록시다. 생성 인벤토리는 대상 계정 키와 Bastion 계정 키를 구분한다. 접속 주소를 갱신하려면 Inventory를 다시 생성한다.

---

# 3. 핵심 원칙

- 멱등성: 2차 실행은 `OK`, drift는 desired state로 복원
- 설치 성공이 아니라 **실제 동작을 검증** (SELECT 1, produce/consume, worker 등록 등)
- Secret은 Ansible Vault, 평문 저장 금지
- 인스턴스 타입에 의존하지 않는다: 메모리에 의존하는 설정(JVM heap, Spark Worker, MongoDB 캐시, MySQL buffer pool 등)은 서버의 실제 RAM에서 계산한다.
- OS: **기본 대상은 Ubuntu 24.04 LTS**이고 Amazon Linux 2023도 지원한다(둘 다 구현·검증). OS는 서버의 배포판(`ansible_facts['distribution']`)으로 자동 감지하므로 입력 YAML에 OS 항목을 두지 않는다. 한 클러스터에 두 OS를 섞는 구성은 지원 범위가 아니다(시험하지 않음). OS별 차이와 포팅 결과는 [ubuntu-porting-plan.md](ubuntu-porting-plan.md)에 있다.

---

# 4. 입력

Ansible은 **inventory(YAML)**의 서버 이름·그룹·IP·계정 정보를 읽는다. 수동 입력 예시는 아래와 같고, aws-infra의 Inventory 실행은 Terraform 출력과 실제 AWS 서버를 대조해 inventory/hosts.current.yml을 생성한다. 인프라 mongo 역할은 mongodb 그룹으로 변환한다. 예시의 단일 키는 공통 키 구성에만 해당하므로 계정별 키를 쓰는 경우 생성 인벤토리의 인증 경로를 따른다.

- YAML인 이유: 서버 목록은 구조화된 데이터라 `.env`의 평면 key=value로는 표현이 어렵고, Ansible이 바로 읽는 형식이다.
- 비밀번호/키 같은 Secret은 이 파일에 쓰지 않고 Ansible Vault에 둔다. (팀원 공개키는 Secret이 아니므로 이 파일에 둔다.)
- 서버 대수와 가능한 구성은 프로그램이 검증하지 않는다. 개발자가 유의하며, 가능한 구성은 README에 명시한다.
- Bastion은 사설 IP(`ip`)와 공인 IP(`public_ip`)를 모두 적는다. 개발자 PC는 공인 IP로 Bastion에 `ssh -i 키 사용자@공인IP`로 접속하고, 나머지 서버는 Bastion을 경유해 사설 IP로 접속한다. 접속 주소(`ansible_host`)는 Bastion은 `public_ip`, 나머지는 `ip`로 group_vars에서 지정한다.
- 팀원별 계정과 공개키는 `users`에 적고, 모든 서버에 생성한다. 접속 계정(Ubuntu는 `ubuntu`, AL2023은 `ec2-user`)은 Ansible 자동화 계정으로 유지하고, 팀원 계정은 사람이 로그인하는 용도다.

```yaml
all:
  vars:
    ansible_user: ubuntu           # AL2023이면 ec2-user
    ansible_ssh_private_key_file: ~/.ssh/infra.pem
    users:
      - { name: alice, pubkey: "ssh-ed25519 AAAA... alice" }
      - { name: bob,   pubkey: "ssh-ed25519 AAAA... bob" }
  children:
    bastion:
      hosts:
        bastion-01: { ip: 10.10.0.10, public_ip: 203.0.113.10 }
    mysql:
      hosts:
        mysql-01: { ip: 10.30.20.11 }
        mysql-02: { ip: 10.50.20.11 }
    kafka:
      hosts:
        kafka-01: { ip: 10.30.20.21 }
        # ... 역할(그룹)별로 서버를 나열
```

---

# 5. 서버 구성

| 역할 | 대수 | 비고 |
|---|---|---|
| Bastion | 1 | |
| Frontend | 현재 기본 2 | 수동 시험 구성에서는 1대도 사용 |
| Monitoring | 선택 그룹 | 현재 AWS 기본 배치에는 없음 |
| Backend | 선택 그룹 | MySQL Router 설치, 현재 AWS 기본 배치에는 없음 |
| MySQL | 2 | InnoDB ReplicaSet, AdminAPI 수동 failover |
| MongoDB | 3 | Replica Set, 1대 장애 허용 |
| Kafka | 3 | KRaft combined, `RF=3, min.isr=2, acks=all`, 1대 장애 허용 |
| Spark | 3 | Master 2 + Worker 3 + ZooKeeper 3 (3노드 동거) |

모드는 서버 대수에서 자동 결정한다 (MySQL 1대 Standalone / 2대 ReplicaSet, MongoDB 1대 Standalone / 3대 Replica Set). 현재 AWS 기본 배치는 서비스 15대와 선택적 Bastion 1대이며 game·ad는 전용 설치 역할과 애플리케이션 방화벽 규칙이 없다. 위 표의 선택 그룹을 실제 생성된 서버처럼 해석하지 않는다.

## 역할 지정과 노드 ID

- 같은 역할 안에서 YAML에 적은 순서로 초기 Primary(MySQL)와 Master(Spark는 앞 2대)를 지정한다. 순서는 최초 지정에만 쓴다.
- Kafka `node.id`, ZooKeeper `myid`, MongoDB 멤버 `_id` 같은 노드 ID는 순서가 아니라 서버 이름에서 만든다 (`kafka-01` → 1). YAML을 재배열해도 ID가 바뀌지 않게 하기 위함이다.
- 서버는 YAML 끝에만 추가한다.

## MySQL failover

개발자가 MySQL Shell(AdminAPI)로 수동 수행한다. 자동 failover(Bastion 또는 Monitoring에서 상태를 확인해 실행)는 후속 과제다.

## Kafka

- 브로커 기본 설정: `process.roles=broker,controller`, `num.partitions=3`, `default.replication.factor=3`, `min.insync.replicas=2`, `offsets.topic.replication.factor=3`, `transaction.state.log.replication.factor=3`, `transaction.state.log.min.isr=2`, `auto.create.topics.enable=false`, `group.initial.rebalance.delay.ms=0`
- Broker와 Controller 리스너는 서버의 사설 IP로 지정한다. 기본 포트는 Broker 9092, Controller 9093이며 AWS 규칙과 함께 맞춘다.
- 클러스터 ID는 한 번만 생성해 모든 노드가 공유하며, 재실행해도 바꾸지 않는다. 스토리지 포맷은 데이터를 초기화하므로 `meta.properties`가 없는 노드에서 한 번만 실행한다.
- 토픽 자동 생성이 꺼져 있으므로 검증용 임시 토픽은 직접 만든다.
- controller quorum은 정적 voters(`controller.quorum.voters`)로 정한다. 노드 ID는 서버 이름의 숫자다.

## Spark

- `spark-env.sh`: `JAVA_HOME`, `SPARK_LOCAL_IP`(노드의 사설 IP. 서버에 실제 할당된 IP인지 확인한다), `SPARK_WORKER_CORES`(`nproc`), `SPARK_WORKER_MEMORY`, `SPARK_DAEMON_MEMORY`
- 한 VM에 Master, Worker, ZooKeeper가 함께 올라가므로 Worker 메모리는 전체 RAM에서 OS 몫(1GiB), Master·Worker 데몬 메모리, ZooKeeper heap을 뺀 값으로 계산한다.
- PySpark를 지원한다. `spark-env.sh`의 `PYSPARK_PYTHON`, `PYSPARK_DRIVER_PYTHON`에 Python 3.12를 지정한다. Spark 4.x가 Python 3.10 이상을 요구한다. Ubuntu 24.04는 시스템 `python3`가 3.12라 그대로 쓰고, AL2023은 시스템 Python이 3.9이므로 `python3.12`를 따로 설치하되 시스템 Python은 바꾸지 않는다.
- Standalone 모드는 Python 애플리케이션의 cluster mode를 지원하지 않으므로 Python 작업은 client mode로 실행된다. 작업을 제출한 서버(드라이버)가 Spark 노드와 직접 통신해야 하고, 드라이버와 Spark 노드의 Python 마이너 버전이 같아야 한다. 업무 작업의 제출 위치는 별도 결정 사항이다. 역할 자체의 검증 작업은 첫 Spark 서버에서 제출한다. Backend 등 다른 서버에서 업무 작업을 제출하면 Python·Spark 클라이언트와 Driver 통신 경로도 준비해야 한다.
- Kafka 커넥터, MySQL JDBC 드라이버, MongoDB Spark 커넥터 JAR을 Spark 노드에 미리 설치한다 (11장). 서비스가 쓰는 Python 패키지(pandas 등)는 설치하지 않는다.

현재 Spark 포트는 Master RPC 7077·내부 Master UI 8080, Worker RPC 7100, Driver 7078–7094·BlockManager 7079–7095다. 작업의 spark.port.maxRetries는 16이고 Master·Worker 데몬은 0이다. ZooKeeper 클러스터는 2181·2888·3888을 사용한다. Worker UI 8081의 원격 공개 SG 규칙은 없다. [Spark 설정 지도](../platform/platform-routing/roles/spark/README.md#프라이빗-서버의-통신-포트)를 참고한다.

## Frontend / Backend

- 실제 웹 서비스와 비즈니스 로직이 올라갈 영역이라 인프라 자동화에서 서비스 내용은 정의하지 않는다. 공통 보안·사용자·방화벽까지만 적용하고 애플리케이션 런타임은 범위 밖이다. 단, Backend에는 서비스가 쓸 수 있도록 MySQL Router를 설치한다 (설치까지만).
- 인프라 접근이 막히지 않도록 방화벽 허용 관계만 미리 반영해 둔다.

---

# 6. 공통 보안 (모든 서버)

- sshd: 키 인증만 허용(비밀번호 인증 금지), root 로그인 금지
- 팀원 전원에게 비밀번호 없는 sudo 허용 (키 인증만 쓰므로 비밀번호가 없음)
- 시간 동기화: `chrony` 서비스를 활성화하고 부팅 시 자동 시작한다. 시간원은 Amazon Time Sync Service(`169.254.169.123`)이며, Amazon Linux 2023 기본 설정이 이미 이 주소를 쓴다(AWS 공식 문서). AL2023은 기본값을 유지하고 동작만 검증한다. Ubuntu 24.04는 기본 시간원이 Ubuntu NTP 풀이라서 `chrony`에 이 소스를 추가한다(풀은 예비로 남고, `^* 169.254.169.123`으로 선택됨을 검증한다).
- 시간대는 UTC로 통일한다.
- 시간 동기화는 클러스터 서비스(MySQL, MongoDB, Kafka, Spark, ZooKeeper)보다 먼저 적용한다.
- 시간 검증: `timedatectl`로 동기화 상태(`System clock synchronized: yes`)와 시간대(UTC), `chronyc sources`(`^* 169.254.169.123`)와 `chronyc tracking`(`Leap status: Normal`)으로 동기화 정상 여부를 확인한다.
- Bastion은 `AllowTcpForwarding` 허용 (ProxyJump용)
- `users`의 계정과 공개키 등록

---

# 7. 서비스 인증과 Secret

- Monitoring 수집용 `monitor` 사용자는 읽기 전용이다. 개인키는 Monitoring 서버에만 두고, 공개키를 모든 서버에 등록한다.
- MySQL과 MongoDB는 로그인을 필수로 한다. Kafka, Spark, ZooKeeper는 인증을 두지 않고 방화벽과 Bastion 경유로만 보호한다. 모든 서비스에서 TLS는 쓰지 않는다.
- DB 계정은 MySQL 6종(`root`, `dev`, `replication`, `monitor`, `failover`, `router`), MongoDB 3종이다. `failover`는 MySQL ReplicaSet을 관리하고 failover를 수행하는 원격 관리 계정으로, `root`를 서버 안에서만 쓰도록 유지하기 위해 따로 둔다. MongoDB는 `root`(관리자), `dev`(읽기/쓰기), `monitor`(모니터링 권한)만 쓰고 `replication`과 `failover`는 없다 (멤버 간 인증은 keyfile, 장애 시 선출은 MongoDB가 자동 처리).
- 팀원별 계정은 DB가 아니라 서버 OS 계정(`users`)에만 둔다. DB 계정 이름과 역할은 YAML에, 비밀번호는 Vault에 둔다.
- MySQL 계정의 접속 허용 출처는 `%`를 쓰지 않고 IP로 한정한다.
  - `dev`: YAML의 Backend, Spark, Bastion IP (팀원이 Bastion 터널로 접속하면 MySQL에는 Bastion IP로 보인다). 업무 DB 권한은 전역으로 주고 시스템 스키마(`mysql`, `sys`)는 부분 revoke로 뺀다 (`partial_revokes`). 계정·권한 정보를 읽거나 고칠 수 없다.
  - `replication`: MySQL 노드
  - `failover`: MySQL 노드와 Bastion. 자동 failover를 Monitoring에서 구현하면 그때 Monitoring을 추가한다.
  - `router`: Backend IP. MySQL Router가 ReplicaSet에 접속하는 전용 계정으로, 메타데이터 읽기와 라우터 등록 권한만 가진다(AdminAPI `setupRouterAccount`로 만들며 ReplicaSet일 때만 있다). Backend에 전체 관리 권한 계정(`failover`)을 열지 않기 위해 따로 둔다.
  - `monitor`: `localhost`. Monitoring이 SSH로 서버에 접속해 서버 안에서 조회한다.
  - `root`: `localhost`
- 모니터링용 DB 계정(MySQL, MongoDB)은 읽기 전용이다. 비밀번호는 Monitoring 서버에 소유자만 읽을 수 있는 파일로 둔다.
- MongoDB keyfile은 Vault에 두고 Replica Set 3대에 동일하게 배포한다.
- Vault 비밀번호는 로컬 파일(`aws-platform/platform/.vault_pass`, 커밋하지 않음)로 전달한다. Secret은 `inventory/group_vars/all/vault.yml`에 암호화해 두며 형식은 `vault.example.yml`에 있다.
- Vault 대상: DB 계정 비밀번호, MongoDB keyfile, `monitor` SSH 개인키. Vault에 두지 않는 것: 팀원 공개키(YAML), Ansible용 개인키의 로컬 경로.

---

# 8. 방화벽

각 서버의 호스트 방화벽은 입력 YAML과 아래 **역할 간 허용 관계**로 자동 생성한다. 허용 관계는 코드에 한 번만 정의하고, Ansible이 역할(그룹)을 실제 IP로 치환해 허용 대상 외에는 모두 차단(default deny)한다. 서버 추가나 IP 변경 시 YAML만 고쳐 재실행한다.

| 대상 | 접근 허용 |
|---|---|
| 모든 서버 SSH | Bastion, Monitoring |
| Bastion SSH | 호스트 방화벽은 SSH 키 접속 허용; 외부 출처 제한은 AWS admin CIDR 규칙도 적용 |
| Bastion Proxy | proxy_enabled일 때 프로젝트 VPC CIDR에서 TCP 3128 |
| Frontend | 외부 전체 (80/443만) |
| Backend | Frontend, Spark, Bastion |
| MySQL | Backend, Spark, Bastion, MySQL 노드끼리 |
| MongoDB | Backend, Spark, Bastion, MongoDB 노드끼리 |
| Kafka | Backend, Spark, Bastion, Kafka 노드끼리 |
| Spark | Backend, Bastion, Spark 노드끼리 |

- 역할별 서비스 허용 출처는 YAML 서버 목록의 IP로 한정한다. Bastion Proxy 3128은 예외적으로 proxy 설정의 프로젝트 VPC CIDR을 사용한다. AWS SG의 서비스 포트 제한과 호스트 방화벽의 역할별 허용 범위를 구분한다. game·ad의 전용 애플리케이션 규칙은 현재 없다.
- 포트를 지정하지 않은 규칙(위 표의 역할 간 허용, 클러스터 노드끼리의 허용)은 SSH(22)를 제외한 모든 포트를 허용한다. SSH는 첫 행의 규칙(Bastion, Monitoring)으로만 허용한다.
- 팀원이 개발자 PC에서 Bastion SSH 터널을 통해 DB, Kafka, Spark UI에 직접 접속할 수 있도록 해당 서버에서 Bastion의 접근을 허용한다.
- 인바운드만 제한하고 아웃바운드는 전부 허용한다.
- Spark가 Kafka를 직접 읽고 결과를 MySQL/MongoDB에 직접 쓰는 구현이 막히지 않도록 Spark의 접근을 허용해 둔다 (구현 방식은 미확정).
- 구현 중 허용 규칙이 바뀔 수 있으므로, 허용 관계는 서비스 role 안에 흩어놓지 않고 한 곳의 데이터로만 정의한다. 방화벽 role은 이 데이터를 읽어 원하는 규칙 전체를 선언하고 그 외는 제거한다 (규칙 추가만 하지 않음).
- 도구: `nftables` 규칙 파일. 전용 테이블 하나만 관리하고(다른 도구의 규칙은 건드리지 않음), 파일을 템플릿으로 배포해 `nft -f`로 원자적으로 교체한다. 부팅 때도 같은 파일을 로드한다.
- 적용 순서: Bastion SSH 허용 → 연결 검증 → default deny (Ansible 자신의 접속이 끊기지 않게). 구현은 SSH 허용 규칙을 포함한 규칙 전체를 한 번에 원자적으로 적용한 뒤 새 SSH 연결을 확인하고, 확인되지 않으면 일정 시간 뒤 방화벽 테이블을 지워 접속을 복구한다. 새 연결이 확인된 규칙만 부팅 때 로드되는 정식 파일이 된다.
- Bastion이거나 Bastion이 없는 인벤토리(작은 구성 테스트, 직접 접속)는 SSH를 모든 출처에 허용한다 (키 인증만). 직접 접속하는 서버에서 SSH를 닫으면 Ansible이 잠기기 때문이다.

---

# 9. Monitoring 수집

- 수집 방식: Monitoring이 SSH로 각 서버에 접속해 직접 가져온다(pull). 서버가 보내는(push) 방식은 쓰지 않는다. 수집은 셸 스크립트로 구현하며, SSH 연결을 재사용하도록 상시 실행 루프 서비스 하나가 주기를 맡는다(일 단위 정리만 systemd timer).
- 수집 대상: 전체 서버의 시스템 리소스(CPU, 메모리, 디스크, 네트워크)와 클러스터 서비스 상태(MySQL, MongoDB, Kafka, Spark, ZooKeeper), 시스템·서비스 로그
- 수집 주기: 리소스 10초, 서비스 상태 30초, 로그(시스템·서비스 로그 모두) 10초
- heartbeat: SSH 접속 실패를 down 신호로 보고, 연속 3회 실패하면 down으로 판단한다. down으로 판단한 뒤에도 매 주기 접속을 계속 시도하며, 접속에 성공하면 up으로 되돌린다. 이후 UI를 붙일 때 이 동작에 맞춰 상태를 표시한다.
- 한 주기 안에 끝나도록 서버별로 병렬 실행하고, 접속 타임아웃을 짧게(5초 이내) 두고, SSH 연결을 재사용한다.
- 저장: Monitoring 서버에 서버·날짜별 파일로, 한 줄에 한 샘플을 `키=값` 형식으로 쌓는다. 이 파일도 아래 로그 보관과 같은 방식으로 일 단위 회전·압축한다.
- `monitor` 전용 사용자는 읽기 전용으로 둔다: `systemd-journal` 그룹, 서비스 로그 읽기 권한, MySQL·MongoDB의 읽기 전용 모니터링 계정. ZooKeeper 상태 조회에는 해당 명령 허용 설정(`4lw.commands.whitelist`)이 필요하다.

---

# 10. 로그 보관

- 로그의 원본 저장 지점은 Monitoring 서버 한 곳이다. Monitoring이 정해진 주기마다 각 서버에서 로그를 가져와 한 곳에서 관리하고, 거의 실시간으로 상태를 확인할 수 있게 한다.
- 서비스 로그 파일: `rsync`로 각 서버의 로그 폴더를 Monitoring의 수집 폴더(`/var/lib/infra-monitor/logs/<서버이름>/`)로 가져온다. 삭제 옵션 없이 새로 붙은 부분만 전송하며, 서버에는 `rsync`를 설치한다.
- 시스템 로그(journald)는 logrotate 대상이 아니다. `journalctl`의 cursor 기능으로 마지막 이후 항목만 가져와 수집 폴더에 날짜별 파일로 쌓고, 서버의 journald 보존 한도(`SystemMaxUse`)도 설정한다.
- Kafka와 Spark는 데이터 경로와 애플리케이션 로그 경로를 분리한다 (Kafka의 `log.dirs`는 데이터 경로이며 로그가 아니다). 로그 경로(`LOG_DIR`, `SPARK_LOG_DIR`)는 서비스별 로그 폴더(`/var/log/<서비스>/`)로 고정해 Monitoring이 수집한다.
- 각 서버의 logrotate는 일 단위로 회전하고 3일 보관 후 삭제한다 (서버 디스크 보호용. 원본은 이미 Monitoring에 있다).
- 하루가 지난 로그는 압축해 보관 폴더(`/var/archive/infra/<서버이름>/`)에 둔다. 이동이 아니라 압축 복사로 하고, 수집 폴더의 원본은 4일 뒤 삭제한다. 이동하면 서버에 아직 남은 파일을 `rsync`가 다시 가져오기 때문이다 (서버 3일 < 수집 폴더 4일 < 보관 폴더 14일).
- 보관 폴더는 14일이 지난 파일을 삭제한다 (디스크 보호용 기본값). Monitoring 그룹을 추가한 경우 실제 인벤토리의 수집 대상 수와 로그량에 맞춰 디스크를 준비한다. 과거 시험의 15대 수량을 현재 배포 수량으로 고정하지 않는다.
- 보관 폴더의 로그를 이후 어떻게 처리할지는 후속 과제다.

---

# 11. 소프트웨어 버전

아래 표는 기존 설계와 구현 시험에서 기록한 버전·출처다. 2026-10-05의 외부 확인 기록을 최신 버전 확인으로 해석하지 않는다. 이번 갱신에서는 로컬 역할의 설치 선언과 문서 경로를 확인했으며 외부 릴리스·지원 종료일을 다시 조회하지 않았다. 설치값과 체크섬은 역할의 defaults를 따른다.

| 대상 | 버전 | 설치 출처 | 비고 |
|---|---|---|---|
| OS | Ubuntu 24.04 LTS (기본), Amazon Linux 2023 | - | 지원 기간은 각 배포판의 공식 일정을 따른다(AL2023은 2029-06-30까지). Ubuntu AWS 이미지의 커널이 7.0이라 MongoDB를 위해 GA 커널(6.8)로 바꾼다 (14장) |
| Java | Amazon Corretto 17 | AL2023: 기본 저장소(`java-17-amazon-corretto-headless`). Ubuntu: Corretto APT 저장소(`apt.corretto.aws`, `java-17-amazon-corretto-jdk`) | Kafka, Spark, ZooKeeper 공용. `JAVA_HOME`은 두 OS 모두 `/usr/lib/jvm/java-17-amazon-corretto` |
| Kafka | 4.3.1 (Scala 2.13) | Apache 배포 tarball | 4.x 브로커는 Java 17 필요 |
| Spark | 4.2.0 | Apache 배포 tarball | Java 17/21/25, Python 3.10 이상 지원 |
| ZooKeeper | 3.9.6 | Apache 배포 tarball | Spark 4.x가 쓰는 3.9 계열 |
| MySQL | 8.4 LTS (Server, Shell, Router 모두 8.4) | AL2023: MySQL Yum 저장소(el9). Ubuntu: MySQL APT 저장소(`noble`, 컴포넌트 `mysql-8.4-lts`, `mysql-tools`) | InnoDB ReplicaSet 지원 확인 |
| MongoDB | 8.0 | AL2023: MongoDB Yum 저장소(Amazon Linux 2023용). Ubuntu: MongoDB APT 저장소(`noble/mongodb-org/8.0`) | 지원 2029-10-31까지. 9.0은 2026-09 출시라 제외. 커널 6.19 이상에서는 시작하지 않는다 (14장) |
| Python (Spark 노드) | 3.12 | AL2023: `python3.12` 패키지(시스템 3.9는 그대로). Ubuntu: 시스템 `python3`(3.12) | PySpark용 |
| Spark Kafka 커넥터 | `spark-sql-kafka-0-10_2.13` 4.2.0 | Maven Central | 의존(Spark 4.2.0 기준): `spark-token-provider-kafka-0-10_2.13` 4.2.0, `kafka-clients` 3.9.2, `commons-pool2` 2.13.1. 현재 역할 선언 참조 |
| MySQL JDBC 드라이버 | `mysql-connector-j` 9.7.0 | Maven Central | 현재 Spark JAR 설치 선언과 과거 P8 연동 시험 기록 참조 |
| MongoDB Spark 커넥터 | `mongo-spark-connector_2.13` 11.1.0 | Maven Central | Spark 4.0 이상 지원. 현재 역할은 driver·core·bson·bson-record-codec 5.1.4를 설치. P5 구현 기록 참조 |

- Kafka, Spark, ZooKeeper tarball은 체크섬(sha512)을 검증한다.
- Spark 커넥터 JAR은 구축 단계에서 Spark 노드의 JAR 폴더에 미리 설치한다. 설치 다운로드 경로 없이도 작업 제출 때 `--packages`로 Maven에서 받지 않아도 되게 하기 위함이다. 전이 의존성을 포함한 현재 JAR 목록·체크섬은 Spark 역할에 선언되어 있다. P5 구현 기록과 역할 라우팅 문서를 따르며 버전을 바꿀 때 함께 검토한다.
- Kafka는 `dlcdn.apache.org`(최신 릴리스만 남지만 빠르다) → `downloads.apache.org` → `archive.apache.org`(구형도 남지만 시험에서 약 50KB/s로 느리다) 순으로 받는다. sha512는 role에 고정해 어느 쪽이든 검증한다. ZooKeeper와 Spark도 같은 방식이다(`dlcdn`에 있음).
- MySQL은 MySQL 공식 페이지의 Yum 저장소 목록에 Amazon Linux 2023이 없고 el9 패키지를 쓴다. 기존 교안(Day 17, MySQL 8.0)도 같은 방식(`mysql80-community-release-el9` RPM)으로 AL2023에 설치했다. 8.4는 `mysql84-community-release-el9` RPM을 쓴다.
- AL2023은 저장소·GPG 키를 등록하고 /var/log/mysqld.log의 초기 root 비밀번호를 변경한다. Ubuntu는 APT 저장소와 auth_socket의 root 소켓 접속을 사용하는 별도 초기화 흐름이다. 두 OS의 초기 비밀번호 처리 방법을 섞지 않는다.
- 패치 버전은 저장소의 최신을 쓴다 (2026-10-05 시험에서 Server 8.4.11 설치). 고정이 필요하면 구현 시점에 확정한다.

---

# 12. 실행 순서

1. aws-infra에서 서버를 생성하고 Inventory로 현재 주소·키·역할을 갱신한다.
2. 프록시 활성 Ubuntu 구성에서는 Proxy로 Squid를 준비하고 prepare-proxy.yml로 HTTPS 저장소·APT 프록시·다운로드를 검사한다. site.yml도 첫 패키지 설치 전에 준비 플레이북을 import한다.
3. Bastion의 공통 보안·방화벽을 먼저 적용하고 프록시 및 새 SSH 연결이 유지되는지 확인한다. 이어 대상 서버의 공통 보안·방화벽을 적용한다.
4. MySQL·MongoDB·Kafka·ZooKeeper·Spark 역할을 실행한다. 같은 서비스의 클러스터 노드는 함께 선택한다. zookeeper만 선택하면 Spark는 설치되지 않으므로 --tags zookeeper,spark --limit spark를 사용한다.
5. 인벤토리에 있는 Frontend·Backend·Monitoring 그룹을 처리한다. Backend는 Router 설치까지이며 game·ad 앱 배포는 별도다.
6. 역할 내부의 복제·송수신·ensemble·Worker 등록·작업 검증을 확인한다. systemd active만으로 클러스터 검증 완료로 판단하지 않는다. verify 태그만 선택하면 앞 단계의 등록 변수가 없어질 수 있으므로 역할 전체 실행을 기준으로 한다.

공통 태그나 Proxy 준비만으로 DB·Kafka·Spark를 설치하지 않는다. 실제 명령·Vault 준비는 [README](../platform/README.md)를 따른다.

---

# 13. 역할별 검증 항목

- 공통: SSH 키 접속 성공, 비밀번호·root 접속 거부, 방화벽 규칙 적용, 시간 동기화 정상
- MySQL: `SELECT 1`, 복제 상태 정상 (Standalone이면 `SELECT 1`만)
- MongoDB: `dev` 계정으로 쓰기·읽기 확인. 3대 Replica Set이면 `rs.status()`의 멤버 상태(PRIMARY 1, SECONDARY 2)도 확인한다.
- Kafka: broker 연결, controller quorum, 임시 토픽을 직접 만들어(자동 생성 꺼짐) produce와 consume (ISR 3 확인)
- ZooKeeper: 상태 응답
- Spark: Master ALIVE 1·STANDBY 1, Worker 3 등록, 작은 PySpark 작업(client mode) 제출 성공
- Monitoring: 모든 서버의 리소스, 서비스 상태, 로그 수집 성공

## 수동 장애 확인

"1대 장애 허용"이라는 동작을 전체 구성이 갖춰진 뒤 사람이 한 번 확인한다. 자동 검증이 아니며 role의 완료 기준에는 포함하지 않는다. 노드 한 대(서비스 프로세스 또는 VM)를 중지하는 단일 장애만 다루고, 동시 다중 장애와 네트워크 분할은 제외한다.

- MongoDB: Primary 중지 → 새 Primary 선출 → 새 Primary에 쓰기 성공
- Kafka: 1대 중지 → `acks=all`로 produce와 consume 성공
- Spark: 활성 Master 중지 → Standby가 Active로 승격(1~2분) → Worker 등록 유지
- 공통: 중지한 노드를 되돌려 정상 상태로 복귀하는지도 확인한다.

---

# 14. 구현하며 확인할 것

구현과 시험에서 확인된 항목은 지웠다(결과는 구현 계획 `implementation-plan.md`에 있다). 아래는 남은 항목이다. 수집 주기, 보관 기간 같은 수치는 초기값이며 구현 후 조정할 수 있다.

- **MongoDB 8.0은 Linux 커널 6.19 이상에서 시작을 거부한다**(MongoDB 이슈 SERVER-121912, 수정 버전 없음). Ubuntu 24.04 AWS 이미지는 `linux-aws`가 HWE 커널(7.0)을 가리켜 그대로는 MongoDB가 뜨지 않으므로, `mongodb` role이 GA 커널(`linux-aws-lts-24.04`, 6.8)로 바꾸고 HWE 커널을 지운 뒤 재부팅한다(커널이 기준 미만이면 아무것도 하지 않는다). MongoDB가 새 커널을 지원하면 이 단계를 뺄 수 있다.
- Ubuntu의 MySQL Router는 AppArmor 프로파일 때문에 임의 경로(예: `/tmp`)에 bootstrap할 수 없고 기본 경로(`/etc/mysqlrouter`, 서비스 `mysqlrouter`)를 쓴다.
- 작은 VM(`t3a.nano`, RAM 약 418MiB)에서는 `dnf`가 메모리 부족으로 종료된다. 패키지 설치가 필요한 단계(`nftables` 등)는 1GiB 이상의 VM에서 한다(Spark 노드는 4GiB 이상).
- MySQL 패치 버전 고정 (지금은 저장소의 최신을 쓴다)
- MongoDB 8.0의 메모리 할당기(tcmalloc) 권장 설정(`transparent_hugepage` 등)은 적용하지 않았다. 실제 부하를 보고 정한다.
- 설계의 `replication` 계정은 AdminAPI가 복제용 계정을 따로 만들어 쓰이지 않는다. 필요 없으면 정리한다.
- Spark 작업 제출 서버(드라이버)의 Python 마이너 버전을 Spark 노드(3.12)와 맞추는 일
- 로그 수집: `rsync`가 쓰는 중인 파일을 가져올 때 마지막 줄이 잘리는지(다음 주기에 이어서 받는다). 서버가 많거나 로그가 커졌을 때의 `rsync` 부담

---

# 15. 후속 과제

- game·ad 등 애플리케이션 통신 규칙과 외부 Driver 경로 확정. 기본 DB·Kafka·Spark·ZooKeeper 포트는 현재 코드에 반영되어 있다.
- Monitoring UI
- 보관된 로그의 후처리
- MySQL 자동 failover (Bastion 또는 Monitoring에서 상태를 확인해 실행)
- Spark 작업 제출 위치 확정 (Backend에서 제출하면 Backend의 Python·Spark 클라이언트 준비는 서비스 영역)
