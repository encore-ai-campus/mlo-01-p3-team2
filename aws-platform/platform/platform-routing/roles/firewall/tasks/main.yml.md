# roles/firewall/tasks/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/firewall/tasks/main.yml)

## 역할

후보 규칙을 문법 검사하고 복구 타이머를 예약한 뒤 새 SSH 접속 확인 후 정식 규칙으로 교체한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 2 | OS별 변수 로드 | ansible.builtin.include_vars | {{ ansible_facts['distribution'] &#124; lower }}.yml | 상위 block/play 조건도 확인 |
| 5 | 패키지 설치 | ansible.builtin.include_role | name=pkg; tasks_from=install; pkg_names={{ firewall_packages }} | 상위 block/play 조건도 확인 |
| 12 | Ubuntu 전용 설정 | ansible.builtin.include_tasks | os-debian.yml | ansible_facts['os_family'] == 'Debian' |
| 16 | 규칙 디렉터리 | ansible.builtin.file | path=/etc/nftables; state=directory | 상위 block/play 조건도 확인 |
| 24 | 후보 규칙 파일 생성 | ansible.builtin.template | src=infra-fw.nft.j2; dest=/etc/nftables/infra-fw.nft.new | 상위 block/play 조건도 확인 |
| 34 | 현재 규칙 파일과 비교 | ansible.builtin.command | cmp -s /etc/nftables/infra-fw.nft.new /etc/nftables/infra-fw.nft | 상위 block/play 조건도 확인 |
| 40 | 적용된 테이블 조회 | ansible.builtin.command | nft list table inet infra_fw | 상위 block/play 조건도 확인 |
| 46 | 적용 대상 판단 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 52 | 방화벽 적용 | block/rescue 제어 | 아래 작업·인자 참조 | firewall_needs_apply |
| 55 | 남아 있는 복구 타이머 정리 | ansible.builtin.command | systemctl stop infra-fw-rollback.timer infra-fw-rollback.service | 상위 block/play 조건도 확인 |
| 60 | 복구 타이머 예약 | ansible.builtin.command | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 66 | 규칙 적용 | ansible.builtin.command | nft -f /etc/nftables/infra-fw.nft.new | 상위 block/play 조건도 확인 |
| 71 | 연결 초기화 | ansible.builtin.meta | reset_connection | 상위 block/play 조건도 확인 |
| 74 | 새 연결 확인 | ansible.builtin.wait_for_connection | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 78 | 복구 타이머 해제 | ansible.builtin.command | systemctl stop infra-fw-rollback.timer | 상위 block/play 조건도 확인 |
| 82 | 정식 규칙 파일로 교체 | ansible.builtin.command | mv /etc/nftables/infra-fw.nft.new /etc/nftables/infra-fw.nft | 상위 block/play 조건도 확인 |
| 86 | 후보 규칙 파일 정리 | ansible.builtin.command | rm -f /etc/nftables/infra-fw.nft.new | 상위 block/play 조건도 확인 |
| 90 | 부팅 때 로드하는 서비스 배포 | ansible.builtin.template | src=infra-firewall.service.j2; dest=/etc/systemd/system/infra-firewall.service | 상위 block/play 조건도 확인 |
| 98 | 부팅 때 로드하는 서비스 활성화 | ansible.builtin.systemd_service | name=infra-firewall.service | 상위 block/play 조건도 확인 |
| 104 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/firewall/tasks/os-debian.yml](os-debian.yml.md)
- [roles/firewall/tasks/verify.yml](verify.yml.md)
- [roles/firewall/templates/infra-firewall.service.j2](../templates/infra-firewall.service.j2.md)
- [roles/firewall/templates/infra-fw.nft.j2](../templates/infra-fw.nft.j2.md)
- [roles/firewall/vars/amazon.yml](../vars/amazon.yml.md)
- [roles/firewall/vars/main.yml](../vars/main.yml.md)
- [roles/firewall/vars/ubuntu.yml](../vars/ubuntu.yml.md)
- [roles/pkg/tasks/install.yml](../../pkg/tasks/install.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
