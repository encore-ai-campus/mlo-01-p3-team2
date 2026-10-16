# Spark 정규화·분석 MySQL 적재

Spark `4.2.0`이 성공 Std Kafka를 여러 토픽에서 읽고, header·본문·타입·지문을 검증한 뒤 9개 사실 테이블에 적재한다. 스트리밍 집계·조인·`dropDuplicates`를 사용하지 않는다. 중복은 MySQL의 `event_uuid` PK와 버전 조건을 확인한 멱등 쓰기로 처리한다.

## 구성

| 경로 | 역할 |
|---|---|
| `stream.py` | `.env` 로딩, 선택적 migration, Structured Streaming 실행 |
| `spark_pipeline/config.py` | Kafka·MySQL·Driver·checkpoint 설정 |
| `spark_pipeline/contracts.py` | Std 계약 로딩, 이벤트·버전별 `StructType`, 사실 테이블 연결 |
| `spark_pipeline/validation.py` | 원본 Std JSON의 엄격한 검증·canonical 지문 대조 |
| `spark_pipeline/streaming.py` | `foreachBatch`, `from_json`, UUID·UTC 변환, 분산 쓰기 |
| `spark_pipeline/package.py` | Driver의 Python 모듈을 ZIP으로 묶어 `addPyFile`로 Executor에 전달 |
| `spark_pipeline/mysql_sink.py` | 파티션별 연결, 트랜잭션, 버전·지문 검사, 오류 격리 |
| `contracts/registry.json` | Driver가 읽는 독립 Std 계약 산출물 |
| `build_contracts.py` | Std and Sinker JSON에서 Spark 계약을 빌드 |
| `migrations/001_facts.sql`, `migrations/002_quiz_question_type.sql`, `migrate.py` | 초기 생성·기존 퀴즈 테이블의 명시적 스키마 확장 |
| `runtime_lock.json`, `prepare_jars.py` | 지정 버전·JAR SHA-256 고정 및 확인 |
| `kafka/node.properties` | Docker 통합 테스트에서 실제 사용하는 Kafka 설정 |
| `docker-compose.test.yml`, `Dockerfile` | Kafka·MongoDB·MySQL·Spark Driver/Worker 3개 로컬 구성 |
| `test_pipeline.py` | 실제 전체 흐름·오류·버전·재시작·부분 실패·offset 만료 검증 |
| `runtime_probe.py` | JVM 버전, MySQL JDBC 실연결, Mongo Spark 커넥터 읽기 확인 |
| `run_native_tests.py` | Docker가 불가한 macOS 환경의 격리된 직접 실행 테스트 |

Spark 실행기는 Std and Sinker Python 모듈을 import하지 않는다. 계약 빌드 단계만 `../std_and_sinker/contracts`를 읽고 결과를 이 디렉터리에 저장한다. JSON을 바꾸면 계약을 다시 빌드하고 양쪽 프로세스를 재시작한다. Driver가 Python 애플리케이션 모듈을 ZIP으로 묶어 `SparkContext.addPyFile()`로 분배하므로 Executor가 Driver의 소스 경로를 직접 읽을 필요가 없다. 바이너리 라이브러리·Python 의존성·JAR은 각 Executor 환경에 배포한다. 공통 배포 파서 버전은 `1.1.0`이며 기존 `1.0.0` 입력도 지원한다. 통합 테스트의 `1.2.0`은 테스트 레지스트리에만 추가한다.

## 설치와 단위 테스트

저장소 루트에서 실행한다. 고정 Spark 배포 환경은 Java 21·Spark/Scala 4.2.0/2.13이다. Spark Docker 이미지에는 Python 3.10이 있으며 Python DB·검증 의존성은 `requirements.txt`에 고정한다.

