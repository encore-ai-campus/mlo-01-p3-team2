# roles/backend/tasks/verify.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/backend/tasks/verify.yml)

## 역할

Router 8.4 버전·RW 포트와 dev 계정으로 Router를 경유한 ONLINE Primary 접속을 확인한다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 2 | MySQL Router 버전 확인 | ansible.builtin.command | 상위 조건 확인 |
| 8 | Router 읽기 쓰기 포트 대기 | ansible.builtin.wait_for | 상위 조건 확인 |
| 15 | Router를 통한 Primary 접속 확인 | ansible.builtin.command | 상위 조건 확인 |

## 동작과 제한

쓰기 쿼리를 수행하지 않고 super_read_only=0과 현재 멤버 역할 PRIMARY를 확인한다. 실제 Primary 중단과 앱 재접속 검증은 별도 운영 검사다.

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
