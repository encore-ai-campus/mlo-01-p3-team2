# MySQL 전체 중단 자동 복구

`mysql-recovery.yml`은 기존 InnoDB Cluster `infra`에 복구 도구를 설치한다. DB 초기화나 신규 클러스터 생성은 하지 않는다.

## 실행 위치와 조건

- 실행 서버: `mysql-1` (10.30.10.111). Primary를 mysql-1로 고정하는 설정은 아니다.
- systemd 타이머: `mysql-cluster-recovery.timer`.
- 부팅 2분 뒤 시작하고, 검사/복구 실행이 끝난 뒤 2분 후 다시 검사한다. 실행 중에는 중복 실행하지 않는다.
- mysql-1/2/3 모두 연결되고 서버 UUID, 클러스터 메타데이터, 멤버 목록이 설치 당시 구성과 일치해야 한다.
- 정상 3대 ONLINE/Primary 1대 상태는 조회만 한다.
- 3대 모두 OFFLINE이고 읽기 전용일 때, 모든 서버의 GTID를 포함하는 서버를 선택한다.
- `dba.rebootClusterFromCompleteOutage('infra', {dryRun: true})` 성공 후 상태가 변하지 않았는지 다시 확인하고 실제 복구한다.
- 일부 장애, 접속 불가, RECOVERING/ERROR, 데이터 이력 충돌, 증분 복구에 필요한 binlog 삭제는 자동 강제 복구하지 않는다. 다음 검사에서 재확인하며 원인은 journal에 남긴다.
- `force`, clone, 메타데이터 삭제, GTID 초기화는 사용하지 않는다.
- mysql-1 자체가 꺼져 있으면 이 검사도 실행되지 않는다. 정상 클러스터의 기존 Group Replication 자동 장애 전환은 별도 동작이다.

