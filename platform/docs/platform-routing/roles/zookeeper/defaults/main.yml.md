# roles/zookeeper/defaults/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/zookeeper/defaults/main.yml)

## 역할

Spark 복구용 ZooKeeper ensemble의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 3 | zookeeper_version | 3.9.6 |
| 4 | zookeeper_urls | 아래 목록/매핑/여러 줄 값 참조 |
| 9 | zookeeper_sha512 | e999626df06de30dc8bb53bb51da9bb786b1658406adafc6b92f104d72ca25e869f70a57c83a726f8b9558cc0fb519fc20f201aa5d6da09884bc4be5fe6dd3b0 |
| 12 | zookeeper_group | spark |
| 14 | zookeeper_user | zookeeper |
| 15 | zookeeper_install_dir | "/opt/apache-zookeeper-{{ zookeeper_version }}-bin" |
| 16 | zookeeper_home | /opt/zookeeper |
| 17 | zookeeper_config_dir | /etc/zookeeper |
| 18 | zookeeper_data_dir | /var/lib/zookeeper |
| 19 | zookeeper_log_dir | /var/log/zookeeper |
| 21 | zookeeper_client_port | 2181 |
| 22 | zookeeper_peer_port | 2888 |
| 23 | zookeeper_election_port | 3888 |
| 26 | zookeeper_heap_mb | 256 |

## 함께 볼 파일

- [roles/zookeeper/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
