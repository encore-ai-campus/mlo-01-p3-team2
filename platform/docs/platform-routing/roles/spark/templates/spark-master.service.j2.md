# roles/spark/templates/spark-master.service.j2

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/spark/templates/spark-master.service.j2)

## 역할

사설 IP와 Master RPC·UI 포트로 Spark Master를 실행하고 master.log에 기록한다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| spark_user |
| spark_home |
| spark_config_dir |
| ip |
| spark_master_port |
| spark_master_webui_port |
| spark_log_dir |

## systemd 선언

| 원본 행 | 설정 |
| --- | --- |
| 3 | Description=Apache Spark Master |
| 4 | After=network-online.target zookeeper.service |
| 5 | Wants=network-online.target |
| 8 | User={{ spark_user }} |
| 9 | Group={{ spark_user }} |
| 10 | Environment=SPARK_HOME={{ spark_home }} |
| 11 | Environment=SPARK_CONF_DIR={{ spark_config_dir }} |
| 12 | ExecStart={{ spark_home }}/bin/spark-class org.apache.spark.deploy.master.Master --host {{ ip }} --port {{ spark_master_port }} --webui-port {{ spark_master_webui_port }} |
| 13 | StandardOutput=append:{{ spark_log_dir }}/master.log |
| 14 | StandardError=inherit |
| 15 | Restart=on-failure |
| 16 | RestartSec=5 |
| 17 | LimitNOFILE=65536 |
| 20 | WantedBy=multi-user.target |

## 함께 볼 파일

- [roles/spark/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
