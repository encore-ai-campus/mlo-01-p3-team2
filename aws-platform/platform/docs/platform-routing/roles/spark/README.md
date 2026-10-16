# spark: Spark Standalone Master·Worker

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

spark 그룹. 앞 spark_master_count대는 Master이고 전체가 Worker다. Java와 ZooKeeper 설정을 사용한다.

Master 선출·Worker 메모리·Python·커넥터 JAR·검증 제출 경로를 찾을 때 사용한다.

## 현재 작업 흐름

역할·메모리·IP 확인 → OS별 Python·sha512 배포 → sha256 JAR → 환경·unit → 시작 → Master·Worker·PySpark 검증

## 구현 조건

기본 Master 수는 2이며 그룹 대수 제한 assert는 없다. 시스템 Ansible Python과 PySpark Python은 별도로 관리한다. infra-check 검증과 외부 DB 연동 테스트는 서로 다른 파일이다.

## 프라이빗 서버의 통신 포트

| 용도 | 기본값 | 동작 |
| --- | --- | --- |
| Master RPC / Master UI | 7077 / 8080 | 데몬 포트 재시도 0으로 고정 |
| Worker RPC / Worker UI | 7100 / 8081 | 데몬 포트 재시도 0으로 고정 |
| Driver RPC | 7078–7094 | 시작 포트 7078부터 최대 16회 재시도 |
| Driver·Executor BlockManager | 7079–7095 | 시작 포트 7079부터 최대 16회 재시도 |

AWS traffic의 spark_driver_end·spark_block_end 및 spark_worker·spark_master_ui 연결과 맞춘다. 허용 대상은 Spark SG 사이의 연결이며 Worker UI 8081의 원격 공개 규칙은 추가하지 않는다. Master 상태 검증은 8080으로 조회하고, PySpark 작업은 Driver와 BlockManager 범위로 결과를 주고받는다. 같은 서버에서 여러 프로세스가 시작 포트를 점유하면 다음 포트를 시도하므로 한 포트만 허용해서는 안 된다. 동시 작업 수는 포트와 CPU·메모리 한도를 함께 고려해야 한다.

Master·Worker의 SPARK_DAEMON_JAVA_OPTS는 spark.port.maxRetries=0을 지정하고, 작업의 spark-defaults.conf는 spark.port.maxRetries=16을 지정한다. [Spark 설정 문서](https://spark.apache.org/docs/4.2.0/configuration.html#networking)와 [Standalone 설정](https://spark.apache.org/docs/4.2.0/spark-standalone.html)을 기준으로 구분했다. 포트를 바꾸면 defaults/main.yml과 선택한 AWS traffic 구성도 함께 변경한다.

## 경로별 문서

인프라 쪽 선언은 [traffic 설정](../../../../../../aws-infra/docs/infra-routing/config/README.md#traffic), 범위 전달·규칙 속성의 모의 검사는 [Spark 포트 범위 테스트](../../../../../../aws-infra/docs/infra-routing/tests/README.md#spark-포트-범위)로 연결된다. SG 검사와 원격 서비스 검사는 별개다. service unit을 만드는 위치는 [설치 작업](tasks/main.yml.md)이며 ZooKeeper 역할만 실행해도 spark-worker.service가 생성되는 구조는 아니다.

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/spark/defaults/main.yml | [main.yml](defaults/main.yml.md) | Spark Standalone Master·Worker의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/spark/meta/main.yml | [main.yml](meta/main.yml.md) | Ansible 역할 의존성으로 Java 역할을 선언한다. |
| roles/spark/tasks/main.yml | [main.yml](tasks/main.yml.md) | Master·Worker 배치, 가용 메모리·IP 확인, Python·Spark·JAR 설치와 환경·unit 배포를 연결한다. |
| roles/spark/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | 서비스 active/enabled, ALIVE Master 하나·STANDBY·Worker 수를 확인하고 infra-check PySpark 작업을 제출한다. |
| roles/spark/templates/infra-check.py.j2 | [infra-check.py.j2](templates/infra-check.py.j2.md) | PySpark 자체 검증; 보조 AST 조사 기준 |
| roles/spark/templates/spark-defaults.conf.j2 | [spark-defaults.conf.j2](templates/spark-defaults.conf.j2.md) | 복수 Master 주소와 Driver·BlockManager의 시작 포트·재시도 범위를 지정한다. |
| roles/spark/templates/spark-env.sh.j2 | [spark-env.sh.j2](templates/spark-env.sh.j2.md) | Java, 로컬 IP, Worker CPU·메모리, ZooKeeper recovery와 PySpark Python 환경을 지정한다. |
| roles/spark/templates/spark-master.service.j2 | [spark-master.service.j2](templates/spark-master.service.j2.md) | 사설 IP와 Master RPC·UI 포트로 Spark Master를 실행하고 master.log에 기록한다. |
| roles/spark/templates/spark-worker.service.j2 | [spark-worker.service.j2](templates/spark-worker.service.j2.md) | 복수 Master 주소와 명시한 RPC 포트로 Worker를 실행하고 worker.log에 기록한다. |
| roles/spark/vars/amazon.yml | [amazon.yml](vars/amazon.yml.md) | Amazon Linux에서 사용할 Spark Standalone Master·Worker의 패키지·서비스·경로 등 역할 변수를 지정한다. |
| roles/spark/vars/ubuntu.yml | [ubuntu.yml](vars/ubuntu.yml.md) | Ubuntu에서 사용할 Spark Standalone Master·Worker의 패키지·서비스·경로 등 역할 변수를 지정한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
