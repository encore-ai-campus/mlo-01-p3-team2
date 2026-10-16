# roles/zookeeper/templates/zookeeper.service.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/zookeeper/templates/zookeeper.service.j2)

## 역할

Java·ZOOCFGDIR·heap 환경으로 ZooKeeper를 foreground 실행한다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| zookeeper_user |
| java_home |
| zookeeper_config_dir |
| zookeeper_log_dir |
| zookeeper_heap_mb |
| zookeeper_home |

## systemd 선언

| 원본 행 | 설정 |
| --- | --- |
| 3 | Description=Apache ZooKeeper |
| 4 | After=network-online.target |
| 5 | Wants=network-online.target |
| 8 | User={{ zookeeper_user }} |
| 9 | Group={{ zookeeper_user }} |
| 10 | Environment=JAVA_HOME={{ java_home }} |
| 11 | Environment=ZOOCFGDIR={{ zookeeper_config_dir }} |
| 12 | Environment=ZOO_LOG_DIR={{ zookeeper_log_dir }} |
| 13 | Environment="JVMFLAGS=-Xms{{ zookeeper_heap_mb }}m -Xmx{{ zookeeper_heap_mb }}m" |
| 14 | ExecStart={{ zookeeper_home }}/bin/zkServer.sh start-foreground |
| 15 | Restart=on-failure |
| 16 | RestartSec=5 |
| 17 | LimitNOFILE=65536 |
| 20 | WantedBy=multi-user.target |

## 함께 볼 파일

- [roles/zookeeper/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
