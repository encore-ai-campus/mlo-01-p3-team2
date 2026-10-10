# roles/monitoring/vars/amazon.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/monitoring/vars/amazon.yml)

## 역할

Amazon Linux에서 사용할 SSH 수집·로그 회전·보관의 패키지·서비스·경로 등 역할 변수를 지정한다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 4 | monitor_units | 아래 목록/매핑/여러 줄 값 참조 |
| 12 | monitor_log_paths | 아래 목록/매핑/여러 줄 값 참조 |
| 20 | monitor_logrotate_paths | 아래 목록/매핑/여러 줄 값 참조 |
| 27 | monitor_group_candidates | [mysql, mongod] |
| 29 | monitor_mysql_socket | /var/lib/mysql/mysql.sock |
| 32 | monitor_group_readable_logs | [] |

## 함께 볼 파일

- [roles/monitoring/tasks/collector.yml](../tasks/collector.yml.md)
- [roles/monitoring/tasks/main.yml](../tasks/main.yml.md)
- [roles/monitoring/tasks/target.yml](../tasks/target.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
