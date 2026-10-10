# roles/mysql/tasks/root-password-redhat.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../roles/mysql/tasks/root-password-redhat.yml)

## 역할

Vault 비밀번호 접속이 실패하면 오류 로그의 임시 root 비밀번호로 변경한다. 비기본 노드는 변경 시 GTID·바이너리 로그를 초기화한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 4 | root 비밀번호가 이미 설정되었는지 확인 | ansible.builtin.command | mysql -uroot -S {{ mysql_socket }} -e "SELECT 1 | 상위 block/play 조건도 확인 |
| 13 | root 임시 비밀번호 조회 | ansible.builtin.shell | grep 'temporary password' {{ mysql_error_log }} &#124; tail -1 &#124; awk '{print $NF}' | mysql_root_check.rc != 0 |
| 22 | root 비밀번호 변경 | ansible.builtin.command | mysql --connect-expired-password -uroot -S {{ mysql_socket }} | mysql_root_check.rc != 0 |

## 함께 볼 파일

- [roles/mysql/tasks/main.yml](main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
