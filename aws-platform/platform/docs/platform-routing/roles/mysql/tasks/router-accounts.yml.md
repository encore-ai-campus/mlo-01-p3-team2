# 공통 Router 메타데이터 계정

[원본 파일](../../../../../roles/mysql/tasks/router-accounts.yml) · [MySQL 역할](../README.md)

MySQL 설치의 accounts.yml과 Router 단독 실행의 router-access.yml이 함께 사용한다. 동일 템플릿·호스트 집합의 해시가 같으면 계정 재설정을 생략하고 성공 후 root 전용 파일에 해시를 기록한다.

| 원본 행 | 작업 이름 |
| --- | --- |
| 3 | Router 계정 입력 계산 |
| 8 | 적용된 Router 계정 해시 조회 |
| 14 | Router 계정 구성 |
| 24 | 적용한 Router 계정 해시 기록 |

YAML·Jinja는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. Ansible 문법·로컬 모의 검사를 따로 수행한다.
