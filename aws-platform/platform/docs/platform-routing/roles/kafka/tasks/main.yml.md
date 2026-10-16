# roles/kafka/tasks/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/kafka/tasks/main.yml)

## 역할

RAM 기반 heap·노드 ID, 미러 다운로드, 설정·cluster.id·조건부 포맷·서비스 시작을 연결한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | 역할 내부 값 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 13 | 서비스 사용자 | ansible.builtin.user | name={{ kafka_user }} | 상위 block/play 조건도 확인 |
| 21 | 데이터·로그·설정 디렉터리 | ansible.builtin.file | path={{ item.path }}; state=directory | 상위 block/play 조건도 확인 |
| 37 | 설치 여부 확인 | ansible.builtin.stat | path={{ kafka_install_dir }}/bin/kafka-server-start.sh | 상위 block/play 조건도 확인 |
| 42 | tarball 내려받기 (sha512 검증, 미러를 차례로 시도) | block/rescue 제어 | 아래 작업·인자 참조 | not kafka_installed.stat.exists |
| 45 | 첫 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ kafka_tarball }} | 상위 block/play 조건도 확인 |
| 53 | 두 번째와 세 번째 미러 | block/rescue 제어 | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 55 | 두 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ kafka_tarball }} | 상위 block/play 조건도 확인 |
| 63 | 세 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ kafka_tarball }} | 상위 block/play 조건도 확인 |
| 71 | tarball 풀기 | ansible.builtin.unarchive | src=/var/tmp/{{ kafka_tarball }}; dest=/opt | not kafka_installed.stat.exists |
| 81 | tarball 정리 | ansible.builtin.file | path=/var/tmp/{{ kafka_tarball }}; state=absent | 상위 block/play 조건도 확인 |
| 86 | 버전 없는 경로 링크 | ansible.builtin.file | src={{ kafka_install_dir }}; dest={{ kafka_home }}; state=link | 상위 block/play 조건도 확인 |
| 94 | 서비스 현재 상태 | ansible.builtin.systemd | name=kafka | 상위 block/play 조건도 확인 |
| 99 | 브로커 설정 배포 | ansible.builtin.template | src=server.properties.j2; dest={{ kafka_config_dir }}/server.properties | 상위 block/play 조건도 확인 |
| 108 | 로그 설정 배포 | ansible.builtin.template | src=log4j2.yaml.j2; dest={{ kafka_config_dir }}/log4j2.yaml | 상위 block/play 조건도 확인 |
| 117 | systemd unit 배포 | ansible.builtin.template | src=kafka.service.j2; dest=/etc/systemd/system/kafka.service | 상위 block/play 조건도 확인 |
| 129 | 기존 클러스터 ID 조회 | ansible.builtin.shell | grep -h '^cluster.id=' {{ kafka_data_dir }}/meta.properties 2>/dev/null &#124; cut -d= -f2 &#124;&#124; true | 상위 block/play 조건도 확인 |
| 134 | 기존 클러스터 ID 정리 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 138 | 클러스터 ID가 하나인지 확인 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 143 | 새 클러스터 ID 생성 (한 번만) | ansible.builtin.command | {{ kafka_home }}/bin/kafka-storage.sh random-uuid | kafka_known_cluster_ids &#124; length == 0 |
| 152 | 클러스터 ID 확정 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 156 | 스토리지 포맷 | ansible.builtin.command | {{ kafka_home }}/bin/kafka-storage.sh format -t {{ kafka_cluster_id }} -c {{ kafka_config_dir }}/server.properties | kafka_meta_cluster.stdout == '' |
| 163 | kafka 활성화 | ansible.builtin.systemd | name=kafka; state=started | 상위 block/play 조건도 확인 |
| 170 | 설정이 바뀌었으면 다시 시작 | ansible.builtin.systemd | name=kafka; state=restarted | (kafka_config.changed or kafka_log_config.changed or kafka_unit_file.changed) and kafka_before.status.ActiveState == 'active' |
| 177 | broker 응답 대기 | ansible.builtin.wait_for | port={{ kafka_broker_port }} | 상위 block/play 조건도 확인 |
| 183 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/kafka/tasks/verify.yml](verify.yml.md)
- [roles/kafka/templates/kafka.service.j2](../templates/kafka.service.j2.md)
- [roles/kafka/templates/log4j2.yaml.j2](../templates/log4j2.yaml.j2.md)
- [roles/kafka/templates/server.properties.j2](../templates/server.properties.j2.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