```bash
uv venv pipeline/std_and_sinker/.venv
uv pip install --python pipeline/std_and_sinker/.venv/bin/python -r pipeline/std_and_sinker/requirements.txt -r pipeline/spark/requirements.txt
PYTHONPATH=pipeline/std_and_sinker pipeline/std_and_sinker/.venv/bin/python -m unittest discover -s pipeline/std_and_sinker/tests -v
PYTHONPATH=pipeline/spark pipeline/std_and_sinker/.venv/bin/python -m unittest discover -s pipeline/spark/tests -v
python3 pipeline/spark/build_contracts.py
python3 pipeline/spark/prepare_jars.py
```

JAR 10개의 경로·SHA-256은 [runtime_lock.json](runtime_lock.json)에 사용자가 지정한 값으로 등록되어 있다. 다른 버전을 자동으로 대체하지 않는다. 지문은 Std and Sinker와 같은 벡터로 대조하고, MySQL UUID는 `CHAR(32)`, 시각은 UTC `DATETIME(6)`로 저장한다. Spark timestamp가 Python의 로컬 시간대로 변환되지 않도록 적재 전에 UTC 문자열로 표현한다.

## 퀴즈 1.0·1.1과 기존 MySQL 테이블

`QUIZ_ANSWERED` Std `1.0`은 기존 형식 그대로 검증하며, 새로 적재하는 사실 행의 `question_type`만 `MULTIPLE_CHOICE`로 매핑한다. Std `1.1`은 `question_type`이 필수이며 값은 `MULTIPLE_CHOICE` 또는 `FILL_BLANK`다. 객관식의 `choice_uuid`는 필수 UUID이고 빈칸형은 명시적 `null`이어야 한다. 계약의 `conditional_rules`를 원본 JSON 검증에 적용한 뒤 버전별 스키마로 파싱하므로 두 버전이 같은 배치에 들어와도 각 버전의 행만 해당 스키마로 처리한다.

새 DB의 [001_facts.sql](migrations/001_facts.sql)은 nullable `question_type`·`choice_uuid`를 포함한다. 기존 DB는 새 Writer 배포 전에 [002_quiz_question_type.sql](migrations/002_quiz_question_type.sql)을 한 번 적용한다. 이 ALTER는 기존 행의 값·파서 순서·지문을 수정하지 않고 새 `question_type`을 `NULL`로 둔다. `migrate.py --migration <SQL 경로>`로 명시적으로 실행할 수 있다. 기본 `migrate.py`와 `stream.py --migrate`는 초기 `CREATE TABLE IF NOT EXISTS`만 실행하므로 기존 테이블에 이 ALTER를 적용하지 않는다.

## Docker 전체 통합 테스트

```bash
docker compose -f pipeline/spark/docker-compose.test.yml build spark-driver
docker compose -f pipeline/spark/docker-compose.test.yml up -d --no-build --wait
pipeline/std_and_sinker/.venv/bin/python pipeline/spark/test_pipeline.py
docker compose -f pipeline/spark/docker-compose.test.yml stop
```

하나의 공통 이미지로 Master·Worker 3개·Driver를 실행한다. `spark-driver`만 `artifacts`를 쓰기 가능하게 연결하며 Worker에는 checkpoint 디렉터리를 연결하지 않는다. 코드 디렉터리는 로컬 테스트에서 읽기 전용으로 연결한다. EC2에서는 같은 배포 패키지·이미지와 필요한 Python 모듈을 각 실행기에 제공한다.

테스트는 매번 별도 토픽·Consumer group·MongoDB/MySQL DB와 checkpoint를 만든다. 실제 15개 사건을 처리한 Std and Sinker의 출력을 Spark가 읽고, 모든 필드와 중복 제거된 행 수를 비교한다. 성공 후 자신의 테스트 토픽·DB만 삭제한다. 실패한 자원은 진단을 위해 남기며 `--keep-data`로 성공 자원도 유지할 수 있다. offset 만료 시험은 자신의 테스트 토픽에서 미처리 레코드를 제거하여 쿼리 중단과 checkpoint 미완료를 확인한다.

