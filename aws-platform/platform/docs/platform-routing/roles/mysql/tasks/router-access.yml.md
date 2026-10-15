# Router 단독 실행의 계정 준비

[원본 파일](../../../../../roles/mysql/tasks/router-access.yml) · [MySQL 역할](../README.md)

MySQL 전체 그룹을 검사하고 현재 ONLINE Primary에서만 Router 대상의 신규 dev 계정과 메타데이터 계정을 준비한다. MySQL 서비스·복제·패키지를 변경하지 않는다. 중복 그룹의 호스트는 한 번만 처리한다. 성공한 MySQL 호스트에는 mysql_router_access_ready를 기록한다.

| 원본 행 | 작업 이름 |
| --- | --- |
| 3 | OS별 MySQL 경로 로드 |
| 6 | Router 계정 준비 입력 확인 |
| 21 | 공통 Router 대상 계산 |
| 25 | Router 출처 IP 확인 |
| 32 | 현재 ONLINE 멤버 역할 조회 |
| 43 | 단일 Primary와 ONLINE 멤버 확인 |
| 50 | 현재 Primary에서 Router 접속 계정 준비 |
| 54 | 없는 Router 클라이언트 계정 생성 |
| 62 | Router 공통 메타데이터 계정 준비 |
| 65 | Router 계정 준비 완료 표시 |

YAML·Jinja는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. Ansible 문법·로컬 모의 검사를 따로 수행한다.
