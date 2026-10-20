# roles/mongodb/vars/ubuntu.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mongodb/vars/ubuntu.yml)

## 역할

Ubuntu에서 사용할 MongoDB 설치·인증·Replica Set의 패키지·서비스·경로 등 역할 변수를 지정한다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 2 | mongodb_apt_repo | 아래 목록/매핑/여러 줄 값 참조 |
| 7 | mongodb_user | mongodb |
| 8 | mongodb_group | mongodb |
| 9 | mongodb_data_dir | /var/lib/mongodb |

## 함께 볼 파일

- [roles/mongodb/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
