# roles/monitoring/files/collector.sh

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/monitoring/files/collector.sh)

## 역할

모든 대상에서 SSH로 리소스·journal·서비스 상태를 가져오고 rsync로 로그를 수집하는 계속 실행되는 루프다.

## 셸 함수 탐색

| 원본 행 | 함수 |
| --- | --- |
| 17 | now() |
| 18 | today() |
| 21 | one_resource() |
| 38 | one_journal() |
| 62 | one_logs() |
| 77 | one_service() |

## 함께 볼 파일

- [roles/monitoring/files/resource.sh](resource.sh.md)
- [roles/monitoring/tasks/collector.yml](../tasks/collector.yml.md)
- [roles/monitoring/tasks/main.yml](../tasks/main.yml.md)
- [roles/monitoring/templates/infra-monitor.service.j2](../templates/infra-monitor.service.j2.md)
- [roles/monitoring/templates/monitor.conf.j2](../templates/monitor.conf.j2.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
