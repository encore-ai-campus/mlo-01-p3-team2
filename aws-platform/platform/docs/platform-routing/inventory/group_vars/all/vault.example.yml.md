# inventory/group_vars/all/vault.example.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../../README.md) · [원본 파일](../../../../../inventory/group_vars/all/vault.example.yml)

## 역할

기존 MySQL 비밀번호 6개 형식을 유지하며 failover는 Cluster 관리, router는 앱 서버별 메타데이터 계정임을 설명한다. 실제 Secret은 없다.

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
