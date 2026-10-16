# roles/mysql/templates/cluster-status.js.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/templates/cluster-status.js.j2)

## 역할

failover로 접속해 getCluster(name).status()를 JSON 한 줄로 출력한다.

## 템플릿 입력

Jinja 출력식이며 Python 심볼 참조가 아니다. 루프·macro의 로컬 변수도 포함한다.

```jinja
{{ vault_mysql_passwords.failover | to_json }}
{{ ip | to_json }}
{{ mysql_port }}
{{ mysql_cluster_name | to_json }}
```

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
