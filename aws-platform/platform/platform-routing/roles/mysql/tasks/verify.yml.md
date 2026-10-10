# roles/mysql/tasks/verify.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/mysql/tasks/verify.yml)

## 역할

dev 접속·시스템 스키마 접근 거부, ReplicaSet AVAILABLE·ONLINE, Backend IP에 한정된 Router 계정을 확인한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | dev 계정으로 SELECT 1 | ansible.builtin.command | mysql -udev -S {{ mysql_socket }} -N -e "SELECT 1 | 상위 block/play 조건도 확인 |
| 13 | dev 계정으로 mysql 스키마 조회 시도 | ansible.builtin.command | mysql -udev -S {{ mysql_socket }} -N -e "SELECT COUNT(*) FROM mysql.user | 상위 block/play 조건도 확인 |
| 23 | ReplicaSet 상태 조회 | ansible.builtin.command | mysqlsh --js --no-wizard --quiet-start=2 | mysql_is_primary and mysql_secondary_ips &#124; length > 0 |
| 32 | ReplicaSet 상태 검증 | ansible.builtin.assert | 아래 작업·인자 참조 | mysql_is_primary and mysql_secondary_ips &#124; length > 0 |
| 44 | Router 계정 확인 | ansible.builtin.command | 아래 작업·인자 참조 | mysql_secondary_ips &#124; length > 0 and groups.get('backend', []) &#124; length > 0 |

## 함께 볼 파일

- [roles/mysql/tasks/main.yml](main.yml.md)
- [roles/mysql/templates/replicaset-status.js.j2](../templates/replicaset-status.js.j2.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
