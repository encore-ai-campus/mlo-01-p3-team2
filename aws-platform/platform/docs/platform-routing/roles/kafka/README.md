# kafka: Kafka KRaft combined 클러스터

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

kafka 그룹. Java 역할에 의존한다.

KRaft voter·리스너·복제 수는 server.properties.j2, 버전·해시는 defaults/main.yml에서 찾는다.

## 현재 작업 흐름

내부 값·사용자 → sha512 배포 → 설정 → 기존 cluster.id 재사용 또는 UUID → 미포맷 노드 포맷 → 시작·검증

## 구현 조건

기본 복제 수와 검증 토픽 replication-factor는 3이다. Kafka는 ZooKeeper에 의존하지 않는다. meta.properties가 있는 노드는 다시 포맷하지 않는다. 현재 템플릿의 리스너는 PLAINTEXT다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/kafka/defaults/main.yml | [main.yml](defaults/main.yml.md) | Kafka KRaft combined 클러스터의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/kafka/meta/main.yml | [main.yml](meta/main.yml.md) | Ansible 역할 의존성으로 Java 역할을 선언한다. |
| roles/kafka/tasks/main.yml | [main.yml](tasks/main.yml.md) | RAM 기반 heap·노드 ID, 미러 다운로드, 설정·cluster.id·조건부 포맷·서비스 시작을 연결한다. |
| roles/kafka/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | 서비스 enabled/active, controller quorum, 복제 수 3 임시 토픽의 ISR·produce·consume을 확인하고 토픽을 삭제한다. |
| roles/kafka/templates/kafka.service.j2 | [kafka.service.j2](templates/kafka.service.j2.md) | Java·heap·로그 환경으로 kafka-server-start.sh를 실행하며 실패 시 재시작한다. |
| roles/kafka/templates/log4j2.yaml.j2 | [log4j2.yaml.j2](templates/log4j2.yaml.j2.md) | Kafka INFO 로그를 server.log 하나에 기록한다. 회전 작업은 monitoring의 logrotate에 있다. |
| roles/kafka/templates/server.properties.j2 | [server.properties.j2](templates/server.properties.j2.md) | KRaft broker+controller, 정적 voters, 사설 IP PLAINTEXT 리스너와 복제 수·ISR·토픽 자동 생성 정책을 지정한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
