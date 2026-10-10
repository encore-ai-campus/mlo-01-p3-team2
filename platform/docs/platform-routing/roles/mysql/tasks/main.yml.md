# roles/mysql/tasks/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/tasks/main.yml)

## 역할

Secret 검증, RAM 기반 버퍼·노드 ID, 설치·root 인증·계정 해시·ReplicaSet 구성을 연결한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 4 | OS별 변수 로드 | ansible.builtin.include_vars | {{ ansible_facts['distribution'] &#124; lower }}.yml | 상위 block/play 조건도 확인 |
| 7 | Secret 확인 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 19 | 역할 내부 값 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 27 | 저장소 등록 (repo.yml) | ansible.builtin.import_tasks | repo.yml | 상위 block/play 조건도 확인 |
| 30 | 패키지 설치 | ansible.builtin.include_role | name=pkg; tasks_from=install; pkg_names={{ mysql_packages }} | 상위 block/play 조건도 확인 |
| 39 | 설정 디렉터리 | ansible.builtin.file | path=/etc/my.cnf.d; state=directory | ansible_facts['os_family'] == 'RedHat' |
| 46 | 설정 디렉터리 포함 | ansible.builtin.lineinfile | path=/etc/my.cnf | ansible_facts['os_family'] == 'RedHat' |
| 55 | MySQL 설정 배포 | ansible.builtin.template | src=infra.cnf.j2; dest={{ mysql_config_file }} | 상위 block/play 조건도 확인 |
| 64 | mysqld 활성화 | ansible.builtin.service | name={{ mysql_service }}; state=started | 상위 block/play 조건도 확인 |
| 71 | 설정 반영 | ansible.builtin.meta | flush_handlers | 상위 block/play 조건도 확인 |
| 74 | mysqld 응답 대기 | ansible.builtin.command | mysqladmin -S {{ mysql_socket }} ping | 상위 block/play 조건도 확인 |
| 83 | root 비밀번호 설정 | ansible.builtin.include_tasks | root-password-{{ ansible_facts['os_family'] &#124; lower }}.yml | 상위 block/play 조건도 확인 |
| 89 | 쓰기 가능 여부 확인 | ansible.builtin.command | mysql -uroot -S {{ mysql_socket }} -N -e "SELECT @@global.super_read_only | 상위 block/play 조건도 확인 |
| 100 | 계정 SQL 해시 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | mysql_super_read_only.stdout == '0' |
| 106 | 적용된 계정 SQL 해시 조회 | ansible.builtin.slurp | src={{ mysql_accounts_stamp }} | mysql_super_read_only.stdout == '0' |
| 113 | 계정 생성과 권한 부여 | ansible.builtin.command | mysql -uroot -S {{ mysql_socket }} | 원본의 목록 또는 여러 줄 조건 확인 |
| 126 | 적용한 계정 SQL 해시 기록 | ansible.builtin.copy | dest={{ mysql_accounts_stamp }} | mysql_super_read_only.stdout == '0' |
| 136 | ReplicaSet 구성 | ansible.builtin.command | mysqlsh --js --no-wizard --quiet-start=2 | mysql_is_primary and mysql_secondary_ips &#124; length > 0 |
| 145 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/mysql/tasks/repo.yml](repo.yml.md)
- [roles/mysql/tasks/root-password-debian.yml](root-password-debian.yml.md)
- [roles/mysql/tasks/root-password-redhat.yml](root-password-redhat.yml.md)
- [roles/mysql/tasks/verify.yml](verify.yml.md)
- [roles/mysql/templates/accounts.sql.j2](../templates/accounts.sql.j2.md)
- [roles/mysql/templates/infra.cnf.j2](../templates/infra.cnf.j2.md)
- [roles/mysql/templates/replicaset.js.j2](../templates/replicaset.js.j2.md)
- [roles/mysql/vars/amazon.yml](../vars/amazon.yml.md)
- [roles/mysql/vars/ubuntu.yml](../vars/ubuntu.yml.md)
- [roles/pkg/tasks/install.yml](../../pkg/tasks/install.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
