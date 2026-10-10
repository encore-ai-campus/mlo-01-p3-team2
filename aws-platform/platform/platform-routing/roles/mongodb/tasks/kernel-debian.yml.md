# roles/mongodb/tasks/kernel-debian.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/mongodb/tasks/kernel-debian.yml)

## 역할

현재 커널이 기본 기준 6.19 이상이면 GA 커널 패키지를 설치하고 기존 HWE 커널을 제거한 뒤 재부팅·재확인한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 5 | 커널 버전 확인 | ansible.builtin.set_fact | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 9 | GA 커널(linux-aws-lts-24.04) 설치 | ansible.builtin.include_role | name=pkg; tasks_from=install; pkg_names=[linux-aws-lts-24.04] | mongodb_kernel_blocked |
| 19 | 새 커널을 막는 HWE 커널 제거 | ansible.builtin.apt | name={{ (['linux-aws', 'linux-image-aws', 'linux-headers-aws', 'linux-tools-aws']; state=absent | mongodb_kernel_blocked |
| 33 | 재부팅 (새 커널로) | ansible.builtin.reboot | 아래 작업·인자 참조 | mongodb_kernel_blocked |
| 38 | 커널 확인 | ansible.builtin.command | uname -r | mongodb_kernel_blocked |

## 함께 볼 파일

- [roles/mongodb/defaults/main.yml](../defaults/main.yml.md)
- [roles/mongodb/tasks/main.yml](main.yml.md)
- [roles/pkg/tasks/install.yml](../../pkg/tasks/install.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
