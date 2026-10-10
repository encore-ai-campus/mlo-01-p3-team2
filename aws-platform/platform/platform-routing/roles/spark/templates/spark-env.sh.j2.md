# roles/spark/templates/spark-env.sh.j2

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/spark/templates/spark-env.sh.j2)

## 역할

Java, 로컬 IP, Worker CPU·메모리, ZooKeeper recovery와 PySpark Python 환경을 지정한다.

SPARK_DAEMON_JAVA_OPTS에는 spark.port.maxRetries=0도 지정한다. Master·Worker의 지정 포트가 이미 사용 중이면 다른 포트로 바꾸지 않고 시작을 실패시킨다. Spark 작업의 재시도 횟수는 spark-defaults.conf의 별도 설정을 사용한다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| java_home |
| ip |
| spark_daemon_mb |
| ansible_facts['processor_vcpus'] |
| spark_worker_mb |
| spark_data_dir |
| spark_log_dir |
| spark_zookeeper_url |
| spark_python |

## 함께 볼 파일

- [roles/spark/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
