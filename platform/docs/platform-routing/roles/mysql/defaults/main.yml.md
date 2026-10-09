# roles/mysql/defaults/main.yml

[탐색 시작점](../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/defaults/main.yml)

## 역할

MySQL 설치·계정·InnoDB ReplicaSet의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다.

## 설정 탐색

아래는 최상위 키와 선언값이다. 목록·매핑의 상세는 원본에서 확인한다. 주석은 구현 보증이 아닌 설명이다.

| 원본 행 | 키 | 선언값/구조 |
| --- | --- | --- |
| 3 | mysql_repo_baseurl | https://repo.mysql.com/yum/mysql-8.4-community/el/9/$basearch/ |
| 4 | mysql_tools_repo_baseurl | https://repo.mysql.com/yum/mysql-tools-8.4-community/el/9/$basearch/ |
| 5 | mysql_gpg_key_url | https://repo.mysql.com/RPM-GPG-KEY-mysql-2025 |
| 6 | mysql_gpg_key_id | a8d3785c   # 위 키의 key ID 끝 8자리 (rpm의 gpg-pubkey 이름) |
| 7 | mysql_packages | [mysql-community-server, mysql-shell] |
| 9 | mysql_accounts_stamp | /etc/mysql-infra-accounts.sha256 |
| 12 | mysql_buffer_pool_ratio | 0.5 |
| 13 | mysql_buffer_pool_min_mb | 128 |
| 16 | mysql_dev_source_groups | [backend, spark, bastion] |
| 17 | mysql_failover_extra_source_groups | [bastion] |
| 20 | mysql_dev_privileges | SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES, CREATE VIEW, SHOW VIEW, TRIGGER, EVENT, CREATE ROUTINE, ALTER ROUTINE, EXECUTE, LOCK TABLES, CREATE TEMPORARY TABLES |
| 21 | mysql_system_schemas | [mysql, sys]  # performance_schema는 root도 revoke할 수 없다 (쓰기는 setup_* 테이블 UPDATE 정도로 제한된다) |
| 23 | mysql_replicaset_name | infra |
| 26 | mysql_no_log | true |

## 함께 볼 파일

- [roles/mysql/tasks/main.yml](../tasks/main.yml.md)
- [roles/mysql/tasks/repo.yml](../tasks/repo.yml.md)
- [roles/mysql/vars/ubuntu.yml](../vars/ubuntu.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
