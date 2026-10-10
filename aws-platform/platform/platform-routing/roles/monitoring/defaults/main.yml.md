# roles/monitoring/defaults/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/monitoring/defaults/main.yml)

## 역할

SSH 수집·로그 회전·보관의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 3 | monitor_user | monitor |
| 4 | monitor_remote_dir | /usr/local/libexec/infra-monitor   # 대상 서버의 원격 수집 스크립트 |
| 7 | monitor_journal_max_use | 200M |
| 12 | monitor_logrotate_days | 3 |
| 15 | monitor_collector_user | infra-monitor |
| 16 | monitor_config_dir | /etc/infra-monitor |
| 17 | monitor_data_dir | /var/lib/infra-monitor     # metrics/, logs/, state/ |
| 18 | monitor_archive_dir | /var/archive/infra |
| 19 | monitor_libexec_dir | /usr/local/libexec/infra-monitor |
| 21 | monitor_resource_interval | 10      # 초: 리소스와 로그 수집 주기 |
| 22 | monitor_service_every | 3           # 서비스 상태는 리소스 주기의 몇 배마다 (3 × 10초 = 30초) |
| 23 | monitor_fail_limit | 3              # 연속 실패가 이만큼이면 down |
| 24 | monitor_collect_keep_days | 4       # 수집 폴더 보관 (서버 3일 < 수집 폴더 4일 < 보관 폴더 14일) |
| 25 | monitor_archive_keep_days | 14 |
| 28 | monitor_no_log | true |

## 함께 볼 파일

- [roles/monitoring/tasks/collector.yml](../tasks/collector.yml.md)
- [roles/monitoring/tasks/main.yml](../tasks/main.yml.md)
- [roles/monitoring/tasks/target.yml](../tasks/target.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
