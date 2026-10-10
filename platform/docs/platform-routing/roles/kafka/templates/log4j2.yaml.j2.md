# roles/kafka/templates/log4j2.yaml.j2

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/kafka/templates/log4j2.yaml.j2)

## 역할

Kafka INFO 로그를 server.log 하나에 기록한다. 회전 작업은 monitoring의 logrotate에 있다.

## 함께 볼 파일

- [roles/kafka/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
