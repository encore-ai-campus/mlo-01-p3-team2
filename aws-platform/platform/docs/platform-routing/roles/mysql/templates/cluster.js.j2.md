# roles/mysql/templates/cluster.js.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/templates/cluster.js.j2)

## 역할

기존 Cluster 조회 또는 최초 생성, 실제 Primary 접속, 신규 노드 clone 추가, OFFLINE/(MISSING) 멤버 증분 재가입을 수행한다.

## 템플릿 입력

Jinja 출력식이며 Python 심볼 참조가 아니다. 루프·macro의 로컬 변수도 포함한다.

```jinja
{{ vault_mysql_passwords.failover | to_json }}
{{ hostvars[h].ip | to_json }}
{{ mysql_port }}
{{ mysql_cluster_name | to_json }}
{{ mysql_cluster_auto_rejoin_tries }}
{{ mysql_cluster_allow_clone_data_loss | bool | to_json }}
```

## 동작과 제한

단일 Primary, communicationStack=MYSQL, manualStartOnBoot=false, autoRejoinTries=3(기본), exitStateAction=READ_ONLY, consistency=BEFORE_ON_PRIMARY_FAILOVER로 생성한다. MYSQL 스택은 MySQL 수신 포트를 재사용한다. 기존 메타데이터가 있는 신규 후보·인벤토리 밖의 멤버·정족수 상실·ERROR 상태는 중단한다. 미가입 후보의 업무 데이터는 mysql_cluster_allow_clone_data_loss=false(기본)로 보호한다. true는 clone 데이터 폐기를 허용하는 명시적 운영 입력이다. 기존 멤버 재가입은 incremental만 사용하며 강제 정족수 복구나 전체 중단 재부팅은 수행하지 않는다.

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
