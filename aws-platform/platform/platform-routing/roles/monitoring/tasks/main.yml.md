# roles/monitoring/tasks/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/monitoring/tasks/main.yml)

## 역할

OS별 unit·로그·그룹 목록과 monitoring IP를 계산한 뒤 target, collector, verify를 연결한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 4 | OS별 변수 로드 | ansible.builtin.include_vars | {{ ansible_facts['distribution'] &#124; lower }}.yml | 상위 block/play 조건도 확인 |
| 7 | 값 계산 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 13 | 수집 대상 설정 | ansible.builtin.import_tasks | target.yml | 상위 block/play 조건도 확인 |
| 16 | 수집 서버 설정 | ansible.builtin.import_tasks | collector.yml | inventory_hostname in groups['monitoring'] |
| 20 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/monitoring/tasks/collector.yml](collector.yml.md)
- [roles/monitoring/tasks/target.yml](target.yml.md)
- [roles/monitoring/tasks/verify.yml](verify.yml.md)
- [roles/monitoring/vars/amazon.yml](../vars/amazon.yml.md)
- [roles/monitoring/vars/ubuntu.yml](../vars/ubuntu.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
