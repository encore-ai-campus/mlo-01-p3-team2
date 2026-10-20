# roles/backend/tasks/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/backend/tasks/main.yml)

## 역할

game·ad·spark·mysql·backend에서 Router 설치 → 관리 범위 확인 → bootstrap → 해시 기록 → systemd 서비스 → 검증을 수행한다.

## 작업 탐색

행은 현재 원본의 선언 위치다. include·play의 상위 조건도 함께 적용된다.

| 원본 행 | 작업 이름 | 모듈/제어 | 조건 |
| --- | --- | --- | --- |
| 2 | Router 입력 확인 | ansible.builtin.assert | 상위 조건 확인 |
| 16 | MySQL 저장소 등록 | ansible.builtin.include_role | 상위 조건 확인 |
| 21 | 패키지 설치 | ansible.builtin.include_role | 상위 조건 확인 |
| 28 | Router 시스템 그룹 | ansible.builtin.group | 상위 조건 확인 |
| 33 | Router 시스템 사용자 | ansible.builtin.user | 상위 조건 확인 |
| 41 | Router 설정 디렉터리 | ansible.builtin.file | 상위 조건 확인 |
| 49 | 기존 Router 설정 확인 | ansible.builtin.stat | 상위 조건 확인 |
| 54 | 기존 Router 설정 읽기 | ansible.builtin.slurp | backend_router_config_stat.stat.exists |
| 61 | Router 초기 설정 해시 조회 | ansible.builtin.slurp | 상위 조건 확인 |
| 68 | 기존 Router 관리 범위 확인 | ansible.builtin.assert | 상위 조건 확인 |
| 76 | Router 초기 설정 입력 계산 | ansible.builtin.set_fact | 상위 조건 확인 |
| 84 | Router 재구성 여부 계산 | ansible.builtin.set_fact | 상위 조건 확인 |
| 92 | 재구성 전 Router 중지 | ansible.builtin.service | backend_router_needs_bootstrap |
| 98 | MySQL Router 초기 설정 | ansible.builtin.command | backend_router_needs_bootstrap |
| 118 | Router 초기 설정 해시 기록 | ansible.builtin.copy | backend_router_needs_bootstrap |
| 127 | Router systemd 서비스 배포 | ansible.builtin.template | 상위 조건 확인 |
| 136 | Router 서비스 활성화 | ansible.builtin.systemd_service | 상위 조건 확인 |
| 143 | 검증 | ansible.builtin.import_tasks | 상위 조건 확인 |

## 동작과 제한

Router는 기본 127.0.0.1:6446(RW), 6447(RO)에 바인딩한다. 기존 설정에 metadata_cache가 있는데 관리 해시가 없으면 자동 인계하지 않는다. bootstrap은 router 계정, --account-create=never, --strict, --disable-rest, --disable-rw-split, --force를 사용한다. 두 비밀번호 입력은 stdin으로 전달하고 no_log로 숨긴다. 초기 설정 후 keyring은 mysqlrouter가 관리한다. 기존 관리 대상의 변경 시 서비스를 중지하므로 유지보수 창에서 수행한다. bootstrap 실패 시 해시는 기록하지 않으며 서비스도 자동 재시작하지 않는다. 기본 /etc/mysqlrouter/mysqlrouter.conf 경로만 지원한다.

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
