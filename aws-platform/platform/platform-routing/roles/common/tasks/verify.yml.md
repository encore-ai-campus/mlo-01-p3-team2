# roles/common/tasks/verify.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/common/tasks/verify.yml)

## 역할

sshd 유효 설정, UTC, NTP 동기화, chrony 선택 시간원과 Leap status를 확인한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 4 | sshd 유효 설정 조회 | ansible.builtin.command | sshd -T | 상위 block/play 조건도 확인 |
| 9 | sshd 유효 설정 검증 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 19 | 시간 상태 조회 | ansible.builtin.command | timedatectl show | 상위 block/play 조건도 확인 |
| 27 | 시간대 검증 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 32 | chrony 시간원 조회 | ansible.builtin.command | chronyc sources | 상위 block/play 조건도 확인 |
| 40 | chrony 동기화 상태 조회 | ansible.builtin.command | chronyc tracking | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/common/tasks/main.yml](main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
