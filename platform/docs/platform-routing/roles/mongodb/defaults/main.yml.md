# roles/mongodb/defaults/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mongodb/defaults/main.yml)

## 역할

MongoDB 설치·인증·Replica Set의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 3 | mongodb_gpg_key_url | https://pgp.mongodb.com/server-8.0.asc |
| 4 | mongodb_gpg_key_id | 4e7dca05   # 위 키의 key ID 끝 8자리 (rpm의 gpg-pubkey 이름. AL2023에서만 쓴다) |
| 5 | mongodb_packages | [mongodb-org-server, mongodb-mongosh] |
| 8 | mongodb_kernel_blocked_from | "6.19" |
| 10 | mongodb_port | 27017 |
| 11 | mongodb_keyfile | /etc/mongod.keyfile |
| 12 | mongodb_replset_name | infra |
| 15 | mongodb_cache_ratio | 0.4 |
| 16 | mongodb_cache_min_gb | 0.25 |
| 19 | mongodb_no_log | true |

## 함께 볼 파일

- [roles/mongodb/tasks/kernel-debian.yml](../tasks/kernel-debian.yml.md)
- [roles/mongodb/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
