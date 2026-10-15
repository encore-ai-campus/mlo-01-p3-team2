# Ansible 역할 지도

[탐색 시작점](../../ROUTING-README.md)

| 역할 | 문서 | 대상·호출 |
| --- | --- | --- |
| edge | [Nginx·공인 IP HTTPS](edge/README.md) | game_frontend·ad_frontend 및 이전 edge 그룹. edge.yml 또는 site.yml --tags edge. |
| common | [공통 보안과 시간 동기화](common/README.md) | 모든 서버. Bastion을 먼저 구성한다. |
| firewall | [nftables 방화벽](firewall/README.md) | 모든 서버. Bastion에 먼저 적용한다. |
| pkg | [공용 패키지 설치와 APT 저장소](pkg/README.md) | 다른 역할이 include_role의 tasks_from으로 호출하는 보조 역할. |
| java | [Java 17 설치](java/README.md) | Kafka·ZooKeeper·Spark의 meta/main.yml이 의존한다. |
| mysql | [MySQL InnoDB Cluster 설치·계정·검증](mysql/README.md) | mysql 그룹 전체 3~9대. 첫 노드는 구축 담당이며 운영 Primary는 자동 선출된다. |
| mongodb | [MongoDB 설치·인증·Replica Set](mongodb/README.md) | mongodb 그룹. 첫 번째 노드에서 초기화와 계정 작업을 한다. |
| kafka | [Kafka KRaft combined 클러스터](kafka/README.md) | kafka 그룹. Java 역할에 의존한다. |
| zookeeper | [Spark 복구용 ZooKeeper ensemble](zookeeper/README.md) | 기본 zookeeper_group=spark. site.yml이 Spark 역할보다 먼저 실행한다. |
| spark | [Spark Standalone Master·Worker](spark/README.md) | spark 그룹. 앞 spark_master_count대는 Master이고 전체가 Worker다. Java와 ZooKeeper 설정을 사용한다. |
| backend | [앱 서버의 로컬 MySQL Router](backend/README.md) | game:spark:backend 그룹. |
| monitoring | [SSH 수집·로그 회전·보관](monitoring/README.md) | monitoring 그룹이 있을 때 site.yml이 모든 서버에 실행한다. collector는 monitoring 노드에만 배포한다. |

roles/pkg는 tasks/main.yml이 없는 보조 역할이며, java는 Kafka·ZooKeeper·Spark의 meta 의존성으로 연결된다. 다른 역할의 기본 진입점은 tasks/main.yml이다.
