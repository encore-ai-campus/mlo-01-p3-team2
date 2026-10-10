# roles/mongodb/tasks/verify.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mongodb/tasks/verify.yml)

## 역할

모든 노드의 인증·계정 권한과 첫 노드의 Replica Set 멤버 상태·실제 복제를 확인한다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 4 | 노드 확인 | ansible.builtin.command | mongosh --nodb --quiet | 상위 block/play 조건도 확인 |
| 19 | Replica Set 상태와 복제 확인 | ansible.builtin.command | mongosh --nodb --quiet | mongodb_is_first and mongodb_replset |

## 함께 볼 파일

- [roles/mongodb/tasks/main.yml](main.yml.md)
- [roles/mongodb/templates/check-node.js.j2](../templates/check-node.js.j2.md)
- [roles/mongodb/templates/check-replset.js.j2](../templates/check-replset.js.j2.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
