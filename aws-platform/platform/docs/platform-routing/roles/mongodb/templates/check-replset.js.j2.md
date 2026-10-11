# roles/mongodb/templates/check-replset.js.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mongodb/templates/check-replset.js.j2)

## 역할

PRIMARY 하나와 나머지 SECONDARY를 확인하고 임시 문서의 모든 멤버 복제 후 삭제를 검사한다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| mongodb_uri |
| groups['mongodb'] &#124; length - 1 |

## 함께 볼 파일

- [roles/mongodb/tasks/main.yml](../tasks/main.yml.md)
- [roles/mongodb/tasks/verify.yml](../tasks/verify.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
