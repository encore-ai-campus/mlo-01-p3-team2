# pkg: 공용 패키지 설치와 APT 저장소

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

다른 역할이 include_role의 tasks_from으로 호출하는 보조 역할.

패키지 설치·잠금 대기·APT 키 재다운로드 방지 동작을 수정할 때 찾는다.

## 현재 작업 흐름

install: 설치 목록 조회 → 누락 패키지 계산 → dnf/apt; apt_repo: 키 확인 → 키 다운로드 → deb822 sources 파일

## 구현 조건

tasks/main.yml은 없다. install 또는 apt_repo를 명시한다. 이미 설치된 패키지는 저장소 접속을 생략하지만 새 패키지 설치에는 저장소 접근이 필요하다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/pkg/tasks/apt_repo.yml | [apt_repo.yml](tasks/apt_repo.yml.md) | apt_repo_* 입력으로 키 파일과 Signed-By가 있는 .sources 저장소를 만든다. 이미 있는 키는 다시 다운로드하지 않는다. |
| roles/pkg/tasks/install.yml | [install.yml](tasks/install.yml.md) | pkg_names에서 이미 설치된 패키지를 빼고 OS별 dnf/apt로 누락 패키지만 설치한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
