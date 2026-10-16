# roles/mysql/templates/configure-instance.js.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/templates/configure-instance.js.j2)

## 역할

가입 전에 생성한 failover 관리 계정으로 신규 인스턴스의 사설 IP·MySQL 포트에 접속한다. classic MySQL 프로토콜(scheme=mysql)을 명시하며, checkInstanceConfiguration의 상태가 ok가 아닐 때만 같은 접속 정보로 configureInstance(restart=true)를 호출한다.

root@localhost 접속은 다른 멤버에서 관리할 수 있는 계정 조건을 충족하지 못해 실제 사전 검사에서 거부됐다. 관리 계정 생성은 root 로컬 소켓으로 유지하고 이 템플릿의 사전 구성 접속만 변경했다. failover의 비밀번호는 Vault에서 가져오며 허용 출처는 [관리 계정 SQL](admin-accounts.sql.j2.md)의 MySQL 노드·Bastion IP를 따른다.

## 템플릿 입력

Jinja 출력식이며 Python 심볼 참조가 아니다. 루프·macro의 로컬 변수도 포함한다.

```jinja
{{ vault_mysql_passwords.failover | to_json }}
{{ ip | to_json }}
{{ mysql_port }}
```

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
