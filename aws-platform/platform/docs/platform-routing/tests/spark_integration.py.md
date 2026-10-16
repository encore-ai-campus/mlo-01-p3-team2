# tests/spark_integration.py

[탐색 시작점](../../ROUTING-README.md) · [테스트 안내](README.md) · [원본 파일](../../../tests/spark_integration.py)

## 선언 구조

정규 파일 참조: `aws-platform/platform/tests/spark_integration.py`.

routing-doc-sync inventory의 parse_status는 ok다. 클래스·함수·메서드 선언은 0개이고 모듈 docstring도 없다. 이 파일은 최상위 코드로 실행되므로 존재하지 않는 main 함수나 API 시그니처를 기재하지 않는다. 대상 모듈을 import하거나 실행하지 않고 AST로만 조사했다.

## 실행 입력과 탐색 단서

Spark 노드에서 spark-submit으로 실행하는 연동 테스트다. 환경변수 키는 추가 정적 AST 조사로 확인했다.

| 환경변수 | 탐색 목적 |
| --- | --- |
| KAFKA_BOOTSTRAP | Kafka bootstrap 주소 |
| KAFKA_TOPIC | 읽을 토픽 |
| EXPECTED_COUNT | 기대 건수 |
| MYSQL_HOST | MySQL Router 주소. 로컬 배치는 127.0.0.1 |
| MYSQL_PORT | JDBC 포트. 기본 6446(Router RW), 직접 접속은 3306을 명시 |
| DEV_USER_PASSWORD_MYSQL | MySQL dev 비밀번호 |
| MONGO_HOSTS | MongoDB 멤버 주소 |
| DEV_USER_PASSWORD_MONGO | MongoDB dev 비밀번호 |

AST 호출 표기에는 Kafka 읽기, JDBC·MongoDB 쓰기와 재조회 count, Spark 종료가 있다. 문자열 상수에는 p8db, msgs, overwrite, INFRA_INTEGRATION_OK가 있다. MongoDB URI 상수는 replicaSet=infra를 포함한다. 이 상수와 호출은 탐색 단서이며 실제 연결 성공을 증명하지 않는다. overwrite 모드의 쓰기가 있으므로 실행 대상 DB·테이블·컬렉션을 먼저 확인한다.

## 정적 검사식

| AST에서 수집한 assert 조건 |
| --- |
| n == expected |
| spark.read.format('jdbc').options(**jdbc).load().count() == n |
| spark.read.format('mongodb').option('database', 'p8db').option('collection', 'msgs').load().count() == n |

import는 os, urllib.parse.quote, pyspark.sql.SparkSession이다. 함수 시그니처 검사 대상은 없고 파일 존재 검사만 적용된다. 역할 의미와 데이터 흐름의 전체 일치는 검증 불가이며 스킬의 role_status는 not_verified다.

## 함께 볼 파일

- [Spark 자체 검증](../roles/spark/tasks/verify.yml.md)
- [Spark 커넥터 JAR 목록](../roles/spark/defaults/main.yml.md)
- [검증 기록](../verification.md)

## InnoDB Cluster 연결 변경 — 2026-10-10

JDBC URL은 MYSQL_HOST와 MYSQL_PORT를 사용한다. 기본 포트는 6446이며 모든 JDBC 실행 노드에 로컬 Router가 있어야 127.0.0.1을 사용할 수 있다. routing-doc-sync로 현재 Python 선언을 다시 조사했으며 이 파일은 함수·클래스 없이 최상위 코드로 실행된다. 실제 Spark 연동은 이번 작업에서 실행하지 않았다.
