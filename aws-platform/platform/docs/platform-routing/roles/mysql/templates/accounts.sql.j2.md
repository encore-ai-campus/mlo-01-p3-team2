# roles/mysql/templates/accounts.sql.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/templates/accounts.sql.j2)

## 역할

현재 Primary에서 failover·dev·replication·monitor 계정과 권한을 변경해 모든 멤버에 복제한다. dev 출처에 game을 포함한다.

## 템플릿 입력

Jinja 출력식이며 Python 심볼 참조가 아니다. 루프·macro의 로컬 변수도 포함한다.

```jinja
{{ user }}
{{ host }}
{{ password }}
{{ account('failover', h, pw.failover) }}
{{ h }}
{{ account('dev', h, pw.dev) }}
{{ mysql_dev_privileges }}
{{ schema }}
{{ account('replication', h, pw.replication) }}
{{ account('monitor', 'localhost', pw.monitor) }}
```

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
