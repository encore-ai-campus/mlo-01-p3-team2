# roles/spark/defaults/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/spark/defaults/main.yml)

## 역할

Spark Standalone Master·Worker의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 3 | spark_version | 4.2.0 |
| 4 | spark_urls | 아래 목록/매핑/여러 줄 값 참조 |
| 9 | spark_sha512 | 3a6559e8546ff387db8fe7a04b8fe4008853b467b972c2e343df8e14a81450534777719fc5d4998dd96519a86fdf9de140cee753c61e2e94db044d5f9555ddc4 |
| 11 | spark_user | spark |
| 12 | spark_install_dir | "/opt/spark-{{ spark_version }}-bin-hadoop3" |
| 13 | spark_home | /opt/spark |
| 14 | spark_config_dir | /etc/spark |
| 15 | spark_data_dir | /var/lib/spark |
| 16 | spark_log_dir | /var/log/spark |
| 18 | spark_master_port | 7077 |
| 19 | spark_master_webui_port | 8080 |
| 20 | spark_worker_port | 7100 |
| 21 | spark_worker_webui_port | 8081 |
| 24 | spark_driver_port | 7078 |
| 25 | spark_block_manager_port | 7079 |
| 26 | spark_port_max_retries | 16 |
| 28 | spark_master_count | 2 |
| 34 | spark_os_reserve_mb | 1024 |
| 35 | spark_daemon_mb | 512 |
| 36 | spark_worker_min_mb | 512 |
| 40 | spark_maven_url | https://repo1.maven.org/maven2 |
| 41 | spark_connector_jars | 아래 목록/매핑/여러 줄 값 참조 |
| 57 | spark_check_classes | 아래 목록/매핑/여러 줄 값 참조 |

## 함께 볼 파일

- [roles/spark/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
