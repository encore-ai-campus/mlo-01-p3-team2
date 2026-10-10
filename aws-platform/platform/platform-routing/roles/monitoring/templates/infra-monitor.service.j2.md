# roles/monitoring/templates/infra-monitor.service.j2

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/monitoring/templates/infra-monitor.service.j2)

## 역할

전용 수집기 사용자로 collector.sh를 실행하고 항상 재시작하는 systemd unit이다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| monitor_collector_user |
| monitor_libexec_dir |

## systemd 선언

| 원본 행 | 설정 |
| --- | --- |
| 3 | Description=Infra monitor collector (SSH pull) |
| 4 | After=network-online.target |
| 5 | Wants=network-online.target |
| 8 | User={{ monitor_collector_user }} |
| 9 | Group={{ monitor_collector_user }} |
| 10 | ExecStart={{ monitor_libexec_dir }}/collector.sh |
| 11 | Restart=always |
| 12 | RestartSec=5 |
| 15 | WantedBy=multi-user.target |

## 함께 볼 파일

- [roles/monitoring/files/collector.sh](../files/collector.sh.md)
- [roles/monitoring/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
