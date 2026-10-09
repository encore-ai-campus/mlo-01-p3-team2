# backend: Backend의 MySQL Router 패키지

[탐색 시작점](../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

backend 그룹.

MySQL Router 설치 출처와 패키지·버전 검증을 찾을 때 사용한다.

## 현재 작업 흐름

mysql/repo → pkg/install → Router 버전 검증

## 구현 조건

현재 역할은 Router 설치까지 한다. Router bootstrap·서비스 설정·애플리케이션 런타임 설치는 이 역할에 없다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/backend/defaults/main.yml | [main.yml](defaults/main.yml.md) | Backend의 MySQL Router 패키지의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/backend/tasks/main.yml | [main.yml](tasks/main.yml.md) | mysql 역할의 repo 작업을 재사용해 MySQL Router를 설치한 뒤 verify 작업을 호출한다. |
| roles/backend/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | mysqlrouter --version 결과에 8.4.가 포함되는지 확인한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
