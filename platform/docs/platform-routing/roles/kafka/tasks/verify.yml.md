# roles/kafka/tasks/verify.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/kafka/tasks/verify.yml)

## 역할

서비스 enabled/active, controller quorum, 복제 수 3 임시 토픽의 ISR·produce·consume을 확인하고 토픽을 삭제한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | kafka 서비스 상태 | ansible.builtin.systemd | name=kafka | 상위 block/play 조건도 확인 |
| 10 | controller quorum 조회 | ansible.builtin.command | {{ kafka_home }}/bin/kafka-metadata-quorum.sh --bootstrap-server {{ ip }}:{{ kafka_broker_port }} describe --status | kafka_node_id &#124; int == (groups['kafka'][0] &#124; regex_search('[0-9]+$') &#124; int) |
| 21 | controller quorum 검증 | ansible.builtin.assert | 아래 작업·인자 참조 | kafka_quorum is not skipped |
| 29 | 임시 토픽 생성 | ansible.builtin.command | 아래 작업·인자 참조 | kafka_quorum is not skipped |
| 38 | 임시 토픽 상태 조회 (ISR) | ansible.builtin.command | {{ kafka_home }}/bin/kafka-topics.sh --bootstrap-server {{ ip }}:{{ kafka_broker_port }} --describe --topic {{ kafka_check_topic }} | kafka_quorum is not skipped |
| 49 | produce (acks=all) | ansible.builtin.command | 아래 작업·인자 참조 | kafka_quorum is not skipped |
| 60 | consume | ansible.builtin.command | 아래 작업·인자 참조 | kafka_quorum is not skipped |
| 71 | 임시 토픽 삭제 | ansible.builtin.command | {{ kafka_home }}/bin/kafka-topics.sh --bootstrap-server {{ ip }}:{{ kafka_broker_port }} --delete --topic {{ kafka_check_topic }} | kafka_quorum is not skipped |

## 함께 볼 파일

- [roles/kafka/tasks/main.yml](main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
