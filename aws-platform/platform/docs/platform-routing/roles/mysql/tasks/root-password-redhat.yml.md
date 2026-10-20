# roles/mysql/tasks/root-password-redhat.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/tasks/root-password-redhat.yml)

## 역할

AL2023의 최초 임시 root 비밀번호를 Vault 값으로 바꾼다. GTID·바이너리 로그를 초기화하지 않는다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 4 | root 비밀번호가 이미 설정되었는지 확인 | ansible.builtin.command | 상위 조건 확인 |
| 13 | root 임시 비밀번호 조회 | ansible.builtin.shell | mysql_root_check.rc != 0 |
| 22 | root 비밀번호 변경 | ansible.builtin.command | mysql_root_check.rc != 0 |

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
