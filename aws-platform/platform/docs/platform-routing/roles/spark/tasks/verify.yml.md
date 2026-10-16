# roles/spark/tasks/verify.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/spark/tasks/verify.yml)

## 역할

서비스 active/enabled, ALIVE Master 하나·STANDBY·Worker 수를 확인하고 infra-check PySpark 작업을 제출한다.

Master의 내부 HTTP 조회는 프록시를 우회하고 연결 대기 3초·요청 전체 10초로 제한한다. 포트가 차단됐을 때 한 요청을 무기한 기다리지 않도록 하며 기존 30회·5초 간격 재시도와 최종 상태 단언은 유지한다.

## 작업 탐색

첫 Spark 서버가 앞 spark_master_count대의 Master UI /json/ 응답을 조회한다. 활성 Master 한 대가 전체 Spark 그룹 수만큼의 Worker를 등록하고, 나머지 Master가 STANDBY인지 검사한다. PySpark 제출에서는 infra-check 작업의 INFRA_SPARK_OK 출력을 확인한다. 서비스가 active인 것만으로 이 두 단계까지 통과했다고 판단하지 않는다. 내부 조회·작업 통신은 [Spark 포트 설정](../README.md#프라이빗-서버의-통신-포트)과 AWS SG 범위가 함께 맞아야 한다.

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | 서비스 상태 조회 | ansible.builtin.systemd | name={{ item }} | 상위 block/play 조건도 확인 |
| 9 | 서비스 상태 검증 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 17 | Master 상태 조회 | ansible.builtin.shell | 아래 작업·인자 참조 | inventory_hostname == groups['spark'][0] |
| 34 | Master 이중화 검증 | ansible.builtin.assert | 아래 작업·인자 참조 | inventory_hostname == groups['spark'][0] |
| 43 | 검증 작업 배포 | ansible.builtin.template | src=infra-check.py.j2; dest={{ spark_data_dir }}/infra-check.py | inventory_hostname == groups['spark'][0] |
| 52 | PySpark 작업 제출 | ansible.builtin.command | 아래 작업·인자 참조 | inventory_hostname == groups['spark'][0] |

## 함께 볼 파일

- [roles/spark/tasks/main.yml](main.yml.md)
- [roles/spark/templates/infra-check.py.j2](../templates/infra-check.py.j2.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
