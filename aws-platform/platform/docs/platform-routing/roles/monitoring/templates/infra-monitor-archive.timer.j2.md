# roles/monitoring/templates/infra-monitor-archive.timer.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/monitoring/templates/infra-monitor-archive.timer.j2)

## 역할

매일 UTC 03:30(한국 시간 12:30)에 archive 서비스를 실행한다. Persistent=true다.

## systemd 선언

| 원본 행 | 설정 |
| --- | --- |
| 3 | Description=Daily infra monitor archive and cleanup |
| 6 | OnCalendar=*-*-* 03:30:00 UTC |
| 7 | Persistent=true |
| 10 | WantedBy=timers.target |

## 함께 볼 파일

- [roles/monitoring/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
