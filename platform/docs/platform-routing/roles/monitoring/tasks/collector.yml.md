# roles/monitoring/tasks/collector.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/monitoring/tasks/collector.yml)

## 역할

수집기 사용자·디렉터리·스크립트·SSH 개인키·DB Secret과 수집 서비스·정리 타이머를 구성한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | Secret 확인 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 12 | 수집 사용자 | ansible.builtin.user | name={{ monitor_collector_user }} | 상위 block/play 조건도 확인 |
| 20 | 디렉터리 | ansible.builtin.file | path={{ item.path }}; state=directory | 상위 block/play 조건도 확인 |
| 38 | 수집 스크립트 디렉터리 | ansible.builtin.file | path={{ monitor_libexec_dir }}; state=directory | 상위 block/play 조건도 확인 |
| 46 | 수집 스크립트 | ansible.builtin.copy | src={{ item }}; dest={{ monitor_libexec_dir }}/{{ item }} | 상위 block/play 조건도 확인 |
| 56 | 설정 파일 | ansible.builtin.template | src={{ item.src }}; dest={{ monitor_config_dir }}/{{ item.dest }} | 상위 block/play 조건도 확인 |
| 68 | SSH 개인키 | ansible.builtin.copy | dest={{ monitor_config_dir }}/id_ed25519 | 상위 block/play 조건도 확인 |
| 78 | DB 비밀번호 파일 | ansible.builtin.copy | dest={{ monitor_config_dir }}/secrets | 상위 block/play 조건도 확인 |
| 89 | 수집 루프 현재 상태 | ansible.builtin.systemd | name=infra-monitor.service | 상위 block/play 조건도 확인 |
| 94 | systemd unit | ansible.builtin.template | src={{ item }}.j2; dest=/etc/systemd/system/{{ item }} | 상위 block/play 조건도 확인 |
| 104 | 수집 루프와 정리 타이머 시작 | ansible.builtin.systemd | name={{ item }}; state=started | 상위 block/play 조건도 확인 |
| 113 | 바뀌었으면 수집 루프 다시 시작 | ansible.builtin.systemd | name=infra-monitor.service; state=restarted | 원본의 목록 또는 여러 줄 조건 확인 |

## 함께 볼 파일

- [roles/monitoring/files/archive.sh](../files/archive.sh.md)
- [roles/monitoring/files/collector.sh](../files/collector.sh.md)
- [roles/monitoring/tasks/main.yml](main.yml.md)
- [roles/monitoring/templates/hosts.conf.j2](../templates/hosts.conf.j2.md)
- [roles/monitoring/templates/monitor.conf.j2](../templates/monitor.conf.j2.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
