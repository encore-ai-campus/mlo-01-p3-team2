# inventory/group_vars/all/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../../README.md) · [원본 파일](../../../../../inventory/group_vars/all/main.yml)

## 역할

기본 사설 IP 접속과 첫 Bastion 공인 IP를 통한 ProxyCommand를 계산한다. Bastion 그룹이 없으면 직접 접속한다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 2 | ansible_host | "{{ ip }}" |
| 6 | ansible_ssh_common_args | 아래 목록/매핑/여러 줄 값 참조 |

## 함께 볼 파일

- [inventory/group_vars/all/vault.example.yml](vault.example.yml.md)
- [inventory/group_vars/bastion.yml](../bastion.yml.md)
- [inventory/hosts.example.yml](../../hosts.example.yml.md)
- [site.yml](../../../site.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
