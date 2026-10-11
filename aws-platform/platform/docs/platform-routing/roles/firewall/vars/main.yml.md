# roles/firewall/vars/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/firewall/vars/main.yml)

## 역할

SSH 출처와 그룹 간 허용 관계를 정의한다. MySQL의 허용 출처에 로컬 Router가 실행되는 game 그룹을 포함한다. Kafka의 허용 출처에 평탄화 노드가 속하는 consumer 그룹을 추가한다. 기존 from 규칙은 SSH 22를 제외한 포트를 허용하며, AWS SG의 consumer_kafka는 TCP 9092로 제한한다.

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
