# site.yml

[탐색 시작점](../ROUTING-README.md) · [역할 지도](roles/README.md) · [원본 파일](../../site.yml)

## 역할

프록시·공통 보안·방화벽 → MySQL Cluster → 다른 서비스 → game:spark:backend 로컬 Router → 모니터링 순서다. MySQL과 Router play는 any_errors_fatal=true다. MySQL은 strategy=linear로 모든 노드의 준비가 끝난 뒤 구축 담당이 Cluster를 생성한다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 3 | 프록시 준비 import | ansible.builtin.import_playbook | 내부 proxy_enabled 조건 |
| 6 | 공통 보안 (Bastion) | play | 상위 조건 확인 |
| 14 | 공통 보안 (나머지 서버) | play | 상위 조건 확인 |
| 22 | 방화벽 (Bastion) | play | 상위 조건 확인 |
| 30 | 방화벽 (나머지 서버) | play | 상위 조건 확인 |
| 37 | MySQL | play | 상위 조건 확인 |
| 46 | MongoDB | play | 상위 조건 확인 |
| 53 | Kafka | play | 상위 조건 확인 |
| 61 | ZooKeeper와 Spark | play | 상위 조건 확인 |
| 70 | MySQL Router | play | 상위 조건 확인 |
| 79 | Monitoring | play | 상위 조건 확인 |

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](verification.md)에서 범위를 확인한다.