결과는 `artifacts/<run-id>/integration_report.json`, 최신 결과 위치는 `artifacts/latest.json`에 기록한다. 최상위 [result.md](../../result.md)에 실제 실행 환경과 제한을 정리한다.

## Docker 장애 시 직접 실행 테스트

현재 macOS 대체 실행기는 Homebrew Java 21·`mongod`·`mysqld`와 Python 3.14를 사용한다. 기존 서비스 데이터 디렉터리를 사용하지 않으며 자기 테스트 프로세스만 시작·종료한다. 지정 포트가 이미 사용 중이면 기존 서비스를 중단하지 않고 테스트를 멈춘다.

```bash
uv venv pipeline/spark/.venv --python 3.14
uv pip install --python pipeline/spark/.venv/bin/python pyspark==4.2.0 -r pipeline/spark/requirements.txt -r pipeline/std_and_sinker/requirements.txt
python3 pipeline/spark/prepare_jars.py
python3 pipeline/spark/prepare_native_runtime.py
pipeline/spark/.venv/bin/python pipeline/spark/run_native_tests.py
```

현재 `pipeline/spark` 디렉터리에서 성공한 테스트 데이터와 MySQL 서버를 유지하려면 다음을 실행한다.

```bash
.venv/bin/python run_native_tests.py --keep-mysql-running
```

이 옵션은 `--keep-data`도 적용한다. 전체 테스트가 통과하면 MySQL만 `127.0.0.1:33306`에서 계속 실행하고 Kafka·MongoDB·Spark는 종료한다. 출력에 MySQL PID와 데이터 디렉터리가 표시되며, 테스트 DB 이름과 테이블별 행 수는 `artifacts/latest.json`이 가리키는 보고서에서 확인한다. 테스트가 실패하면 모든 테스트 서버를 종료한다. 다음 테스트 전에는 출력된 MySQL PID를 `kill <PID>`로 종료해야 한다. `--keep-data`만 사용하면 성공 데이터는 디스크에 남기고 모든 서버를 종료한다. 옵션을 생략하면 기존처럼 성공한 테스트 자원과 서버를 정리한다.

직접 실행은 한 컴퓨터의 Master·Worker 3개·Driver 프로세스다. 3대 EC2의 네트워크·파일시스템 격리나 장애 내성 검증을 대신하지 않는다. Kafka는 4.3.1/Scala 2.13, Spark는 4.2.0을 사용하며 MongoDB·MySQL 서버 버전은 설치된 바이너리의 실제 값을 결과에 기록한다. 테스트 데이터와 로그는 무시된 `artifacts/native-runtime`에 남는다.

## `.env`와 직접 작업 실행

[.env.example](.env.example)은 Docker 내부 주소를 사용한다. EC2에서는 Kafka·MySQL·Master의 실제 내부 주소와 계정, Driver의 영구 checkpoint 경로로 바꾼다.

