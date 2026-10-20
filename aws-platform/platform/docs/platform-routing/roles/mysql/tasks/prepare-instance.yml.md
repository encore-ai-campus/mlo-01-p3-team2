# roles/mysql/tasks/prepare-instance.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/tasks/prepare-instance.yml)

## 역할

메타데이터가 없는 인스턴스에 관리 계정을 복제 없이 준비하고 checkInstanceConfiguration/configureInstance로 Cluster 요구 설정을 검사·구성한다.

관리 계정 SQL은 root 로컬 소켓으로 적용한다. 이후 사전 구성은 [configure-instance 템플릿](../templates/configure-instance.js.j2.md)이 failover 계정과 해당 노드의 사설 IP·MySQL 포트로 접속해 수행한다. root@localhost는 AdminAPI의 원격 관리 계정 조건을 충족하지 않아 사전 검사에서 거부되므로 이 단계의 접속 계정으로 사용하지 않는다. 요구 설정이 부족하면 configureInstance(restart=true)를 호출하고, 다음 작업에서 mysqld 응답을 기다린다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 3 | 가입 전 관리 계정 SQL 계산 | ansible.builtin.set_fact | 상위 조건 확인 |
| 8 | 가입 전 관리 계정 SQL 해시 조회 | ansible.builtin.slurp | 상위 조건 확인 |
| 14 | 가입 전 관리 계정 준비 | ansible.builtin.command | (mysql_admin_stamp_current.content &#124; default('') &#124; b64decode) != (mysql_admin_sql &#124; hash('sha256')) |
| 24 | 가입 전 관리 계정 SQL 해시 기록 | ansible.builtin.copy | 상위 조건 확인 |
| 32 | Cluster 인스턴스 사전 구성 | ansible.builtin.command | 상위 조건 확인 |
| 40 | 사전 구성 후 mysqld 응답 대기 | ansible.builtin.command | 상위 조건 확인 |

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
