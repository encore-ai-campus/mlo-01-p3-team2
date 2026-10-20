# site.yml

2026-10-18 HTTPS play의 대상은 edge:game_frontend:ad_frontend다. 게임은 도메인·IP 이동용 인증서와 로컬 앱/WebSocket 전달 경로를, 광고는 기존 IP 모드를 사용한다. Django나 광고 앱 자체를 배포하지 않는다. 도메인은 edge_domain으로 선택하며 [현재 운영 구성](../../../../aws-infra/docs/operations/current-state.md)과 원격 재배포 전 상태를 구분한다.

[탐색 시작점](../ROUTING-README.md) · [역할 지도](roles/README.md) · [원본 파일](../../site.yml)

## 역할

프록시·공통 보안·방화벽 → MySQL Cluster → 다른 서비스 → game:ad:spark:mysql:backend 로컬 Router → 모니터링 순서다. MySQL과 Router play는 any_errors_fatal=true다. MySQL은 strategy=linear로 모든 노드의 준비가 끝난 뒤 구축 담당이 Cluster를 생성한다.

## Router 단독 실행

`--tags mysql_router`는 [계정 준비](roles/mysql/tasks/router-access.yml.md) play와 game:ad:spark:mysql:backend Router play를 함께 선택한다. 기존 backend 태그도 같은 준비 경로를 사용한다. MySQL 패키지·설정·Cluster 구성 play는 mysql 태그이므로 단독 Router 실행에 포함되지 않는다.

계정 준비가 MySQL 전체에서 성공한 뒤에만 Router 설치로 진행한다. `--limit ad`는 준비 누락 검사에서 중단된다. 일부 대상만 선택할 때도 `--limit 'mysql:ad'`처럼 mysql 그룹을 포함한다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 3 | 프록시 준비 import | ansible.builtin.import_playbook | proxy 태그·내부 조건 |
| 6 | 공통 보안 (Bastion) | play | 해당 태그·host 조건 |
| 14 | 공통 보안 (나머지 서버) | play | 해당 태그·host 조건 |
| 22 | 방화벽 (Bastion) | play | 해당 태그·host 조건 |
| 30 | 방화벽 (나머지 서버) | play | 해당 태그·host 조건 |
| 37 | MySQL | play | 해당 태그·host 조건 |
| 46 | MongoDB | play | 해당 태그·host 조건 |
| 53 | Kafka | play | 해당 태그·host 조건 |
| 61 | ZooKeeper와 Spark | play | 해당 태그·host 조건 |
| 70 | MySQL Router 접속 계정 준비 | play | 해당 태그·host 조건 |
| 83 | MySQL Router | play | 해당 태그·host 조건 |
| 100 | 진입 서버 HTTPS | play | 해당 태그·host 조건 |
| 108 | Monitoring | play | 해당 태그·host 조건 |

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](verification.md)에서 범위를 확인한다.

## Edge HTTPS

Monitoring 직전에 hosts: edge:game_frontend:ad_frontend, role: edge, tags: [edge] play가 실행된다. 실제 EIP·허용 사용자 CIDR이 필수다. Front HTTPS만 별도로 준비하려면 [edge.yml](edge.yml.md)을 사용한다. [edge 역할](roles/edge/README.md)은 Front 앱 설치를 포함하지 않는다.
