# 검증 코드 지도

[탐색 시작점](../../ROUTING-README.md)

| 검증 목적 | 먼저 볼 문서 | 실행 경계 |
| --- | --- | --- |
| Spark 자체 계산·Python·클래스 로딩 | [Spark verify](../roles/spark/tasks/verify.yml.md) | Ansible verify 작업에서 infra-check 템플릿 배포·제출 |
| Kafka → MySQL·MongoDB 연동 | [spark_integration.py](spark_integration.py.md) | Spark 노드에서 환경변수를 설정하고 별도로 spark-submit |
| Cluster·Router 로컬 검증 | [validate_mysql_cluster.py](validate_mysql_cluster.py.md) · [AdminAPI 시나리오](mysql_cluster.test.cjs.md) | 컨트롤 노드에서 렌더링·모의 검사·로컬 Ansible assert·문법 검사, 원격 접속 없음 |
| 역할별 서비스·계정·포트 상태 | [역할별 verify](../roles/README.md) | 각 역할의 tasks/verify.yml |

MySQL Cluster 전환은 로컬 렌더링·모의 검사·Ansible 문법 검사까지 수행했다. README의 과거 서버 검증 기록은 재실행하거나 갱신하지 않았다.

Spark 포트 범위의 Terraform 전달·SG 속성은 [인프라 포트 범위 테스트](../../../../../aws-infra/docs/infra-routing/tests/README.md#spark-포트-범위)에서 확인한다. model·security-rules·workload의 정적/모의 검사이며 원격 서비스는 실행하지 않는다.

Spark 통신 변경은 [기본 변수](../roles/spark/defaults/main.yml.md), [Worker unit](../roles/spark/templates/spark-worker.service.j2.md), [데몬 환경](../roles/spark/templates/spark-env.sh.j2.md), [작업 포트](../roles/spark/templates/spark-defaults.conf.j2.md)와 [Master 조회·PySpark 검증](../roles/spark/tasks/verify.yml.md)으로 이어진다. ZooKeeper 검증 성공은 Spark 설치·Worker 등록·계산 작업 검증 성공과 구분한다.