MySQL 공식 복구 절차: [Rebooting a Cluster from a Major Outage](https://dev.mysql.com/doc/mysql-shell/8.0/en/reboot-outage.html).

## 설치

WSL의 프로젝트 Ansible 가상환경과 Vault 암호 파일을 사용한다. 인벤토리의 배스천 공인 IP는 현재 주소여야 한다.

```bash
# 프로젝트 환경에서 MySQL 3대 전체를 대상으로 설치한다.
ansible-playbook -i inventory/hosts.current.yml mysql-recovery.yml --ask-vault-pass
```

이미 `ANSIBLE_VAULT_PASSWORD_FILE`을 설정했다면 `--ask-vault-pass`를 생략한다. `--limit mysql-1`만으로 설치하지 않는다. 3대의 데이터 볼륨 UUID와 기존 DB 식별자를 확인해야 한다.

처음 검토할 때 타이머를 켜지 않으려면 `-e mysql_recovery_enable_timer=false`를 추가한다. 이 값은 재실행할 때 기존 타이머도 중지·비활성화한다.

설치 파일:

| 위치 | 대상 | 용도 |
|---|---|---|
| `/usr/local/lib/mysql-cluster-recovery/recovery.js` | mysql-1 | 상태 검사와 전체 중단 복구 |
| `/etc/mysql-cluster-recovery/config.json` | mysql-1 | Vault에서 받은 접속 비밀번호와 고정된 DB 식별자, root:root 0600 |
| `/etc/systemd/system/mysql-cluster-recovery.service` | mysql-1 | 한 번의 검사/복구 실행, 최대 10분 |
| `/etc/systemd/system/mysql-cluster-recovery.timer` | mysql-1 | 부팅 후 및 주기적 실행 |
| `/usr/local/sbin/mysql-check-data-mount` | MySQL 3대 | 데이터 볼륨과 MySQL bind mount UUID 검사 |
| `/etc/systemd/system/mysql.service.d/30-data-mount-guard.conf` | MySQL 3대 | MySQL 시작 전 마운트 검사 |

설치 과정은 MySQL을 재시작하지 않는다. 마운트 보호 설정은 다음 MySQL 시작 때부터 적용된다. 볼륨을 교체하거나 서버/클러스터를 재구축했으면 식별자를 확인한 뒤 다시 배포한다. 비밀번호 변경 시에도 Vault 값을 바꾸고 재배포한다.

## mysql-1에서 확인

```bash
# 다음 실행 시각과 활성화 상태
sudo systemctl list-timers mysql-cluster-recovery.timer
sudo systemctl is-enabled mysql-cluster-recovery.timer

# 최근 실행 결과
sudo journalctl -u mysql-cluster-recovery.service -n 60 --no-pager

# 타이머와 같은 서비스를 즉시 한 번 실행
sudo systemctl start mysql-cluster-recovery.service

# 정기 실행 중지 (DB 서비스와 데이터는 유지)
sudo systemctl disable --now mysql-cluster-recovery.timer
```

`HEALTHY`는 변경 없이 정상 확인, `RECOVERED`는 복구 후 3대 ONLINE 확인, `RECOVERY_REFUSED`는 자동 복구 조건을 만족하지 않아 중단한 것이다. oneshot 서비스는 성공 후 `inactive (dead)`가 정상이며 `Result=success`와 journal을 함께 확인한다.

별도 알림 서비스나 CloudWatch 사용자 지정 지표는 추가하지 않는다. 이 도구가 AWS에서 EC2를 시작하지는 않는다. EC2 시작/중지는 기존 EventBridge Scheduler가 담당한다.

## 문법 확인

```bash
ansible-playbook mysql-recovery.yml --syntax-check
```

실제 서버의 복구와 게임 Router 조회는 별도로 확인해야 한다.

## 2026-10-15 설치 검증 (한국 시간)

- 설치 전: MySQL 3대 모두 OFFLINE/읽기 전용, 게임 서버의 Router 6446 연결 실패.
- 00:42: 공식 AdminAPI dry-run 이후 systemd 서비스 실행으로 전체 중단 복구 성공.
- 복구 결과: mysql-1 PRIMARY, mysql-2/3 SECONDARY, 모두 ONLINE.
- 게임 서버: `127.0.0.1:6446`에서 `dev` 계정으로 실제 SELECT 성공, 연결된 Primary의 `super_read_only=0` 확인. 업무 테이블에 시험 데이터를 쓰지는 않았다.
- 00:44: 타이머가 다시 실행되어 `HEALTHY: 3 ONLINE, 1 PRIMARY; no changes` 확인.
- 자동화 모의 테스트 15개 통과, Ansible 문법과 실제 systemd 유닛 검사 통과.
- 최초 설치 검증에서는 서비스 실행과 정기 실행을 확인했고, 이후 아래 EC2 중지·시작 검증도 수행했다.
- 검증 완료 후 사용자가 승인한 배스천·MySQL 3대·게임 서버 총 5대를 모두 `stopped`로 되돌린 것을 AWS API로 확인했다. 타이머의 부팅 시 자동 시작 설정은 유지했다.

## 2026-10-15 EC2 중지·시작 후 자동 복구 검증 (한국 시간)

- 이미 중지된 배스천·MySQL 3대·게임 서버 총 5대를 다시 시작했다. 복구 서비스의 수동 시작 명령은 실행하지 않았다.
- mysql-1 부팅 시각: 00:51:36. 타이머가 부팅과 함께 enabled 상태로 시작됐고 첫 실행 예정 시각은 00:53:36이었다.
- 자동 실행 전: MySQL 3대 OFFLINE/읽기 전용, 게임 Router 6446 접속 실패를 직접 확인했다.
- 00:53:49: 현재 부팅 journal에 `RECOVERED: 3 ONLINE, 1 PRIMARY; seed=10.30.10.111` 기록. 서비스 종료 코드 0, Result=success.
- 자동 복구 후: mysql-1 PRIMARY, mysql-2/3 SECONDARY, 모두 ONLINE. 게임 서버에서 Router 6446을 통한 SELECT 성공 및 Primary의 super_read_only=0 확인.
- 복구 방식은 증분 복구였으며, 시험을 위한 업무 데이터 INSERT/UPDATE/DELETE는 실행하지 않았다.
- 실험 후 5대 모두 stopped 상태로 돌아간 것을 AWS API로 확인했다. 종료 중 검사 방지를 위해 타이머를 런타임에서만 중지했고 enabled 설정은 유지했다.
