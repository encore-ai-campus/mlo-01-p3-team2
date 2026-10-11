# roles/mysql/tasks/accounts.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/tasks/accounts.yml)

## 역할

현재 Primary에서 관리·업무 계정 SQL과 Router 계정을 구성한다. 적용 해시가 같으면 재설정을 생략한다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 3 | 계정 SQL 계산 | ansible.builtin.set_fact | 상위 조건 확인 |
| 9 | 적용된 계정 SQL 해시 조회 | ansible.builtin.slurp | 상위 조건 확인 |
| 15 | 계정 생성과 권한 부여 | ansible.builtin.command | (mysql_accounts_stamp_current.content &#124; default('') &#124; b64decode) != (mysql_accounts_sql &#124; hash('sha256')) |
| 25 | 적용한 계정 SQL 해시 기록 | ansible.builtin.copy | 상위 조건 확인 |
| 33 | 적용된 Router 계정 해시 조회 | ansible.builtin.slurp | 상위 조건 확인 |
| 39 | Router 계정 구성 | ansible.builtin.command | 원본 목록 조건 확인 |
| 49 | 적용한 Router 계정 해시 기록 | ansible.builtin.copy | mysql_router_hosts &#124; length > 0 |

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
