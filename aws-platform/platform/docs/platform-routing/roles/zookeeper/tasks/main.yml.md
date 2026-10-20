# roles/zookeeper/tasks/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/zookeeper/tasks/main.yml)

## 역할

호스트명 기반 myid, 다운로드·데이터·설정·logback·unit과 시작·검증을 연결한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | 역할 내부 값 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 9 | 서비스 사용자 | ansible.builtin.user | name={{ zookeeper_user }} | 상위 block/play 조건도 확인 |
| 17 | 데이터·로그·설정 디렉터리 | ansible.builtin.file | path={{ item.path }}; state=directory | 상위 block/play 조건도 확인 |
| 32 | 설치 여부 확인 | ansible.builtin.stat | path={{ zookeeper_install_dir }}/bin/zkServer.sh | 상위 block/play 조건도 확인 |
| 37 | tarball 내려받기 (sha512 검증, 미러를 차례로 시도) | block/rescue 제어 | 아래 작업·인자 참조 | not zookeeper_installed.stat.exists |
| 40 | 첫 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ zookeeper_tarball }} | 상위 block/play 조건도 확인 |
| 48 | 두 번째와 세 번째 미러 | block/rescue 제어 | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 50 | 두 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ zookeeper_tarball }} | 상위 block/play 조건도 확인 |
| 58 | 세 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ zookeeper_tarball }} | 상위 block/play 조건도 확인 |
| 66 | tarball 풀기 | ansible.builtin.unarchive | src=/var/tmp/{{ zookeeper_tarball }}; dest=/opt | not zookeeper_installed.stat.exists |
| 76 | tarball 정리 | ansible.builtin.file | path=/var/tmp/{{ zookeeper_tarball }}; state=absent | 상위 block/play 조건도 확인 |
| 81 | 버전 없는 경로 링크 | ansible.builtin.file | src={{ zookeeper_install_dir }}; dest={{ zookeeper_home }}; state=link | 상위 block/play 조건도 확인 |
| 89 | 서비스 현재 상태 | ansible.builtin.systemd | name=zookeeper | 상위 block/play 조건도 확인 |
| 94 | myid | ansible.builtin.copy | dest={{ zookeeper_data_dir }}/myid | 상위 block/play 조건도 확인 |
| 103 | zoo.cfg 배포 | ansible.builtin.template | src=zoo.cfg.j2; dest={{ zookeeper_config_dir }}/zoo.cfg | 상위 block/play 조건도 확인 |
| 113 | logback 설정 | ansible.builtin.template | src=logback.xml.j2; dest={{ zookeeper_config_dir }}/logback.xml | 상위 block/play 조건도 확인 |
| 122 | systemd unit 배포 | ansible.builtin.template | src=zookeeper.service.j2; dest=/etc/systemd/system/zookeeper.service | 상위 block/play 조건도 확인 |
| 131 | zookeeper 활성화 | ansible.builtin.systemd | name=zookeeper; state=started | 상위 block/play 조건도 확인 |
| 138 | 설정이 바뀌었으면 다시 시작 | ansible.builtin.systemd | name=zookeeper; state=restarted | (zookeeper_myid_file.changed or zookeeper_config.changed or zookeeper_logback.changed or zookeeper_unit_file.changed) and zookeeper_before.status.ActiveState == 'active' |
| 145 | ZooKeeper 응답 대기 | ansible.builtin.wait_for | port={{ zookeeper_client_port }} | 상위 block/play 조건도 확인 |
| 151 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/zookeeper/tasks/verify.yml](verify.yml.md)
- [roles/zookeeper/templates/logback.xml.j2](../templates/logback.xml.j2.md)
- [roles/zookeeper/templates/zoo.cfg.j2](../templates/zoo.cfg.j2.md)
- [roles/zookeeper/templates/zookeeper.service.j2](../templates/zookeeper.service.j2.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
