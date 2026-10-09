# roles/backend/tasks/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/backend/tasks/main.yml)

## 역할

mysql 역할의 repo 작업을 재사용해 MySQL Router를 설치한 뒤 verify 작업을 호출한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 2 | MySQL 저장소 등록 | ansible.builtin.include_role | name=mysql; tasks_from=repo | 상위 block/play 조건도 확인 |
| 7 | 패키지 설치 | ansible.builtin.include_role | name=pkg; tasks_from=install; pkg_names={{ backend_packages }} | 상위 block/play 조건도 확인 |
| 14 | 검증 | ansible.builtin.import_tasks | verify.yml | 상위 block/play 조건도 확인 |

## 함께 볼 파일

- [roles/backend/tasks/verify.yml](verify.yml.md)
- [roles/mysql/tasks/repo.yml](../../mysql/tasks/repo.yml.md)
- [roles/pkg/tasks/install.yml](../../pkg/tasks/install.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
