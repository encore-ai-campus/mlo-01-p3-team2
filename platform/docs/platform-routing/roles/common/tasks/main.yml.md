# roles/common/tasks/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/common/tasks/main.yml)

## 역할

OS별 변수와 패키지를 준비하고 팀원 계정·SSH·sudo·UTC·chrony를 설정한 뒤 검증을 연결한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 2 | OS별 변수 로드 | ansible.builtin.include_vars | {{ ansible_facts['distribution'] &#124; lower }}.yml | 상위 block/play 조건도 확인 |
| 5 | 패키지 설치 | ansible.builtin.include_role | name=pkg; tasks_from=install; pkg_names={{ common_packages }} | 상위 block/play 조건도 확인 |
| 13 | 팀원 계정 생성 | ansible.builtin.user | name={{ item.name }} | 상위 block/play 조건도 확인 |
| 21 | 팀원 공개키 등록 | ansible.posix.authorized_key | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 32 | 팀원 sudo 허용 | ansible.builtin.copy | dest=/etc/sudoers.d/90-team | 상위 block/play 조건도 확인 |
| 44 | sshd 보안 설정 | block/rescue 제어 | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 46 | sshd drop-in 디렉터리 | ansible.builtin.file | path=/etc/ssh/sshd_config.d; state=directory | 상위 block/play 조건도 확인 |
| 52 | sshd 보안 설정 배포 | ansible.builtin.template | src=sshd-hardening.conf.j2; dest=/etc/ssh/sshd_config.d/00-hardening.conf | 상위 block/play 조건도 확인 |
| 61 | sshd 설정 문법 확인 | ansible.builtin.command | sshd -t | 상위 block/play 조건도 확인 |
| 66 | 깨진 sshd 설정 제거 | ansible.builtin.file | path=/etc/ssh/sshd_config.d/00-hardening.conf; state=absent | 상위 block/play 조건도 확인 |
| 71 | sshd 설정 실패 | ansible.builtin.fail | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 77 | sshd 설정 반영 | ansible.builtin.meta | flush_handlers | 상위 block/play 조건도 확인 |
| 80 | 시간대 UTC | community.general.timezone | name=UTC | 상위 block/play 조건도 확인 |
| 85 | Ubuntu 전용 설정 | ansible.builtin.include_tasks | os-debian.yml | ansible_facts['os_family'] == 'Debian' |
| 89 | chrony 활성화 | ansible.builtin.service | name={{ common_chrony_service }}; state=started | 상위 block/play 조건도 확인 |
| 96 | chrony 설정 반영 | ansible.builtin.meta | flush_handlers | 상위 block/play 조건도 확인 |
| 99 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/common/tasks/os-debian.yml](os-debian.yml.md)
- [roles/common/tasks/verify.yml](verify.yml.md)
- [roles/common/templates/sshd-hardening.conf.j2](../templates/sshd-hardening.conf.j2.md)
- [roles/common/vars/amazon.yml](../vars/amazon.yml.md)
- [roles/common/vars/ubuntu.yml](../vars/ubuntu.yml.md)
- [roles/pkg/tasks/install.yml](../../pkg/tasks/install.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
