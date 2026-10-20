# infra/scripts/bastion.ps1

환경 변수 저장·복원은 infra-common.ps1의 Save-InfraEnvironment / Restore-InfraEnvironment를 사용한다. Invoke-BastionAws의 출력 수집은 Invoke-InfraCapturedCommand가 담당하며, 기존 제한 시간·DryRun 판정·오류 메시지는 이 실행기에 유지한다.

[탐색 시작점](../ROUTING-README.md) · [원본 스크립트](../../../infra/scripts/bastion.ps1) · [실행 안내](../../operations-recovery.md#4-배스천-상태-조회와-중지시작) · [전용 Terraform 단계](../terraform/stacks/bastion.md)

## 역할과 입력

개발자 PC에서 Bastion 전용 Terraform 계획의 생성·적용과 AWS CLI의 상태 조회·전원 제어를 제공한다. PlanCreate/Create/PlanDelete/Delete는 infra.ps1의 bastion 단계로 위임하고, 그 외 동작은 AWS CLI로 기존 한 대를 조회·제어한다. 설정은 스크립트 위치의 상위 `infra`를 기준으로 읽고, [공통 함수 파일](../../../infra/scripts/lib/infra-common.ps1)의 `Read-InfraJson`을 재사용한다.

| 매개변수 | 허용 값·기본값 |
| --- | --- |
| Action | Status / Output / Stop / Start / Restart / PlanCreate / Create / PlanDelete / Delete. 필수 |
| TimeoutSeconds | 1~3600초, 기본 600초. Start 또는 Stop 한 단계의 상태 대기 상한 |

topology 설정의 nodes → bastion → account 값이 대상 계정을 결정한다. 해당 계정의 ID·CLI 프로필, 프로젝트 이름, 서울 리전을 topology에서 읽고 SSH 포트는 traffic에서 읽는다. Account·Profile·InstanceId를 별도로 지정하는 옵션은 없다. Status·Output·전원 동작은 AMI·backend를 사용하지 않는다. 생성·삭제는 공통 실행기의 backend 검사와 저장 계획 보호를 사용하며, 생성 Plan·Apply에는 AMI와 공개키가 필요하다. 인증서는 HTTP 구성에서 사용하지 않는다.

## 대상 확인과 실행 흐름

1. JSON을 읽고 대상 설정을 검사한다. 생성·삭제 동작은 infra.ps1에 위임한다. PlanCreate/PlanDelete는 계획 저장 후 반환하고 Create/Delete는 적용 후 현재 EC2 조회를 이어간다.
2. 조회·전원 경로에서는 AWS CLI 실행 파일을 확인한다.
3. AWS 자격 증명·리전·엔드포인트 등 지정된 프로세스 환경변수를 보관하고 격리한다. 모든 CLI 요청에 설정의 프로필·리전을 명시한다.
4. STS의 실제 계정 ID와 설정을 비교한다. 불일치하면 EC2를 조회하거나 변경하지 않는다.
5. Project·Account·Layout=v2·ManagedBy=Terraform·Node=bastion·Role=bastion 태그로 pending/running/stopping/stopped 인스턴스를 조회한다. 여러 대이면 거부한다. 0대일 때 Status·Output·Delete는 State=Absent를 반환하고 Start·Stop·Restart·Create 후 조회는 오류로 처리한다.
6. 대상 ID를 고정하고 선택한 Action을 실행한다. Stop·Start·Restart에는 EBS 루트 볼륨이 필요하다.
7. 시스템·인스턴스 검사 결과와 IP를 출력한다. running이면 공인 IP의 SSH TCP 포트를 최대 3초간 확인한다.
8. finally에서 원래 AWS 프로세스 환경변수를 복원한다. 조회·전원 경로는 로컬 설정·상태·로그를 쓰지 않는다. 생성·삭제 경로는 공통 실행기의 .local 계획·manifest와 Bastion 전용 S3 상태를 사용한다.

| Action | 동작 |
| --- | --- |
| PlanCreate → 검토 → Create | bastion 단계의 Create 계획 저장 → 해당 저장 계획 적용 |
| PlanDelete → 검토 → Delete | bastion 단계의 Delete 계획 저장 → Bastion EC2·OS 디스크·전용 키페어 삭제 |
| Status / Output | 현재 상태·IP·EC2 검사 결과 조회. running일 때 SSH TCP 확인. 없는 경우 Absent |
| Start | pending/stopping이 끝나길 기다림 → 필요하면 시작 요청 → running 및 SystemStatus/InstanceStatus 모두 ok 대기 |
| Stop | pending/stopping이 끝나길 기다림 → 필요하면 기본 중지 요청 → stopped 대기 |
| Restart | 시작·중지 권한을 각각 dry-run으로 검사 → 같은 ID에 Stop → Start. 중지 실패 시 시작 단계로 진행하지 않음 |

Start/Stop 재실행 시 목표 전원 상태이면 변경 요청을 생략한다. Start는 이미 running이어도 EC2 검사 완료를 기다린다. 고정 ID의 전원 전환 대기에서 삭제 중·삭제 완료 등 예상하지 않은 상태는 오류다. 재시작에는 Stop과 Start에 각각 TimeoutSeconds를 적용한다. 상태 조회 API 호출 시간 때문에 실제 경과 시간은 대기 상한보다 길어질 수 있다. CLI 연결 제한은 5초, 읽기 제한은 20초, 최대 시도 횟수는 2회다.

## 함수 지도

PowerShell 선언과 역할을 직접 대조하는 표다. routing-doc-sync의 Python AST 분석 대상은 아니다.

| 함수 | param 선언 | 역할 |
| --- | --- | --- |
| Invoke-BastionAws | ([string[]]$Arguments, [switch]$DryRun) | 공통 CLI 옵션·종료 코드·JSON 처리. DryRunOperation을 권한 검사 성공으로 판정 |
| Get-BastionInstance | ([string]$InstanceId, [switch]$AllowMissing) | 최초 태그 검색 또는 고정 ID 조회. 중복·ID 검사, AllowMissing이면 0대는 null |
| Get-BastionHealth | 없음 | 고정 ID의 시스템·인스턴스 검사 결과. 미보고 시 not-reported |
| Wait-BastionState | ([string]$Condition, [DateTime]$Deadline) | Stable / Stopped / Ready 조건까지 최대 5초 간격으로 조회 |
| Set-BastionPower | ([string]$Operation) | Start / Stop 한 단계 실행. 진행 중인 전환 대기와 목표 상태 검사 |
| Test-BastionSshPort | ([string]$Address, [int]$Port) | 최대 3초간 TCP 연결 확인. 연결 종료 및 핸들 정리 |

## 결과와 실패 처리

PowerShell 객체로 Action, Account, Region, InstanceId, State, SystemStatus, InstanceStatus, PublicIp, PrivateIp, SshPort, SshTcp, SshCommand, ProxyEndpoint를 반환한다. Absent는 InstanceId·IP·접속 문자열이 null이며 EC2 검사·TCP 결과 필드는 없다. 진행 상태는 Write-Host, 접속·프록시 영향은 Write-Warning으로 표시한다.

SshTcp는 PortOpen / Unreachable / NoPublicIp / NotChecked다. PortOpen은 TCP 접속만 확인한 결과이며 SSH 키 인증·내부 서버 경유·Forward Proxy 동작 성공을 뜻하지 않는다. SSH TCP 확인 실패는 경고로 보고하고 켜진 EC2를 유지한다.

AWS 오류·대상 불일치·상태 대기 시간 초과는 terminating error로 전달한다. 오류 발생 시 자동 강제 종료·반대 동작·롤백을 하지 않는다. 명령이 실패한 뒤 실제 상태는 Status로 다시 확인한다. 종료 전에 결과 조회가 실패하면 전원 변경이 완료됐어도 명령 전체는 오류가 될 수 있다.

조회·전원에 필요한 권한은 STS GetCallerIdentity, EC2 DescribeInstances·DescribeInstanceStatus와 요청할 동작의 StartInstances·StopInstances다. 생성·삭제에는 추가로 Terraform EC2·키페어·S3 상태·잠금 관련 권한이 필요하다. Restart는 두 변경 권한이 모두 필요하다. 기존 Terraform 작업이나 다른 PC의 배스천 전원 작업과 동시에 실행하지 않는다. 여러 PC 사이의 실행 잠금은 구현하지 않는다.

## 범위와 검증 한계

Status·Output·전원 동작은 보안그룹·CIDR·EIP·디스크·예약 일정·서비스 설정을 변경하지 않는다. Create/Delete의 자원 범위는 전용 EC2·OS 디스크·키페어이며, EIP는 만들지 않는다. foundation의 SG와 workload의 규칙·서비스 서버·ALB·데이터 디스크는 전용 상태 밖에 있다. 배스천이 Forward Proxy로 사용 중이면 중지하는 동안 해당 외부 연결도 끊긴다. EC2의 정상 검사 결과만으로 SSH나 Proxy 자동 기동을 보증하지 않는다.

PowerShell 5.1과 7.6에서 실제 AWS CLI를 가짜 응답 함수로 대체한 24개 사례씩을 검증했다. 반복 실행·상태 전환·잘못된 계정·누락/중복 대상·권한 오류·시간 초과·EC2 검사 대기를 포함한다. 공인 IP 없음·열린 포트·닫힌 포트의 TCP 처리 3개 사례는 로컬 루프백으로 확인했다. 검증용 추가 파일은 저장하지 않았다.

위 모의 실행·루프백 결과는 기존 문서의 기록이다. 이번 문서 대조에서는 다시 실행하지 않았고, 검증용 추가 파일이 보관돼 있지 않아 그 기록을 독립적으로 재확인한 결과로 취급하지 않는다. 현재 함수·매개변수·태그 선택·상태 처리 구조는 원본 PowerShell과 직접 대조했다.

현재 admin_public_cidrs에는 관리자 CIDR 한 항목이 있고, workload에는 Bastion SG의 콘솔 접속용 EC2 Instance Connect 접두사 목록 TCP 22 규칙도 있다. 이 스크립트는 SSH 규칙을 직접 추가하지 않는다. workload는 Bastion EC2를 제외한다. Stop은 같은 EC2를 중지하고 OS 디스크를 유지한다. EC2·OS 디스크·전용 키페어·EIP를 제거하려면 PlanDelete 검토 후 Delete를 사용한다. EIP 적용 후에는 중지·시작 동안 주소를 유지한다. 최초 EIP 전환 및 Delete 후 재생성 시에는 현재 주소를 확인한다. Proxy 설치와 팀원 공개키 추가는 새 서버에 다시 준비해야 한다.

스크립트 실행법은 위 실행 안내에서 관리한다. 실제 AWS 기동·중지, IAM 권한, SSH 연결 및 Proxy 복구는 별도 운영 검증 대상이다.
