# 전체 EC2 중지·시작

`infra/scripts/power-all.ps1`은 선택한 배포 구성의 Bastion·서비스 EC2를 계정별로 병렬 중지·시작한다. 기본 구성은 `infra/config/profiles/current`이며, 2026-10-18 현재 이 구성에는 테스트 Backend를 포함한 5개 계정의 EC2 19대가 있다. 실행 위치와 관계없이 스크립트 위치에서 기본 구성을 찾는다.

```powershell
# C:\third-project\aws에서 전체 EC2 중지
.\aws-infra\infra\scripts\power-all.ps1 -Action Stop

# 같은 환경의 전체 EC2 시작
.\aws-infra\infra\scripts\power-all.ps1 -Action Start

# 전원 변경 없이 대상·현재 상태·권한 확인
.\aws-infra\infra\scripts\power-all.ps1 -Action Stop -WhatIf
```

다른 구성은 `-ProfileDirectory <구성 폴더>`로 지정한다. 전원 전환 대기는 계정마다 기본 600초이며 `-TimeoutSeconds 1200`처럼 변경할 수 있다. 대기 중인 EC2 조회 한 번은 CLI 연결·읽기 제한 시간만큼 추가로 걸릴 수 있다.

## 대상과 동작

- 해당 구성 경로의 로컬 Terraform `outputs.json`에 기록된 EC2 ID만 사용한다. AWS 계정 전체를 검색해 선택하지 않는다.
- 실제 변경 전에 다섯 계정의 STS 계정 ID, EC2 소유자, 프로젝트·계정·노드·역할·관리 태그, EBS 루트와 전원 권한을 확인한다. 한 계정이라도 이 사전 검사를 통과하지 못하면 전체 전원 변경을 시작하지 않는다.
- `-WhatIf`도 AWS 조회와 `--dry-run` 권한 검사는 수행한다. 실제 중지·시작 요청은 보내지 않는다.
- 이미 원하는 상태인 서버는 건너뛴다. `pending`·`stopping`은 전환이 끝나기를 기다린다. 중지는 AWS 기본 OS 종료 절차를 사용한다.
- 모든 계정에 요청한 뒤 실제 `stopped` 또는 `running` 상태까지 기다리고 IP를 표시한다. 실패한 계정은 오류로 보고한다. 변경 도중 실패하면 일부 계정은 이미 변경됐을 수 있으며, 원인을 해결한 뒤 같은 명령을 재실행할 수 있다.

설치·포맷·Terraform Apply·리소스 삭제·클러스터 복구·강제 중지는 수행하지 않는다. 시작 완료는 EC2가 `running`임을 뜻하며 SSH, EC2 상태 검사와 애플리케이션 정상 동작까지 보증하지 않는다.

로컬 출력이 없거나 구성과 다르면 해당 구성으로 기존 `infra.ps1 -ConfigurationDirectory <구성 폴더> -Account <계정> -Stage workload -Action Output`을 실행해 출력을 갱신한다. Bastion 출력은 해당 계정에 `-Stage bastion`으로 갱신한다. 전원 스크립트는 출력을 얻으려고 배포를 실행하지 않는다.

## 다음 시작 후 접속

Bastion EIP 적용 후 중지·시작에는 같은 공인 IP를 유지한다. 아직 EIP를 적용하지 않았거나 처음 전환·삭제 후 재생성했다면 주소를 확인하고, Ansible 실행 전 같은 구성의 인벤토리를 갱신한다.

```powershell
# 새 공인 IP를 인벤토리에 반영한다. EC2 전원 스크립트와 별도로 실행한다.
.\aws-infra\infra\scripts\deploy.ps1 -ProfileDirectory .\aws-infra\infra\config\profiles\current -Action Inventory
```

MySQL을 포함한 DB·Kafka·Spark 클러스터 상태는 별도로 확인한다. MySQL Group Replication 전체 중단 뒤에는 복구 절차가 필요할 수 있다. [MySQL 전체 중단 복구](https://dev.mysql.com/doc/mysql-shell/8.4/en/reboot-outage.html)

중지해도 EBS 데이터는 유지되고 저장 비용은 계속 발생한다. EIP 등 유지한 다른 리소스도 별도 과금될 수 있다. [AWS 중지·시작 동작](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/how-ec2-instance-stop-start-works.html)

## 검증

2026-10-14 검증: Windows PowerShell 5.1과 PowerShell 7에서 각각 13개 모의 시나리오가 통과했다. 실제 `current` 구성에 `-Action Stop -WhatIf`를 실행해 5개 계정의 18대, 소유자·태그와 중지 권한도 확인했다. 확인 당시 18대 모두 `running`이었으며, 실제 중지·시작과 클러스터 재기동 시험은 수행하지 않았다.

## 현재 자동 예약 — 2026-10-18 조회

5개 계정의 aws-infra-office-hours 그룹은 ec2-start-0900(이름 유지)을 평일 08:30, ec2-stop-2200을 매일 22:00 Asia/Seoul에 실행한다. 모두 ENABLED다. 대상은 기존 18대이며 game-server-test는 두 예약 모두 제외된다. power-all.ps1의 current 19대와 예약 대상을 혼동하지 않는다.

수동 Stop은 자동 예약을 비활성화하지 않는다. 이번 문서 정리는 예약·서버 상태를 바꾸지 않았다. [서버별 현재 상태와 주소](current-state.md)를 참고한다. 아래 명령 실행 성공은 DB 복제·앱 정상 상태까지 보장하지 않는다.
