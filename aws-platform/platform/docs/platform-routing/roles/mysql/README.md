# mysql: MySQL InnoDB Cluster 설치·계정·검증

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 대상과 흐름

전체 mysql 인벤토리 검사 → 기존 Cluster 확인 → 설치·root 인증 → 신규 인스턴스 준비 → Cluster 생성/가입/재가입 → 실제 Primary 계정 → 정상 상태 검증

mysql 그룹 전체 3~9대가 대상이다. 첫 노드는 구축 담당이고 현재 Primary는 Group Replication 상태로 판단한다. 기존 ReplicaSet의 자동 데이터 이전·메타데이터 삭제는 제공하지 않는다. MYSQL 통신 스택을 사용하므로 멤버 간 MySQL 포트(기본 3306)가 필요하다. 현재 배포 프로필은 mysql-1(account3), mysql-2(account5), mysql-3(account4)를 정의하지만 로컬 `inventory/hosts.current.yml`은 아직 mysql-1·mysql-2만 포함한다. Inventory 갱신은 kafka-1이 실행 중이 아니라는 검사에서 중단됐다. 새 인벤토리를 생성한 뒤 mysql 그룹에 세 노드가 모두 있는지 확인하고 이 역할을 실행한다.

## 경로별 문서

| 소스 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/mysql/defaults/main.yml | [main.yml](defaults/main.yml.md) | MySQL 8.4 저장소·버퍼·계정 출처·Cluster 이름·재가입 횟수·clone 데이터 보호 기본값을 정의한다. |
| roles/mysql/handlers/main.yml | [main.yml](handlers/main.yml.md) | 기존 OS별 저장소·서비스·설치 경로 설정을 제공한다. Cluster 구성 흐름에서 재사용한다. |
| roles/mysql/tasks/accounts.yml | [accounts.yml](tasks/accounts.yml.md) | 현재 Primary에서 관리·업무 계정 SQL과 Router 계정을 구성한다. 적용 해시가 같으면 재설정을 생략한다. |
| roles/mysql/tasks/main.yml | [main.yml](tasks/main.yml.md) | 전체 MySQL 3~9대 인벤토리를 검사하고 기존 토폴로지 확인 → 설치 → 인스턴스 준비 → Cluster → 현재 Primary 계정 → 검증을 연결한다. |
| roles/mysql/tasks/prepare-instance.yml | [prepare-instance.yml](tasks/prepare-instance.yml.md) | 메타데이터가 없는 인스턴스에 관리 계정을 복제 없이 준비하고 checkInstanceConfiguration/configureInstance로 Cluster 요구 설정을 검사·구성한다. |
| roles/mysql/tasks/repo-debian.yml | [repo-debian.yml](tasks/repo-debian.yml.md) | 기존 OS별 저장소·서비스·설치 경로 설정을 제공한다. Cluster 구성 흐름에서 재사용한다. |
| roles/mysql/tasks/repo-redhat.yml | [repo-redhat.yml](tasks/repo-redhat.yml.md) | 기존 OS별 저장소·서비스·설치 경로 설정을 제공한다. Cluster 구성 흐름에서 재사용한다. |
| roles/mysql/tasks/repo.yml | [repo.yml](tasks/repo.yml.md) | 기존 OS별 저장소·서비스·설치 경로 설정을 제공한다. Cluster 구성 흐름에서 재사용한다. |
| roles/mysql/tasks/root-password-debian.yml | [root-password-debian.yml](tasks/root-password-debian.yml.md) | Ubuntu의 auth_socket root를 caching_sha2_password로 변경한다. GTID·바이너리 로그를 초기화하지 않는다. |
| roles/mysql/tasks/root-password-redhat.yml | [root-password-redhat.yml](tasks/root-password-redhat.yml.md) | AL2023의 최초 임시 root 비밀번호를 Vault 값으로 바꾼다. GTID·바이너리 로그를 초기화하지 않는다. |
| roles/mysql/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | dev 접속·mysql 스키마 접근 거부, Cluster OK·모든 멤버 ONLINE·Primary 1대·Secondary 읽기 전용, Router 계정 출처를 검사한다. |
| roles/mysql/templates/accounts.sql.j2 | [accounts.sql.j2](templates/accounts.sql.j2.md) | 현재 Primary에서 failover·dev·replication·monitor 계정과 권한을 변경해 모든 멤버에 복제한다. dev 출처에 game을 포함한다. |
| roles/mysql/templates/admin-accounts.sql.j2 | [admin-accounts.sql.j2](templates/admin-accounts.sql.j2.md) | 가입 전 failover 관리 계정만 MySQL 노드와 Bastion IP에 한정해 로컬에 준비한다. sql_log_bin=0을 사용하고 GTID를 초기화하지 않는다. |
| roles/mysql/templates/cluster-inspect.js.j2 | [cluster-inspect.js.j2](templates/cluster-inspect.js.j2.md) | 기존 메타데이터를 getCluster로 읽어 정족수가 있는 단일 Primary Cluster인지 확인한다. 기존 ReplicaSet 오류를 신규 생성으로 처리하지 않는다. |
| roles/mysql/templates/cluster-status.js.j2 | [cluster-status.js.j2](templates/cluster-status.js.j2.md) | failover로 접속해 getCluster(name).status()를 JSON 한 줄로 출력한다. |
| roles/mysql/templates/cluster.js.j2 | [cluster.js.j2](templates/cluster.js.j2.md) | 기존 Cluster 조회 또는 최초 생성, 실제 Primary 접속, 신규 노드 clone 추가, OFFLINE/(MISSING) 멤버 증분 재가입을 수행한다. |
| roles/mysql/templates/configure-instance.js.j2 | [configure-instance.js.j2](templates/configure-instance.js.j2.md) | 가입 전에 생성한 failover 계정으로 각 노드 사설 IP·MySQL 포트에 접속하고, 요구 설정이 맞지 않을 때만 configureInstance(restart=true)를 호출한다. |
| roles/mysql/templates/infra.cnf.j2 | [infra.cnf.j2](templates/infra.cnf.j2.md) | 사설 IP·포트·server-id·GTID·ROW 바이너리 로그·log_replica_updates·clone·버퍼를 설정한다. Group Replication 동적 설정은 AdminAPI의 mysqld-auto.cnf에 맡긴다. |
| roles/mysql/templates/router-accounts.js.j2 | [router-accounts.js.j2](templates/router-accounts.js.j2.md) | 현재 Primary에서 game·spark·backend IP별 router 계정을 setupRouterAccount로 생성·갱신한다. |
| roles/mysql/vars/amazon.yml | [amazon.yml](vars/amazon.yml.md) | 기존 OS별 저장소·서비스·설치 경로 설정을 제공한다. Cluster 구성 흐름에서 재사용한다. |
| roles/mysql/vars/ubuntu.yml | [ubuntu.yml](vars/ubuntu.yml.md) | 기존 OS별 저장소·서비스·설치 경로 설정을 제공한다. Cluster 구성 흐름에서 재사용한다. |

## 운영 검증

역할 verify는 정상 구축과 연결을 검사한다. Primary 중단 후 자동 선출·Router 재접속·쓰기 성공·복귀 노드 ONLINE은 배포 환경에서 별도로 확인한다. 연결이 끊긴 트랜잭션의 처리는 앱에서 구현해야 한다. [로컬 검증](../../tests/README.md) · [검증 기록](../../verification.md)
