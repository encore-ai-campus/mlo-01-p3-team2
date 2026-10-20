# Primary의 전체 계정 구성

[원본 파일](../../../../../roles/mysql/tasks/accounts.yml) · [MySQL 역할](../README.md)

기존 전체 계정 SQL·해시 처리를 유지한다. Router 메타데이터 계정은 공통 router-accounts.yml로 연결해 단독 실행과 중복 구현하지 않는다.

| 원본 행 | 작업 이름 |
| --- | --- |
| 3 | 계정 SQL 계산 |
| 8 | 적용된 계정 SQL 해시 조회 |
| 14 | 계정 생성과 권한 부여 |
| 24 | 적용한 계정 SQL 해시 기록 |
| 32 | Router 공통 메타데이터 계정 준비 |

YAML·Jinja는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. Ansible 문법·로컬 모의 검사를 따로 수행한다.
