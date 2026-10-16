# inventory/group_vars/all/mysql.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../../README.md) · [원본 파일](../../../../../inventory/group_vars/all/mysql.yml)

## 역할

MySQL 역할과 Router 역할이 공유하는 Cluster 이름·MySQL 포트·Router 출처 그룹·loopback 주소·RW/RO 포트를 정의한다.

## 설정 탐색

| 원본 행 | 키 | 선언값 |
| --- | --- | --- |
| 3 | mysql_cluster_name | infra |
| 4 | mysql_port | 3306 |
| 5 | mysql_router_source_groups | [game, ad, spark, mysql, backend] |
| 6 | mysql_router_bind_address | 127.0.0.1 |
| 7 | mysql_router_rw_port | 6446 |
| 8 | mysql_router_ro_port | 6447 |

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
