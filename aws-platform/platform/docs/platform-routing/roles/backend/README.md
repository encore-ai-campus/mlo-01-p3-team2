# backend: 대상 서버의 로컬 MySQL Router

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 대상과 흐름

입력 검사 → 저장소·패키지 → 관리 범위 확인 → bootstrap → systemd → 실제 Primary 연결 검증

site.yml의 game:ad:spark:mysql:backend가 대상이다. 역할 이름 backend는 호환성을 위해 유지하며 별도 Router EC2를 만들지 않는다. 기본 접속은 앱 → 127.0.0.1:6446 → Cluster Primary다. Spark JDBC를 수행하는 모든 실행 노드에 Router가 필요하다. 앱 런타임·앱 연결 풀·재시도 코드는 이 역할이 설치하지 않는다.

## 경로별 문서

| 소스 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/backend/defaults/main.yml | [main.yml](defaults/main.yml.md) | 로컬 Router·클라이언트 패키지, 기본 설정 경로·서비스·관리 해시·loopback RW/RO 포트를 정의한다. |
| roles/backend/tasks/main.yml | [main.yml](tasks/main.yml.md) | game·ad·spark·mysql·backend에서 Router 설치 → 관리 범위 확인 → bootstrap → 해시 기록 → systemd 서비스 → 검증을 수행한다. |
| roles/backend/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | Router 8.4 버전·RW 포트와 dev 계정으로 Router를 경유한 ONLINE Primary 접속을 확인한다. |
| roles/backend/templates/mysqlrouter.service.j2 | [mysqlrouter.service.j2](templates/mysqlrouter.service.j2.md) | mysqlrouter 전용 사용자로 기본 설정 파일을 읽고 systemd에서 시작·자동 시작·실패 시 재시작한다. |

## 운영 검증

역할 verify는 정상 구축과 연결을 검사한다. Primary 중단 후 자동 선출·Router 재접속·쓰기 성공·복귀 노드 ONLINE은 배포 환경에서 별도로 확인한다. 연결이 끊긴 트랜잭션의 처리는 앱에서 구현해야 한다. [로컬 검증](../../tests/README.md) · [검증 기록](../../verification.md)

site.yml의 Router 계정 준비 play가 완료된 뒤 설치한다. 계정 준비·실행 범위는 [최상위 지도](../../site.yml.md#router-단독-실행)를 따른다.
