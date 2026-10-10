# roles/kafka/defaults/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/kafka/defaults/main.yml)

## 역할

Kafka KRaft combined 클러스터의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 4 | kafka_version | 4.3.1 |
| 5 | kafka_scala_version | "2.13" |
| 6 | kafka_urls | 아래 목록/매핑/여러 줄 값 참조 |
| 11 | kafka_sha512 | c7d7b2318cb51aa0c61d3246a51c349210073c5c9b754947ef965a439f2f939e8600f204e134a75ac31faf3829c9370960ef7c6a9886c8a1dbf0339a21f4c54c |
| 13 | kafka_user | kafka |
| 14 | kafka_install_dir | "/opt/kafka_{{ kafka_scala_version }}-{{ kafka_version }}" |
| 15 | kafka_home | /opt/kafka |
| 16 | kafka_config_dir | /etc/kafka |
| 17 | kafka_data_dir | /var/lib/kafka/data |
| 18 | kafka_log_dir | /var/log/kafka |
| 20 | kafka_broker_port | 9092 |
| 21 | kafka_controller_port | 9093 |
| 24 | kafka_heap_ratio | 0.25 |
| 25 | kafka_heap_min_mb | 256 |
| 26 | kafka_heap_max_mb | 6144 |
| 29 | kafka_check_topic | infra-check |

## 함께 볼 파일

- [roles/kafka/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
