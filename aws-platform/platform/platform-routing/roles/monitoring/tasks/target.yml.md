# roles/monitoring/tasks/target.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/monitoring/tasks/target.yml)

## 역할

모든 대상에 monitor 사용자·출처 제한 키·읽기 권한·원격 스크립트·logrotate·journald를 구성한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | 패키지 설치 | ansible.builtin.include_role | name=pkg; tasks_from=install; pkg_names=[rsync, logrotate] | 상위 block/play 조건도 확인 |
| 11 | 그룹 목록 조회 | ansible.builtin.getent | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 15 | monitor 사용자 | ansible.builtin.user | name={{ monitor_user }} | 상위 block/play 조건도 확인 |
| 23 | monitor 공개키 등록 | ansible.posix.authorized_key | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 30 | 그룹 읽기가 필요한 로그 파일 확인 | ansible.builtin.stat | path={{ item }} | 상위 block/play 조건도 확인 |
| 36 | 로그 파일을 그룹 읽기(0640)로 | ansible.builtin.file | path={{ item.item }} | item.stat.exists |
| 45 | 원격 수집 스크립트 디렉터리 | ansible.builtin.file | path={{ monitor_remote_dir }}; state=directory | 상위 block/play 조건도 확인 |
| 53 | 리소스 수집 스크립트 | ansible.builtin.copy | src=resource.sh; dest={{ monitor_remote_dir }}/resource.sh | 상위 block/play 조건도 확인 |
| 61 | 서비스 상태 수집 스크립트 | ansible.builtin.template | src=service.sh.j2; dest={{ monitor_remote_dir }}/service.sh | 상위 block/play 조건도 확인 |
| 70 | 회전할 로그 경로 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 74 | logrotate 설정 | ansible.builtin.template | src=logrotate.j2; dest=/etc/logrotate.d/infra | monitor_server_logs &#124; length > 0 |
| 83 | logrotate 타이머 활성화 | ansible.builtin.systemd | name=logrotate.timer; state=started | 상위 block/play 조건도 확인 |
| 90 | journald 설정 디렉터리 | ansible.builtin.file | path=/etc/systemd/journald.conf.d; state=directory | 상위 block/play 조건도 확인 |
| 98 | journald 설정 | ansible.builtin.copy | dest=/etc/systemd/journald.conf.d/infra.conf | 상위 block/play 조건도 확인 |
| 111 | 설정 반영 | ansible.builtin.meta | flush_handlers | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/monitoring/files/resource.sh](../files/resource.sh.md)
- [roles/monitoring/tasks/main.yml](main.yml.md)
- [roles/monitoring/templates/logrotate.j2](../templates/logrotate.j2.md)
- [roles/monitoring/templates/service.sh.j2](../templates/service.sh.j2.md)
- [roles/pkg/tasks/install.yml](../../pkg/tasks/install.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