| 설정 | 의미 |
|---|---|
| `KAFKA_BOOTSTRAP_SERVERS`, `SPARK_INPUT_TOPICS` | Kafka 브로커·Std 구독 목록 |
| `SPARK_MASTER`, `SPARK_REGISTRY_FILE` | Spark Master 주소·Driver의 계약 파일 |
| `SPARK_CHECKPOINT_LOCATION` | Driver 영구 디스크의 쿼리 전용 경로 |
| `SPARK_STARTING_OFFSETS` | 새 checkpoint의 최초 위치. 재시작 위치를 덮어쓰지 않음 |
| `SPARK_WRITE_PARTITIONS`, `MYSQL_WRITE_BATCH_SIZE` | 동시 SQL 쓰기 파티션 수·트랜잭션당 행 수 |
| `SPARK_MAX_OFFSETS_PER_TRIGGER`, `SPARK_TRIGGER_SECONDS` | 배치 입력 제한·실행 간격 |
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` | 분석 DB 접속 정보 |
| `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SASL_MECHANISM`, `KAFKA_SASL_JAAS_CONFIG` | Kafka Java 클라이언트 인증 |
| `KAFKA_SSL_TRUSTSTORE_LOCATION`, `KAFKA_SSL_TRUSTSTORE_PASSWORD`, `MYSQL_SSL_CA` | Kafka truststore·MySQL TLS 설정 |

환경변수가 `.env`보다 우선한다. 파일·checkpoint 상대 경로는 `.env` 위치 기준이다. Kafka SASL/SSL 설정은 Executor에서도 유효해야 한다. 기본 구독은 `standardized.points`를 포함한 7개 Std 토픽이며, `POINT_GRANTED` 이벤트는 `point_grant_fact`에 적재한다. 기존 설정을 사용하는 경우 `SPARK_INPUT_TOPICS`에 `standardized.points`를 추가하고 작업을 재시작한다.

```bash
cp pipeline/spark/.env.example pipeline/spark/.env
```

배포한 Spark 4.2.0 환경의 `spark-submit --master spark://<master>:7077 --deploy-mode client ... pipeline/spark/stream.py --env-file <설정경로> --migrate`로 시작한다. `--available-now`는 현재 데이터 처리 후 종료하는 테스트·배치 실행 옵션이다. 지속 실행에는 해당 옵션을 생략한다. Driver가 작업을 조정하고 Executor가 검증·변환·MySQL 쓰기를 수행한다.

### EC2 상시 서비스

실제 EC2 배포는 `spark-1/2` Master와 `spark-1/2/3` Worker, `spark-1` Driver로 구성한다. 기존 Corretto Java 17과 Python 3.12 환경을 사용한다. Java 17은 [Spark 4.2.0 공식 지원 런타임](https://spark.apache.org/docs/4.2.0/)이며, 위 Java 21은 로컬 검증 기준이다. Executor는 각 1 core·2 GiB, Driver는 1 GiB로 실행한다.

`spark-1`의 `spark-pipeline.service`가 `client` 모드 작업을 제출하고 자동 재시작한다. 각 Executor는 로컬 MySQL Router의 쓰기 포트 `127.0.0.1:6446`으로 `analysis_user`에 적재한다. 비밀번호는 systemd 암호화 자격 증명으로 보관하며 일반 설정 파일에 넣지 않는다. 구체적인 제출 명령·서비스 관리·격리 검증 절차는 [EC2 배포 안내](deploy/README.md)를 참고한다.

## 복구 경계

- 데이터 오류는 `stream_processing_error`에 Kafka 위치·오류 코드·가능한 UUID·원본 참조를 저장한다. 원문을 일반 오류 로그에 복사하지 않는다.
- SQL 저장·오류 격리가 실패하면 배치를 실패시킨다. 작업을 같은 checkpoint에서 재시작하여 미완료 배치를 다시 읽는다.
- MySQL 쓰기는 파티션별 연결 하나를 재사용한다. 행 잠금과 파서 순서·지문을 확인하고 제한된 크기로 커밋한다. 같은 버전의 다른 지문은 격리하고, 높은 버전은 갱신하며 낮은 버전은 무시한다. 삽입 경쟁·데드락은 제한적으로 재시도한다.
- checkpoint는 한 쿼리의 진행 기록이며 Worker별로 나누지 않는다. 현재는 배치 간 상태 연산이 없으므로 Driver의 영구 디스크를 사용한다. 같은 경로를 작업 두 개가 동시에 사용하지 않는다.
- Driver 자동 전환·실제 3노드 장애 내성·운영 지표·삭제 전파·Mongo 원본 재발행 도구는 별도 운영 작업이다.

기준: [Spark DRD](../../pipeline/DRD/spark_drd.md), [Spark 구현 방안](../../pipeline/Implementation/spark_implementation.md).
