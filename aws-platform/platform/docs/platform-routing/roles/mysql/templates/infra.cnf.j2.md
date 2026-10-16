# roles/mysql/templates/infra.cnf.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/templates/infra.cnf.j2)

## 역할

사설 IP·포트·server-id·GTID·ROW 바이너리 로그·log_replica_updates·clone·버퍼를 설정한다. Group Replication 동적 설정은 AdminAPI의 mysqld-auto.cnf에 맡긴다.

## 템플릿 입력

Jinja 출력식이며 Python 심볼 참조가 아니다. 루프·macro의 로컬 변수도 포함한다.

```jinja
{{ ip }}
{{ mysql_port }}
{{ mysql_server_id }}
{{ mysql_buffer_pool_mb }}
```

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
