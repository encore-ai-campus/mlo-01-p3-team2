# roles/monitoring/templates/monitor.conf.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/monitoring/templates/monitor.conf.j2)

## 역할

수집·보관 경로, 키, 목표 주기, 장애 임계치와 보관 기간의 셸 설정을 렌더링한다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| monitor_data_dir |
| monitor_archive_dir |
| monitor_config_dir |
| monitor_remote_dir |
| monitor_resource_interval |
| monitor_service_every |
| monitor_fail_limit |
| monitor_collect_keep_days |
| monitor_archive_keep_days |

## 함께 볼 파일

- [roles/monitoring/files/archive.sh](../files/archive.sh.md)
- [roles/monitoring/files/collector.sh](../files/collector.sh.md)
- [roles/monitoring/tasks/collector.yml](../tasks/collector.yml.md)
- [roles/monitoring/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
