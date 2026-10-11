# roles/backend/defaults/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/backend/defaults/main.yml)

## 역할

로컬 Router·클라이언트 패키지, 기본 설정 경로·서비스·관리 해시·loopback RW/RO 포트를 정의한다.

## 설정 탐색

| 원본 행 | 키 | 선언값 |
| --- | --- | --- |
| 3 | backend_packages | [mysql-router-community, mysql-community-client] |
| 4 | backend_router_user | mysqlrouter |
| 5 | backend_router_service | mysqlrouter |
| 6 | backend_router_config | /etc/mysqlrouter/mysqlrouter.conf |
| 7 | backend_router_stamp | /etc/mysqlrouter/infra-bootstrap.sha256 |
| 8 | mysql_cluster_name | infra |
| 9 | mysql_port | 3306 |
| 10 | mysql_router_bind_address | 127.0.0.1 |
| 11 | mysql_router_rw_port | 6446 |
| 12 | mysql_router_ro_port | 6447 |
| 13 | mysql_router_source_groups | [game, spark, backend] |
| 14 | backend_no_log | true |

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
