# mysql: MySQL 설치·계정·InnoDB ReplicaSet

[탐색 시작점](../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

mysql 그룹. 첫 번째 노드를 초기 Primary로 취급한다.

계정 권한은 accounts.sql.j2, ReplicaSet 구성·Router 계정은 replicaset.js.j2, OS 차이는 vars와 root-password-*에서 찾는다.

## 현재 작업 흐름

Secret·내부 값 → OS별 저장소·설치 → 설정·시작 → OS별 root 인증 → 계정 SQL 해시 → ReplicaSet → 검증

## 구현 조건

문서상 지원 대수는 1 또는 2대지만 구현은 Secondary가 있으면 ReplicaSet을 구성한다. 대수 제한 자체를 검사하는 assert는 없다. SQL이 같으면 해시 stamp로 재적용을 생략한다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/mysql/defaults/main.yml | [main.yml](defaults/main.yml.md) | MySQL 설치·계정·InnoDB ReplicaSet의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/mysql/handlers/main.yml | [main.yml](handlers/main.yml.md) | notify로 요청한 서비스 reload/restart를 처리한다. 호출 작업의 flush_handlers 위치도 함께 확인한다. |
| roles/mysql/tasks/main.yml | [main.yml](tasks/main.yml.md) | Secret 검증, RAM 기반 버퍼·노드 ID, 설치·root 인증·계정 해시·ReplicaSet 구성을 연결한다. |
| roles/mysql/tasks/repo-debian.yml | [repo-debian.yml](tasks/repo-debian.yml.md) | mysql_apt_repo와 GPG 키로 pkg/apt_repo를 호출한다. |
| roles/mysql/tasks/repo-redhat.yml | [repo-redhat.yml](tasks/repo-redhat.yml.md) | RPM GPG 키 등록 여부를 확인하고 MySQL Server·Tools Yum 저장소를 등록한다. |
| roles/mysql/tasks/repo.yml | [repo.yml](tasks/repo.yml.md) | OS별 MySQL 변수를 로드하고 repo-debian 또는 repo-redhat 작업으로 분기한다. backend도 재사용한다. |
| roles/mysql/tasks/root-password-debian.yml | [root-password-debian.yml](tasks/root-password-debian.yml.md) | root의 auth_socket 여부를 확인해 비밀번호 정책 컴포넌트와 caching_sha2_password를 설정한다. 비기본 노드는 변경 시 GTID·바이너리 로그를 초기화한다. |
| roles/mysql/tasks/root-password-redhat.yml | [root-password-redhat.yml](tasks/root-password-redhat.yml.md) | Vault 비밀번호 접속이 실패하면 오류 로그의 임시 root 비밀번호로 변경한다. 비기본 노드는 변경 시 GTID·바이너리 로그를 초기화한다. |
| roles/mysql/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | dev 접속·시스템 스키마 접근 거부, ReplicaSet AVAILABLE·ONLINE, Backend IP에 한정된 Router 계정을 확인한다. |
| roles/mysql/templates/accounts.sql.j2 | [accounts.sql.j2](templates/accounts.sql.j2.md) | failover·dev·replication·monitor 계정과 권한을 생성·정정한다. 비기본 노드는 sql_log_bin=0으로 failover 계정만 준비한다. |
| roles/mysql/templates/infra.cnf.j2 | [infra.cnf.j2](templates/infra.cnf.j2.md) | 사설 IP bind/report_host, server-id, GTID, partial_revokes, clone 플러그인과 버퍼 크기를 설정한다. |
| roles/mysql/templates/replicaset-status.js.j2 | [replicaset-status.js.j2](templates/replicaset-status.js.j2.md) | failover로 접속해 dba.getReplicaSet().status()를 JSON 한 줄로 출력한다. |
| roles/mysql/templates/replicaset.js.j2 | [replicaset.js.j2](templates/replicaset.js.j2.md) | failover로 접속해 ReplicaSet 생성·미가입 노드 clone 추가·Backend IP별 Router 계정을 준비한다. |
| roles/mysql/vars/amazon.yml | [amazon.yml](vars/amazon.yml.md) | Amazon Linux에서 사용할 MySQL 설치·계정·InnoDB ReplicaSet의 패키지·서비스·경로 등 역할 변수를 지정한다. |
| roles/mysql/vars/ubuntu.yml | [ubuntu.yml](vars/ubuntu.yml.md) | Ubuntu에서 사용할 MySQL 설치·계정·InnoDB ReplicaSet의 패키지·서비스·경로 등 역할 변수를 지정한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
