# inventory/hosts.example.yml

[탐색 시작점](../../ROUTING-README.md) · [영역 안내](README.md) · [원본 파일](../../../inventory/hosts.example.yml)

## 역할

MySQL 3노드와 로컬 Router 대상 game 그룹을 포함한 수동 인벤토리 형식 예시다. 실제 EC2 생성이나 완성된 전체 서비스 배치를 뜻하지 않는다.

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../verification.md)에서 범위를 확인한다.
