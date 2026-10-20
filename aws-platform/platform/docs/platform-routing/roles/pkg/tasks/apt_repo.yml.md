# roles/pkg/tasks/apt_repo.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/pkg/tasks/apt_repo.yml)

## 역할

apt_repo_* 입력으로 키 파일과 Signed-By가 있는 .sources 저장소를 만든다. 이미 있는 키는 다시 다운로드하지 않는다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 6 | apt 키 디렉터리 | ansible.builtin.file | path=/etc/apt/keyrings; state=directory | 상위 block/play 조건도 확인 |
| 12 | apt 서명 키 확인 ({{ apt_repo_name }}) | ansible.builtin.stat | path=/etc/apt/keyrings/{{ apt_repo_name }}.asc | 상위 block/play 조건도 확인 |
| 17 | apt 서명 키 ({{ apt_repo_name }}) | ansible.builtin.get_url | dest=/etc/apt/keyrings/{{ apt_repo_name }}.asc | not apt_repo_key.stat.exists |
| 24 | apt 저장소 ({{ apt_repo_name }}) | ansible.builtin.copy | dest=/etc/apt/sources.list.d/{{ apt_repo_name }}.sources | 상위 block/play 조건도 확인 |

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
