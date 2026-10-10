# roles/monitoring/tasks/verify.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/monitoring/tasks/verify.yml)

## 역할

대상 로그 읽기와 수집 서버의 리소스·서비스·로그 수집을 확인하고 archive 서비스를 실행한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | monitor의 journalctl 읽기 | ansible.builtin.command | journalctl -n 1 -q --no-pager | 상위 block/play 조건도 확인 |
| 8 | monitor가 서비스 로그를 읽을 수 있는지 확인 (읽을 수 없는 파일이 없어야 한다) | ansible.builtin.shell | find {{ item }} -maxdepth 1 -type f ! -readable | 상위 block/play 조건도 확인 |
| 17 | 리소스 수집 확인 | ansible.builtin.shell | tail -n 1 {{ monitor_data_dir }}/metrics/{{ item }}/resource-$(date -u +%F).log | inventory_hostname in groups['monitoring'] |
| 27 | 서비스 상태 수집 확인 | ansible.builtin.shell | tail -n 1 {{ monitor_data_dir }}/metrics/{{ item }}/service-$(date -u +%F).log | inventory_hostname in groups['monitoring'] |
| 43 | 시스템 로그와 서비스 로그 수집 확인 | ansible.builtin.shell | 아래 작업·인자 참조 | inventory_hostname in groups['monitoring'] |
| 66 | 정리 스크립트 실행 | ansible.builtin.systemd | name=infra-monitor-archive.service; state=started | inventory_hostname in groups['monitoring'] |

## 함께 볼 파일

- [roles/monitoring/tasks/main.yml](main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
