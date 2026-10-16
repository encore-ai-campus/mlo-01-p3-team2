# roles/mysql/tasks/verify.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/tasks/verify.yml)

## 역할

dev 접속·mysql 스키마 접근 거부, Cluster OK·모든 멤버 ONLINE·Primary 1대·Secondary 읽기 전용, Router 계정 출처를 검사한다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 2 | dev 계정으로 SELECT 1 | ansible.builtin.command | 상위 조건 확인 |
| 13 | dev 계정으로 mysql 스키마 조회 시도 | ansible.builtin.command | 상위 조건 확인 |
| 22 | InnoDB Cluster 상태 조회 | ansible.builtin.command | mysql_is_bootstrap |
| 36 | InnoDB Cluster 상태 검증 | ansible.builtin.assert | mysql_is_bootstrap |
| 52 | Router 계정 출처 확인 | ansible.builtin.command | 상위 조건 확인 |

## 동작과 제한

defaultReplicaSet은 InnoDB Cluster status 응답의 필드명이다. getReplicaSet을 호출한다는 뜻은 아니다. 정상 구축 검사는 모든 인벤토리 멤버의 ONLINE을 요구하며 장애 중 degraded 상태의 허용 검사가 아니다.

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
