# roles/spark/templates/infra-check.py.j2

[탐색 시작점](../../../ROUTING-README.md) · [Spark 안내](../README.md) · [원본 파일](../../../../../roles/spark/templates/infra-check.py.j2)

## 역할과 배포

roles/spark/tasks/verify.yml이 spark_data_dir/infra-check.py로 배포하고 첫 Spark 노드에서 spark-submit --deploy-mode client로 제출하는 자체 검증 작업이다. 외부 Kafka·MySQL·MongoDB 연동 테스트와 구분한다.

## AST 보조 조사

기본 스킬은 .py 파일만 분석하므로 이 .py.j2 파일은 기본 inventory 대상에서 제외된다. 스킬의 decode_python·SymbolCollector·scope_facts를 재사용한 보조 AST 조사에서는 템플릿 원문을 렌더링하지 않고 파싱할 수 있었고 선언된 클래스·함수는 0개였다. 이 결과는 Jinja 렌더링 성공이나 실제 Spark 실행 성공을 증명하지 않는다.

import는 sys와 pyspark.sql.SparkSession이다. 호출 표기에는 parallelize, map, sum, executor 버전 collect, context class loader의 loadClass와 spark.stop이 있다. 성공 문자열은 INFRA_SPARK_OK다.

| AST에서 수집한 assert 조건 |
| --- |
| sys.version_info[:2] == (3, 12) |
| executor_versions == {(3, 12)} |
| total == 999000 |

첫 Spark 노드의 verify 작업은 stdout에 INFRA_SPARK_OK가 있는지 검사한다. 커넥터 클래스 목록의 선언 위치는 Spark defaults/main.yml이다. 기본 스킬의 documents.checks가 이 파일의 심볼·시그니처를 검증했다고 해석하면 안 된다.

## 함께 볼 파일

- [배포·제출 작업](../tasks/verify.yml.md)
- [검증할 클래스·JAR 기본값](../defaults/main.yml.md)
- [외부 서비스 연동 테스트](../../../tests/spark_integration.py.md)
