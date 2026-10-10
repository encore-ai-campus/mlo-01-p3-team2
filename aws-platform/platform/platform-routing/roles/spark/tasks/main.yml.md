# roles/spark/tasks/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/spark/tasks/main.yml)

## 역할

Master·Worker 배치, 가용 메모리·IP 확인, Python·Spark·JAR 설치와 환경·unit 배포를 연결한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | 역할 내부 값 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 12 | 메모리 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 18 | 메모리 확인 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 26 | 사설 IP 확인 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 32 | OS별 변수 로드 | ansible.builtin.include_vars | {{ ansible_facts['distribution'] &#124; lower }}.yml | 상위 block/play 조건도 확인 |
| 35 | 패키지 설치 (Python) | ansible.builtin.include_role | name=pkg; tasks_from=install; pkg_names={{ spark_packages }} | 상위 block/play 조건도 확인 |
| 42 | 서비스 사용자 | ansible.builtin.user | name={{ spark_user }} | 상위 block/play 조건도 확인 |
| 50 | 데이터·로그·설정 디렉터리 | ansible.builtin.file | path={{ item.path }}; state=directory | 상위 block/play 조건도 확인 |
| 66 | 설치 여부 확인 | ansible.builtin.stat | path={{ spark_install_dir }}/bin/spark-class | 상위 block/play 조건도 확인 |
| 71 | tarball 내려받기 (sha512 검증, 미러를 차례로 시도) | block/rescue 제어 | 아래 작업·인자 참조 | not spark_installed.stat.exists |
| 74 | 첫 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ spark_tarball }} | 상위 block/play 조건도 확인 |
| 82 | 두 번째와 세 번째 미러 | block/rescue 제어 | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 84 | 두 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ spark_tarball }} | 상위 block/play 조건도 확인 |
| 92 | 세 번째 미러 | ansible.builtin.get_url | dest=/var/tmp/{{ spark_tarball }} | 상위 block/play 조건도 확인 |
| 100 | tarball 풀기 | ansible.builtin.unarchive | src=/var/tmp/{{ spark_tarball }}; dest=/opt | not spark_installed.stat.exists |
| 110 | tarball 정리 | ansible.builtin.file | path=/var/tmp/{{ spark_tarball }}; state=absent | 상위 block/play 조건도 확인 |
| 115 | 버전 없는 경로 링크 | ansible.builtin.file | src={{ spark_install_dir }}; dest={{ spark_home }}; state=link | 상위 block/play 조건도 확인 |
| 122 | 커넥터 JAR 설치 여부 확인 | ansible.builtin.stat | path={{ spark_install_dir }}/jars/{{ item.path &#124; basename }} | 상위 block/play 조건도 확인 |
| 130 | 커넥터 JAR 내려받기 (sha256 검증) | ansible.builtin.get_url | dest={{ spark_install_dir }}/jars/{{ item.item.path &#124; basename }} | not item.stat.exists |
| 145 | 서비스 현재 상태 | ansible.builtin.systemd | name=spark-worker | 상위 block/play 조건도 확인 |
| 150 | spark-env.sh 배포 | ansible.builtin.template | src=spark-env.sh.j2; dest={{ spark_config_dir }}/spark-env.sh | 상위 block/play 조건도 확인 |
| 159 | spark-defaults.conf 배포 | ansible.builtin.template | src=spark-defaults.conf.j2; dest={{ spark_config_dir }}/spark-defaults.conf | 상위 block/play 조건도 확인 |
| 168 | Worker systemd unit 배포 | ansible.builtin.template | src=spark-worker.service.j2; dest=/etc/systemd/system/spark-worker.service | 상위 block/play 조건도 확인 |
| 177 | Master systemd unit 배포 | ansible.builtin.template | src=spark-master.service.j2; dest=/etc/systemd/system/spark-master.service | spark_is_master |
| 187 | 서비스 시작과 활성화 | ansible.builtin.systemd | name={{ item }}; state=started | 상위 block/play 조건도 확인 |
| 195 | 설정이 바뀌었으면 다시 시작 | ansible.builtin.systemd | name={{ item }}; state=restarted | 원본의 목록 또는 여러 줄 조건 확인 |
| 205 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/pkg/tasks/install.yml](../../pkg/tasks/install.yml.md)
- [roles/spark/tasks/verify.yml](verify.yml.md)
- [roles/spark/templates/spark-defaults.conf.j2](../templates/spark-defaults.conf.j2.md)
- [roles/spark/templates/spark-env.sh.j2](../templates/spark-env.sh.j2.md)
- [roles/spark/templates/spark-master.service.j2](../templates/spark-master.service.j2.md)
- [roles/spark/templates/spark-worker.service.j2](../templates/spark-worker.service.j2.md)
- [roles/spark/vars/amazon.yml](../vars/amazon.yml.md)
- [roles/spark/vars/ubuntu.yml](../vars/ubuntu.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
