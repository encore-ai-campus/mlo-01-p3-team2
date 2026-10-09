# roles/mysql/tasks/root-password-debian.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/tasks/root-password-debian.yml)

## 역할

root의 auth_socket 여부를 확인해 비밀번호 정책 컴포넌트와 caching_sha2_password를 설정한다. 비기본 노드는 변경 시 GTID·바이너리 로그를 초기화한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 4 | root 인증 방식 확인 | ansible.builtin.command | mysql -uroot -S {{ mysql_socket }} -N -e "SELECT plugin FROM mysql.user WHERE user = 'root' AND host = 'localhost' | 상위 block/play 조건도 확인 |
| 13 | 비밀번호 정책 컴포넌트 확인 | ansible.builtin.command | mysql -uroot -S {{ mysql_socket }} -N -e "SELECT COUNT(*) FROM mysql.component WHERE component_urn = 'file://component_validate_password' | mysql_root_plugin.stdout == 'auth_socket' |
| 23 | root 비밀번호 설정 (auth_socket에서 비밀번호 방식으로) | ansible.builtin.command | mysql -uroot -S {{ mysql_socket }} | mysql_root_plugin.stdout == 'auth_socket' |

## 함께 볼 파일

- [roles/mysql/tasks/main.yml](main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
