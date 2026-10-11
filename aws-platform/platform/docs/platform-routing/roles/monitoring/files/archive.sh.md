# roles/monitoring/files/archive.sh

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/monitoring/files/archive.sh)

## 역할

하루 지난 수집 파일을 gzip 복사하고 수집·보관 기한을 넘은 파일을 정리한다. 원본을 보관 폴더로 이동하는 방식은 아니다.

## 함께 볼 파일

- [roles/monitoring/tasks/collector.yml](../tasks/collector.yml.md)
- [roles/monitoring/tasks/main.yml](../tasks/main.yml.md)
- [roles/monitoring/templates/infra-monitor-archive.service.j2](../templates/infra-monitor-archive.service.j2.md)
- [roles/monitoring/templates/monitor.conf.j2](../templates/monitor.conf.j2.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
