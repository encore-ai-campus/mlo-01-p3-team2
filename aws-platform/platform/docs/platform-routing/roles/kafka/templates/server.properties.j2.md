# roles/kafka/templates/server.properties.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/kafka/templates/server.properties.j2)

## 역할

KRaft broker+controller, 정적 voters, 사설 IP PLAINTEXT 리스너와 복제 수·ISR·토픽 자동 생성 정책을 지정한다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| kafka_node_id |
| h &#124; regex_search('[0-9]+$') |
| hostvars[h].ip |
| kafka_controller_port |
| ',' if not loop.last |
| ip |
| kafka_broker_port |
| kafka_data_dir |

## 함께 볼 파일

- [roles/kafka/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
