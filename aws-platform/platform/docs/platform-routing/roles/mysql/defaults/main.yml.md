# roles/mysql/defaults/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/mysql/defaults/main.yml)

## 역할

MySQL 8.4 저장소·버퍼·계정 출처·Cluster 이름·재가입 횟수·clone 데이터 보호 기본값을 정의한다.

## 설정 탐색

| 원본 행 | 키 | 선언값 |
| --- | --- | --- |
| 3 | mysql_repo_baseurl | https://repo.mysql.com/yum/mysql-8.4-community/el/9/$basearch/ |
| 4 | mysql_tools_repo_baseurl | https://repo.mysql.com/yum/mysql-tools-8.4-community/el/9/$basearch/ |
| 5 | mysql_gpg_key_url | https://repo.mysql.com/RPM-GPG-KEY-mysql-2025 |
| 6 | mysql_gpg_key_id | a8d3785c   # 위 키의 key ID 끝 8자리 (rpm의 gpg-pubkey 이름) |
| 7 | mysql_packages | [mysql-community-server, mysql-shell] |
| 9 | mysql_accounts_stamp | /etc/mysql-infra-accounts.sha256 |
| 10 | mysql_admin_accounts_stamp | /etc/mysql-infra-admin-accounts.sha256 |
| 11 | mysql_router_accounts_stamp | /etc/mysql-infra-router-accounts.sha256 |
| 14 | mysql_buffer_pool_ratio | 0.5 |
| 15 | mysql_buffer_pool_min_mb | 128 |
| 18 | mysql_dev_source_groups | [game, backend, spark, bastion] |
| 19 | mysql_failover_extra_source_groups | [bastion] |
| 22 | mysql_dev_privileges | SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES, CREATE VIEW, SHOW VIEW, TRIGGER, EVENT, CREATE ROUTINE, ALTER ROUTINE, EXECUTE, LOCK TABLES, CREATE TEMPORARY TABLES |
| 23 | mysql_system_schemas | [mysql, sys]  # performance_schema는 root도 revoke할 수 없다 (쓰기는 setup_* 테이블 UPDATE 정도로 제한된다) |
| 26 | mysql_cluster_name | infra |
| 27 | mysql_port | 3306 |
| 28 | mysql_cluster_auto_rejoin_tries | 3 |
| 30 | mysql_cluster_allow_clone_data_loss | false |
| 31 | mysql_router_source_groups | [game, spark, backend] |
| 34 | mysql_no_log | true |

## 검증 범위

관련 MySQL·Router 템플릿을 로컬에서 렌더링하고 AdminAPI 모의 시나리오 및 Ansible 인벤토리 검사·playbook 문법 검사를 수행했다. EC2 설치·실제 복제·장애 전환은 실행하지 않았다. YAML·Jinja·JavaScript는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. [검증 기록](../../../verification.md)에서 범위를 확인한다.
