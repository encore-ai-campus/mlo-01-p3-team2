# roles/mysql/tasks/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/tasks/main.yml)

## 역할

전체 MySQL 3~9대 인벤토리를 검사하고 기존 토폴로지 확인 → 설치 → 인스턴스 준비 → Cluster → 현재 Primary 계정 → 검증을 연결한다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 3 | OS별 변수 로드 | ansible.builtin.include_vars | 상위 조건 확인 |
| 6 | Secret 확인 | ansible.builtin.assert | 상위 조건 확인 |
| 18 | Cluster 인벤토리 확인 | ansible.builtin.assert | 상위 조건 확인 |
| 36 | 역할 내부 값 계산 | ansible.builtin.set_fact | 상위 조건 확인 |
| 44 | 기존 MySQL 소켓 확인 | ansible.builtin.stat | 상위 조건 확인 |
| 49 | 기존 MySQL 데이터 디렉터리 확인 | ansible.builtin.stat | 상위 조건 확인 |
| 54 | 중지된 기존 MySQL 보호 | ansible.builtin.assert | 상위 조건 확인 |
| 60 | 기존 MySQL 메타데이터 확인 | ansible.builtin.command | mysql_existing_socket.stat.exists |
| 72 | 기존 가입 여부 계산 | ansible.builtin.set_fact | 상위 조건 확인 |
| 76 | 관리되지 않는 Group Replication 확인 | ansible.builtin.assert | mysql_existing_socket.stat.exists |
| 83 | 기존 InnoDB Cluster 확인 | ansible.builtin.command | mysql_has_metadata |
| 92 | 저장소 등록 (repo.yml) | ansible.builtin.import_tasks | 상위 조건 확인 |
| 95 | 패키지 설치 | ansible.builtin.include_role | 상위 조건 확인 |
| 104 | 설정 디렉터리 | ansible.builtin.file | ansible_facts['os_family'] == 'RedHat' |
| 111 | 설정 디렉터리 포함 | ansible.builtin.lineinfile | ansible_facts['os_family'] == 'RedHat' |
| 121 | 가입된 Cluster의 설정 포함 변경 제한 | ansible.builtin.assert | ansible_facts['os_family'] == 'RedHat' |
| 128 | 설정 디렉터리 포함 적용 | ansible.builtin.lineinfile | ansible_facts['os_family'] == 'RedHat' |
| 138 | MySQL 설정 변경 사전 확인 | ansible.builtin.template | 상위 조건 확인 |
| 148 | 가입된 Cluster의 설정 변경 제한 | ansible.builtin.assert | 상위 조건 확인 |
| 154 | MySQL 설정 배포 | ansible.builtin.template | 상위 조건 확인 |
| 163 | mysqld 활성화 | ansible.builtin.service | 상위 조건 확인 |
| 170 | 설정 반영 | ansible.builtin.meta | 상위 조건 확인 |
| 173 | mysqld 응답 대기 | ansible.builtin.command | 상위 조건 확인 |
| 182 | root 비밀번호 설정 | ansible.builtin.include_tasks | 상위 조건 확인 |
| 185 | 신규 인스턴스 준비 | ansible.builtin.include_tasks | not mysql_has_metadata |
| 189 | InnoDB Cluster 구성 | ansible.builtin.command | mysql_is_bootstrap |
| 198 | 현재 멤버 역할 조회 | ansible.builtin.command | 상위 조건 확인 |
| 212 | 운영 중 Primary 계산 | ansible.builtin.set_fact | 상위 조건 확인 |
| 216 | 현재 Primary에서 계정 구성 | ansible.builtin.include_tasks | mysql_is_primary |
| 220 | 검증 | ansible.builtin.import_tasks | 상위 조건 확인 |

## 동작과 제한

mysql_is_bootstrap은 인벤토리 첫 노드이며 mysql_is_primary는 ONLINE 멤버의 현재 MEMBER_ROLE로 계산한다. mysql 그룹 일부만 --limit으로 선택하면 실패한다. 기존 메타데이터가 있으면 설정 파일 변경을 적용하기 전에 중단하여 동시 재시작을 방지한다. AL2023의 설정 포함 경로 변경도 적용 전에 검사한다. 기존 데이터의 auto.cnf가 있는데 소켓이 없으면 먼저 서비스를 시작해 토폴로지를 확인하도록 중단한다. 순차 유지보수는 운영자가 별도로 수행한다.

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
