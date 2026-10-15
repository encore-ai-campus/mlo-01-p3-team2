# roles/mongodb/tasks/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mongodb/tasks/main.yml)

## 역할

Secret·RAM 캐시·URI를 계산하고 OS별 설치·데이터 디렉터리 소유권·인증·초기화·계정·검증을 연결한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 5 | Secret 확인 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 19 | 역할 내부 값 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 26 | 접속 주소 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 31 | OS별 변수 로드 | ansible.builtin.include_vars | {{ ansible_facts['distribution'] &#124; lower }}.yml | 상위 block/play 조건도 확인 |
| 34 | 커널 호환 (Ubuntu) | ansible.builtin.include_tasks | kernel-debian.yml | ansible_facts['os_family'] == 'Debian' |
| 38 | MongoDB 저장소 등록 | ansible.builtin.include_tasks | repo-{{ ansible_facts['os_family'] &#124; lower }}.yml | 상위 block/play 조건도 확인 |
| 41 | 패키지 설치 | ansible.builtin.include_role | name=pkg; tasks_from=install; pkg_names={{ mongodb_packages }} | 상위 block/play 조건도 확인 |
| 50 | 데이터 디렉터리 소유권 설정 | ansible.builtin.file | path={{ mongodb_data_dir }}; state=directory; owner={{ mongodb_user }}; group={{ mongodb_group }}; mode=0755 | 상위 block/play 조건도 확인 |
| 58 | keyfile 배포 | ansible.builtin.copy | dest={{ mongodb_keyfile }} | mongodb_replset |
| 69 | MongoDB 설정 배포 | ansible.builtin.template | src=mongod.conf.j2; dest=/etc/mongod.conf | 상위 block/play 조건도 확인 |
| 79 | 설정 반영 | ansible.builtin.meta | flush_handlers | 상위 block/play 조건도 확인 |
| 82 | mongod 활성화 | ansible.builtin.service | name=mongod; state=started | 상위 block/play 조건도 확인 |
| 88 | mongod 응답 대기 | ansible.builtin.wait_for | port={{ mongodb_port }} | 상위 block/play 조건도 확인 |
| 95 | root 계정 확인 | ansible.builtin.command | mongosh --nodb --quiet | mongodb_is_first |
| 108 | Replica Set 초기화와 root 계정 생성 | ansible.builtin.command | mongosh --nodb --quiet | mongodb_is_first and 'INFRA_ROOT_MISSING' in mongodb_root_check.stdout |
| 119 | dev, monitor 계정 | ansible.builtin.command | mongosh --nodb --quiet | mongodb_is_first |
| 132 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 데이터 경로와 EBS 경계

패키지 설치 후, keyfile·mongod 설정과 서비스 시작 전에 mongodb_data_dir 디렉터리를 만들거나 기존 디렉터리의 소유자·그룹·모드를 맞춘다. 별도 EBS가 해당 경로에 미리 마운트된 경우 MongoDB 서비스 계정에 쓰기 권한을 주는 단계다. OS별 경로·계정은 아래 vars 문서에서 찾는다.

이 작업에는 recurse가 없으므로 하위 파일 전체의 소유권을 재귀적으로 변경하지 않는다. 디스크 포맷·마운트·fstab 등록·기존 데이터 이전·마운트 여부 검사는 수행하지 않는다. 별도 데이터 EBS를 사용할 때는 이 역할을 실행하기 전에 올바른 경로에 마운트해야 한다.

## 함께 볼 파일

- [roles/mongodb/tasks/kernel-debian.yml](kernel-debian.yml.md)
- [roles/mongodb/tasks/repo-debian.yml](repo-debian.yml.md)
- [roles/mongodb/tasks/repo-redhat.yml](repo-redhat.yml.md)
- [roles/mongodb/tasks/verify.yml](verify.yml.md)
- [roles/mongodb/templates/accounts.js.j2](../templates/accounts.js.j2.md)
- [roles/mongodb/templates/bootstrap.js.j2](../templates/bootstrap.js.j2.md)
- [roles/mongodb/templates/mongod.conf.j2](../templates/mongod.conf.j2.md)
- [roles/mongodb/vars/amazon.yml](../vars/amazon.yml.md)
- [roles/mongodb/vars/ubuntu.yml](../vars/ubuntu.yml.md)
- [roles/pkg/tasks/install.yml](../../pkg/tasks/install.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
