# check-mysql.yml: Vault 인증과 MySQL 멤버 상태 조회

[탐색 시작점](../ROUTING-README.md) · [원본](../../check-mysql.yml) · [MySQL 역할](roles/mysql/README.md)

## 대상과 입력

mysql 그룹 전체에 become=true, gather_facts=false로 실행하는 별도 조회 playbook이다. vault_mysql_passwords.root가 존재하고 비어 있지 않은지 먼저 검사한다. 현재 Ubuntu 배포의 /var/run/mysqld/mysqld.sock 소켓과 root 계정을 사용하며 다른 OS의 소켓 경로를 자동으로 선택하지 않는다.

```bash
# platform 디렉터리에서 현재 인벤토리의 MySQL 인증·멤버 목록을 조회한다.
ansible-playbook -i inventory/hosts.current.yml check-mysql.yml --ask-vault-pass
```

## 작업 흐름

Vault root 입력 검사 → mysql CLI로 서버명·인증 계정·replication_group_members 조회 → 반환 코드 확인 → 비밀번호를 제외한 조회 결과 표시 순서다. 비밀번호는 MYSQL_PWD 환경 변수로 전달하며 입력 검사와 조회 작업은 no_log=true다. 원본 stderr는 출력하지 않고 ERROR 1045 여부에 따라 인증 오류 또는 서비스·소켓 확인 메시지로 나눈다.

조회 명령은 changed_when=false, failed_when=false로 결과를 받은 뒤 별도 assert에서 rc=0을 요구한다. check_mode=false이므로 Ansible의 --check 실행에서도 실제 읽기 전용 SQL 조회를 수행한다.

## 검사 경계

호스트·인증 사용자와 MEMBER_HOST/MEMBER_PORT/MEMBER_STATE/MEMBER_ROLE을 표시한다. 멤버 수, 모든 멤버의 ONLINE 상태, Primary 개수는 이 playbook에서 자동 단언하지 않으므로 조회 성공만으로 클러스터 정상이라고 판정하지 않는다. 전체 Cluster 검증은 [MySQL verify](roles/mysql/tasks/verify.yml.md)에서 찾는다.

설치·비밀번호 변경·클러스터 가입·복구 SQL은 실행하지 않는다. 이번 문서 작업은 playbook의 정적 대조이며 원격 MySQL 인증·복제 상태를 확인한 실행 기록은 아니다.
