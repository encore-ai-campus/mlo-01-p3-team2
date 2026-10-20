# roles/firewall/tasks/os-debian.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/firewall/tasks/os-debian.yml)

## 역할

Ubuntu의 nftables 자동 로드를 비활성화하고 ufw 비활성 상태를 확인한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 5 | nftables.service 비활성화 (전용 테이블이 지워지지 않게) | ansible.builtin.systemd_service | name=nftables | 상위 block/play 조건도 확인 |
| 11 | ufw 상태 조회 | ansible.builtin.command | ufw status | 상위 block/play 조건도 확인 |
| 16 | ufw 비활성 확인 | ansible.builtin.assert | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 21 | ufw 서비스 비활성화 | ansible.builtin.systemd_service | name=ufw | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/firewall/tasks/main.yml](main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
