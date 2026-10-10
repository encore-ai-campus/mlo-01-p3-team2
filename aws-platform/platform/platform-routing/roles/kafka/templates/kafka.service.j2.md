# roles/kafka/templates/kafka.service.j2

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/kafka/templates/kafka.service.j2)

## 역할

Java·heap·로그 환경으로 kafka-server-start.sh를 실행하며 실패 시 재시작한다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| kafka_user |
| java_home |
| kafka_heap_mb |
| kafka_log_dir |
| kafka_config_dir |
| kafka_home |

## systemd 선언

| 원본 행 | 설정 |
| --- | --- |
| 3 | Description=Apache Kafka (KRaft broker + controller) |
| 4 | After=network-online.target |
| 5 | Wants=network-online.target |
| 8 | User={{ kafka_user }} |
| 9 | Group={{ kafka_user }} |
| 10 | Environment=JAVA_HOME={{ java_home }} |
| 11 | Environment="KAFKA_HEAP_OPTS=-Xms{{ kafka_heap_mb }}m -Xmx{{ kafka_heap_mb }}m" |
| 12 | Environment=LOG_DIR={{ kafka_log_dir }} |
| 13 | Environment="KAFKA_LOG4J_OPTS=-Dlog4j2.configurationFile=file:{{ kafka_config_dir }}/log4j2.yaml" |
| 14 | ExecStart={{ kafka_home }}/bin/kafka-server-start.sh {{ kafka_config_dir }}/server.properties |
| 15 | Restart=on-failure |
| 16 | RestartSec=5 |
| 17 | LimitNOFILE=100000 |
| 18 | TimeoutStopSec=120 |
| 21 | WantedBy=multi-user.target |

## 함께 볼 파일

- [roles/kafka/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
