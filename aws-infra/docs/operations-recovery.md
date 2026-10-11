# 복원·운영 절차

[배포 절차로 돌아가기](deployment-runbook.md) · [배포 명령 설명](../infra/scripts/scripts.md) · [코드 탐색](infra-routing/ROUTING-README.md)

배포 중 발생한 오류의 확인·복구와 이미 만든 환경의 운영 명령을 모은 문서다. scripts.md에 있던 절차를 이곳으로 옮겼다. 아래 명령을 위에서부터 전부 실행하지 않고 해당 증상·작업의 절만 선택한다. 이 문서의 복원은 설정·접속·배포 흐름 복구를 뜻하며 삭제된 DB 데이터나 EBS를 되살리는 절차는 포함하지 않는다.

| 증상 또는 작업 | 볼 절차 |
| --- | --- |
| S3 상태 버킷 값 누락·잘못된 버킷 이름 | [1. S3 설정 복원](#1-s3-상태-버킷-설정-복원) |
| AMI 값 누락·조회 실패 | [2. Ubuntu AMI 설정](#2-account-1-ubuntu-ami-조회와-설정) |
| 네트워크를 옮긴 뒤 게임 HTTP 접속이 막힘 | [3. 공인 IP·게임 접속 범위](#3-테스트용-공인-ip-조회와-게임-접속-허용-설정) |
| 배스천 중지·시작·상태 확인 | [4. 배스천 운영](#4-배스천-상태-조회와-중지시작) |
| 배스천 재시작·재생성 후 주소가 바뀜 | [4.1 주소 갱신](#41-배스천-주소가-바뀐-뒤-다시-연결) |
| 기존 서버를 보관한 PEM과 다시 맞추는 계획된 키 전환 | [5. SSH 키 전환](#5-계정별-새-ssh-키-준비와-기존-서버-등록) |
| 전체 인프라 정리·삭제 실패·보호 설정 복원 | [6. 전체 삭제](#6-전체-인프라-삭제) |
| SSH·프록시·Vault·서비스 설치 또는 Terraform 실패 | [7. 배포 장애 확인](#7-배포-장애-확인과-재개) |

## 공통 작업 위치와 선택한 구성

Windows PowerShell의 새 창에서는 다음을 설정한다. current 대신 배포할 때 사용한 구성 이름을 선택한다.

```powershell
Set-Location 'C:\third_project\aws-infra'
$deployScript = 'C:\third_project\aws-infra\infra\scripts\deploy.ps1'
$deploymentProfile = 'C:\third_project\aws-infra\infra\config\profiles\current'
```

S3 backend는 공통 infra/config/backend.json을 사용한다. 2·3절은 NewProfile 전 기본 config를 준비하던 기존 명령이다. 이미 구성 프로필을 만들었다면 코드 블록의 topologyPath·trafficPath 할당을 각각 다음 줄로 바꿔 실행한다. 기본 config만 수정해도 기존 프로필에 자동 복사되지 않는다.

```powershell
# AMI·노드 설정은 선택한 구성의 파일을 변경한다.
$topologyPath = Join-Path $deploymentProfile 'topology.tfvars.json'
# 접속 허용 범위도 같은 구성에서 변경한다.
$trafficPath = Join-Path $deploymentProfile 'traffic.tfvars.json'
```

설정·키·코드를 변경한 뒤에는 새 Plan을 검토해야 한다. 오류가 났다고 Terraform 상태 파일·S3 버킷부터 지우거나 전체 인프라 삭제를 실행하지 않는다. 삭제는 6절의 별도 운영 작업이다.


## 1. S3 상태 버킷 설정 복원

기존 배포의 버킷 이름이 로컬 설정에서 빠졌거나 잘못됐을 때 사용한다. 아래 이름은 이전 환경의 값이며 실제 유지된 버킷인지 확인한다. AccessDenied·만료된 인증은 이름 변경으로 해결되지 않으므로 사용한 CLI 프로필과 해당 버킷 권한부터 확인한다. 이 명령은 버킷·삭제된 상태 객체를 재생성하지 않는다.

```powershell
Set-Location C:\third_project\aws-infra

# 기존 설정을 읽고 이전 배포의 S3 상태 버킷 이름을 채웁니다.
$backendPath = 'C:\third_project\aws-infra\infra\config\backend.json'
$backendConfig = Get-Content -Raw -LiteralPath $backendPath | ConvertFrom-Json
$backendConfig.bucket = 'aws-infra-tfstate-541308265856'

# JSON을 UTF-8(BOM 없음) 형식으로 저장합니다.
$backendJson = $backendConfig | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($backendPath, $backendJson, [System.Text.UTF8Encoding]::new($false))

# 저장된 값을 확인합니다.
Get-Content -LiteralPath $backendPath
```

수정 후 [배포 입력 확인](deployment-runbook.md#31-windows-도구와-aws-인증)으로 돌아가고, 실패한 Terraform 단계의 새 Plan부터 진행한다.

## 2. Account 1 Ubuntu AMI 조회와 설정

```powershell
Set-Location C:\third_project\aws-infra

# 서울 리전의 Ubuntu Server 24.04 x86_64 공식 AMI를 조회합니다.
$ubuntuAmiId = aws ssm get-parameter --profile account1 --region ap-northeast-2 --name "/aws/service/canonical/ubuntu/server/noble/stable/current/amd64/hvm/ebs-gp3/ami-id" --query "Parameter.Value" --output text

# 조회에 실패하면 잘못된 값을 저장하지 않고 중단합니다.
if ($LASTEXITCODE -ne 0 -or $ubuntuAmiId -notmatch '^ami-[0-9a-f]+$') {
    throw 'AMI 조회에 실패했습니다. 위 AWS 오류를 확인하세요.'
}

# 기존 설정을 유지하면서 Account 1의 AMI 값만 채웁니다.
$topologyPath = 'C:\third_project\aws-infra\infra\config\topology.tfvars.json'
$topologyConfig = Get-Content -Raw -LiteralPath $topologyPath | ConvertFrom-Json
$topologyConfig.topology.accounts.account1.ami_id = $ubuntuAmiId.Trim()
$topologyJson = $topologyConfig | ConvertTo-Json -Depth 50
[System.IO.File]::WriteAllText($topologyPath, $topologyJson, [System.Text.UTF8Encoding]::new($false))

# 저장된 AMI ID를 확인합니다.
$topologyConfig.topology.accounts.account1.ami_id
```

조회가 실패하면 값을 저장하지 않고 프로필·리전·SSM 조회 권한을 확인한다. 다른 계정의 AMI 설정도 필요하면 해당 계정에서 조회·설정한다. 기존 EC2의 AMI 변경은 교체 계획을 만들 수 있으므로 [단계별 Plan 검토](deployment-runbook.md#5-terraform으로-네트워크와-ec2-생성) 후 적용 여부를 판단한다.

## 3. 테스트용 공인 IP 조회와 게임 접속 허용 설정

현재 PC가 연결된 네트워크의 공인 IPv4를 조회하고, 그 IP 하나를 허용하는 `/32` 형식으로 저장한다. `game_client_cidrs` 목록은 현재 IP 하나로 교체하며 다른 설정은 유지한다. 학교·사무실에서 조회하면 해당 네트워크의 공인 IP가 나오고, 집에서 조회하면 집 네트워크의 공인 IP가 나온다.

```powershell
Set-Location C:\third_project\aws-infra

# 현재 네트워크의 공인 IP를 조회하고 접속 허용 범위를 표시합니다.
$testPublicIp = (Invoke-RestMethod -Uri 'https://checkip.amazonaws.com').Trim()
"$testPublicIp/32"

# 기존 설정을 읽고 게임 접속 허용 IP만 변경합니다.
$trafficPath = 'C:\third_project\aws-infra\infra\config\traffic.tfvars.json'
$trafficConfig = Get-Content -Raw -LiteralPath $trafficPath | ConvertFrom-Json
$trafficConfig.traffic.game_client_cidrs = @("$testPublicIp/32")

# 기존 설정 전체를 UTF-8(BOM 없음) JSON으로 저장합니다.
$trafficJson = $trafficConfig | ConvertTo-Json -Depth 50
[System.IO.File]::WriteAllText(
    $trafficPath,
    $trafficJson,
    [System.Text.UTF8Encoding]::new($false)
)

# 파일에 실제로 저장된 접속 허용 IP를 확인합니다.
$savedTrafficConfig = Get-Content -Raw -LiteralPath $trafficPath | ConvertFrom-Json
$savedTrafficConfig.traffic.game_client_cidrs
```

이번 PC의 조회 결과는 `211.117.107.63/32`였다. 다른 네트워크에서는 조회값이 달라질 수 있다.

위 명령은 로컬 설정 파일을 저장한다. 실제 AWS 반영은 Account 1 workload의 새 Plan을 검토한 뒤 Apply할 때 이루어진다. 나중에 학교의 공인 IP 대역을 확보하면 `game_client_cidrs`의 테스트 IP를 해당 대역으로 교체하고 같은 절차로 적용한다. 설정을 바꾼 뒤에는 이전 저장 Plan을 사용할 수 없다.

현재 ALB는 HTTP 80 listener만 사용한다. certificate_arn은 공통 타입에 남아 있지만 인증서가 없다는 이유로 workload Plan·Apply를 중단하지 않는다. /static/*는 Front:80, /ads/*는 광고:8000, 기본 경로는 game:8000으로 보낸다. HTTPS/WSS 공개는 현재 구현과 별도로 설계해야 한다.

이 절은 게임 접속용 game_client_cidrs만 바꾼다. 배스천 SSH 허용 범위인 admin_public_cidrs는 별도이며 [SSH 연결 장애](#72-ssh-인증-또는-접속-시간-초과)에서 구분한다. 변경한 구성으로 [workload Plan·Apply](deployment-runbook.md#53-서비스-ec2ebs통신-규칙alb-workload)를 진행한다.

## 4. 배스천 상태 조회와 중지·시작

[../infra/scripts/bastion.ps1](../infra/scripts/bastion.ps1)은 기존 배스천 한 대를 대상으로 AWS CLI를 실행한다. PowerShell 5.1 이상과 AWS CLI v2, 대상 계정의 유효한 CLI 프로필이 필요하다. Terraform·S3 상태·AMI·ALB 인증서는 실행 조건이 아니다. 실제 배스천은 현재 v2 Terraform 구성으로 이미 생성되어 있어야 한다.

```powershell
Set-Location C:\third_project\aws-infra

# 현재 전원 상태·IP·EC2 검사 결과를 확인합니다.
.\infra\scripts\bastion.ps1 -Action Status

# 중지를 요청하고 stopped 상태까지 기다립니다.
.\infra\scripts\bastion.ps1 -Action Stop

# 시작을 요청하고 running 및 EC2 시스템·인스턴스 검사 정상까지 기다립니다.
.\infra\scripts\bastion.ps1 -Action Start

# 시작·중지 권한을 먼저 검사하고, 중지 완료 후 같은 서버를 다시 시작합니다.
.\infra\scripts\bastion.ps1 -Action Restart
```

위 네 명령은 개별 사용 예시다. Status는 조회하고, Stop·Start·Restart는 별도 확인 질문 없이 실제 전원을 제어한다. 처음 실행할 때는 Status로 대상을 확인한다.

계정·프로필·리전은 [topology 설정](../infra/config/topology.tfvars.json)의 bastion 노드에서 찾는다. 실제 AWS 계정 ID를 검사하고 Project·Account·Layout=v2·ManagedBy=Terraform·Node=bastion·Role=bastion 태그에 맞는 활성 대상이 정확히 한 대일 때만 진행한다. 여기서 활성 대상은 pending/running/stopping/stopped를 포함한다. 대상이 없거나 중복되면 중단하며 인스턴스 ID를 추측하지 않는다. 작업 중에는 처음 선택한 ID를 유지한다.

| Action | 완료 기준 |
| --- | --- |
| Status | 현재 전원 상태·IP·EC2 상태 검사 결과 출력 |
| Stop | stopped. 이미 stopped면 중지 요청 생략 |
| Start | running이고 SystemStatus·InstanceStatus 모두 ok. 이미 running이어도 검사 완료 대기 |
| Restart | Stop 완료 후 Start 완료. 시작·중지 권한 검사 또는 Stop이 실패하면 다음 단계로 진행하지 않음 |

pending/stopping 상태는 전환 완료를 기다린 뒤 요청한 목표 상태로 진행한다. Start 또는 Stop 한 단계의 대기 상한은 기본 600초이며 `-TimeoutSeconds 900`처럼 1~3600초로 바꿀 수 있다. Restart는 Stop·Start에 각각 적용한다. 마지막 AWS 조회에 소요되는 시간이 추가될 수 있다. 실패하면 마지막 상태·실패 원인을 출력하고 종료하며 강제 종료나 자동 롤백을 하지 않는다. 실패 후 현재 상태는 Status로 확인한다.

반환 객체에는 Action, Account, Region, InstanceId, State, SystemStatus, InstanceStatus, PublicIp, PrivateIp, SshPort, SshTcp가 있다. running이면 [traffic 설정](../infra/config/traffic.tfvars.json)의 SSH 포트에 최대 3초 동안 TCP 접속을 시도한다.

| SshTcp | 의미 |
| --- | --- |
| PortOpen | TCP 포트 도달 성공. SSH 키 인증 성공을 의미하지 않음 |
| Unreachable | 제한 시간 안에 TCP 연결 실패. 관리자 CIDR·네트워크·SSH 서비스 확인 필요 |
| NoPublicIp | 조회 결과에 공인 IP가 없음 |
| NotChecked | running 상태가 아니어서 검사 생략 |

SSH 도달 실패는 전원 제어 결과와 별도로 경고하고 EC2를 유지한다. SG 규칙이나 관리자 IP는 자동 수정하지 않는다. 내부 서버 경유 접속, SSH 키 인증, Forward Proxy 복구는 별도 확인 대상이다.

배스천 중지는 SSH 세션·터널과 해당 서버를 사용하는 Forward Proxy 연결을 끊는다. 서비스가 프록시로 외부 API를 호출하는 시간에는 이 영향을 고려해 실행한다. 다른 PC의 전원 작업이나 Terraform 변경과 동시에 실행하지 않는다. 인스턴스 삭제·디스크 삭제·Elastic IP 해제·자동 예약은 수행하지 않는다.

필요한 EC2 권한은 DescribeInstances·DescribeInstanceStatus와 사용할 동작의 StartInstances·StopInstances다. Restart에는 두 변경 권한이 모두 필요하다. 함수와 예외 처리의 위치는 [배스천 라우팅 문서](infra-routing/scripts/bastion.ps1.md)에 정리했다.

### 4.1 배스천 주소가 바뀐 뒤 다시 연결

중지·시작 또는 재생성 뒤 공인·사설 주소가 바뀌었다면 Windows PowerShell에서 선택한 구성의 인벤토리를 갱신한다.

```powershell
# 현재 EC2 주소를 읽어 선택한 구성의 인벤토리를 다시 만든다.
& $deployScript -Action Inventory -ProfileDirectory $deploymentProfile
```

이후 WSL에서 [가상환경·인벤토리 확인](deployment-runbook.md#73-wsl-실행-환경과-인벤토리-확인), 필요한 [Vault 비밀번호 설정](deployment-runbook.md#91-vault-비밀번호와-db-secret), [프록시 준비](deployment-runbook.md#8-전체-프록시와-apt-준비) 순으로 진행한다. 내부 IP를 사용하는 [방화벽](deployment-runbook.md#10-공통-os-설정과-방화벽)과 서비스 설정도 주소 변경 영향을 확인한다. DB·클러스터 노드의 재생성은 단순 IP 갱신만으로 데이터·멤버 상태가 복원되지 않는다.


## 5. 계정별 새 SSH 키 준비와 기존 서버 등록

이 절은 계획된 키 전환 작업이다. Permission denied만 보고 배스천을 먼저 삭제하지 말고 [키 경로·사용자·인증 확인](#72-ssh-인증-또는-접속-시간-초과)을 수행한다. 아래 재생성은 배스천 OS와 수동 설치를 제거하므로 새 배스천을 만든 뒤 프록시를 다시 준비해야 한다.

개인키는 `C:\Users\Playdata\.ssh\project-key`에 보관한다. Account 1은 `project-bastion.pem`, 나머지는 **account2.pem**~**account5.pem**이다. 기존 서버는 새 개인키를 PC에 저장하는 것만으로 접속 키가 바뀌지 않는다.

```powershell
Set-Location C:\third_project\aws-infra

# 로컬 개인키 권한·공개키·계정별 경로를 준비한다. AWS 변경은 하지 않는다.
.\infra\scripts\account-keys.ps1 -Action Prepare

# Bastion 전용 상태의 삭제 계획만 검토한 뒤 Delete를 실행한다.
.\infra\scripts\bastion.ps1 -Action PlanDelete
.\infra\scripts\bastion.ps1 -Action Delete

# 새 Account 1 키로 Bastion을 재생성한다. PlanCreate를 검토한 뒤 Create를 실행한다.
.\infra\scripts\bastion.ps1 -Action PlanCreate
.\infra\scripts\bastion.ps1 -Action Create
.\infra\scripts\bastion.ps1 -Action Output

# 새 Bastion을 통해 현재 topology의 서비스 서버에 계정별 공개키를 등록한다.
.\infra\scripts\account-keys.ps1 -Action Register
```

`Prepare`는 기존 공개키를 `infra/.local/ssh-keys/previous-public/`에 보관하고, `infra/config/keys/account1.pub`~**account5.pub** 및 `topology.accounts.<계정>.ssh_public_key_path`를 갱신한다. 개인키는 저장소 안으로 복사하지 않는다. 설정 변경 전의 저장 Plan은 다시 만들어야 한다.

`Register`는 실제 계정·서버 태그·역할·개수·기동 상태를 확인한다. Bastion에 다섯 공개키를 추가하고, EC2 Instance Connect로 기존 서비스 서버에 임시 접속하여 `ubuntu`의 `authorized_keys`에 계정별 공개키를 추가한다. 기존 공개키는 보존한다. EC2·디스크·ALB의 생성이나 삭제, Terraform Apply는 수행하지 않는다. 필요한 권한은 STS GetCallerIdentity, EC2 DescribeInstances, EC2 Instance Connect SendSSHPublicKey이며 Ubuntu의 EIC 설치 및 SSH 경로가 필요하다.

등록 중 실패하면 원인을 해결하고 같은 명령을 다시 실행한다. 특정 계정만 재시도할 때는 `-Account account2`처럼 지정한다. Bastion을 다음에 재생성한 뒤에는 `Register -Account account1`을 실행하여 추가 팀원 공개키를 다시 등록한다.

접속 설정은 `infra/.local/ssh-keys/ssh-config`에 생성된다. 예를 들어 등록 후 Account 2의 Mongo 서버에 접속하는 명령은 다음과 같다.

```powershell
ssh -F .\infra\.local\ssh-keys\ssh-config infra-key-account2-mongo-1
```

EC2 Instance Connect 임시 키가 만료된 뒤에도 접속되는지 별도로 확인한다. 팀원에게는 자기 계정의 PEM과 필요한 접속 설정을 전달하고, 팀원 PC의 `IdentityFile` 경로와 관리자 공인 IP 허용 규칙을 맞춘다.

새 공개키를 서버에 등록한 뒤, AWS 키페어 등록 정보도 맞추기 위해 각 계정 workload의 새 `Plan`을 검토한다. 키페어 교체가 예상되지만 서비스 EC2·디스크·ALB 교체가 포함되면 Apply하지 않는다. 검토한 계정만 기존 `infra.ps1 -Action Apply`로 적용한다. 자세한 함수·경계는 [키 전환 라우팅 문서](infra-routing/scripts/account-keys.ps1.md)를 참고한다.

Prepare가 갱신한 기본 topology의 키 경로와 선택한 프로필의 키 경로도 대조한다. 접속이 복구되면 [인벤토리 생성](deployment-runbook.md#6-현재-ec2-주소로-인벤토리-생성)과 [프록시 준비](deployment-runbook.md#8-전체-프록시와-apt-준비)로 돌아간다.

## 6. 전체 인프라 삭제

이 프로젝트의 Terraform 상태가 관리하는 Bastion·5개 계정 workload·Peering·foundation을 삭제한다. 데이터 EBS도 삭제 대상이다. S3 상태 버킷·상태 이력, 상태에 없는 수동 자원과 다른 프로젝트는 자동 삭제하지 않는다.

workload가 생성한 역할별 service_console_ssh 규칙도 전체 삭제 대상이다. 삭제 검사기는 정확한 자원 주소와 문자열 역할 키 형식을 허용하며 단계·태그·계정·삭제 전용 검사를 유지한다. 관련 함수를 수정한 뒤에는 이전 실패 실행 ID를 재사용하지 않고 새 Plan을 만든다. [삭제 검사 문서](infra-routing/scripts/lib/infra-destroy.ps1.md)를 참고한다.

현재 [compute의 데이터 EBS 보호](infra-routing/terraform/README.md#compute)는 prevent_destroy=true다. 아래 명령은 지정한 옵션으로 Plan 전에 잠시 해제하고 종료 시 원래 값으로 복원한다. `-DeleteDataVolumes`만으로는 이 보호가 해제되지 않으며, 별도 Plan·Apply에서도 자동 해제하지 않는다. 이전 구현 당시의 false 값은 [검증 이력](infra-routing/verification.md)에 당시 상태로 남긴다.

### 한 번의 명령으로 전체 삭제

```powershell
Set-Location C:\third_project\aws-infra

# 새 Plan 생성·검사·실제 삭제·결과 확인을 이어서 수행한다. 데이터 EBS도 삭제된다.
.\infra\scripts\destroy-all.ps1 -Action Destroy -DeleteDataVolumes -DisableDataVolumeProtection
```

추가 입력 대기 없이 실행한다. 새 실행 ID를 출력하고 모든 Plan이 Ready인 경우에만 Apply를 진행한다. 중간 실패는 뒤 단계를 중단하며 정상 종료·처리 가능한 오류에서는 보호 설정을 원래 바이트로 복원한다. 원래 false이면 그대로 유지한다. 이 옵션은 Destroy에서만 허용하며 RunId를 직접 지정하지 않는다.

완료 메시지와 Status의 Complete를 확인한다. Plan/Apply 실패는 Failed, 삭제 후 잔존 자원·조회 실패는 VerificationFailed, 보호 복원 실패는 ProtectionRestoreFailed로 기록된다. 실행 ID로 Status를 확인하고 원인을 해결한 뒤 새 Destroy를 실행한다. 복원 후 Verify도 보호 해제 전 코드·설정 기준을 사용한다.

실행 중 compute 파일에 외부 수정이 있거나 원본 사본이 변조되면 자동 복원을 중단한다. 프로세스 강제 종료·전원 중단으로 finally가 실행되지 않은 경우도 해당 실행 폴더의 run.json과 data-protection.original.tf를 확인하여 원본과 현재 파일을 대조하고 설정을 복구해야 한다. 자세한 동작은 [삭제 라우팅 문서](infra-routing/scripts/destroy-all.ps1.md#한-번에-실행과-보호-복원)에 있다.

### Plan을 별도로 검토한 뒤 삭제

기존 Plan·Apply는 보호 설정을 자동 변경하지 않는다. 보호가 true이면 데이터 볼륨을 포함한 Plan이 실패할 수 있으므로 필요한 경우 직접 해제한 뒤 새 Plan을 만든다. Plan 생성 후 설정을 변경하면 이전 계획을 적용할 수 없다.

아래 명령은 한 단계씩 실행한다. Plan은 자원을 삭제하지 않고, Apply가 실제 삭제를 수행한다.

```powershell
Set-Location C:\third_project\aws-infra

# 최대 12개 상태의 삭제 계획을 준비한다. 데이터 EBS 삭제 선택이 필수다.
.\infra\scripts\destroy-all.ps1 -Action Plan -DeleteDataVolumes
```

Plan에서 출력한 실행 ID를 아래 변수에 넣는다. `infra/.local/destroy-all/{실행ID}/`의 계정·단계별 `delete-summary.json`과 Plan 출력을 검토한다. `delete_count`에는 EC2 OS 디스크 검증 항목도 포함되므로 Terraform의 destroy 개수와 다를 수 있다. 전체 실행 상태가 Ready여야 Apply할 수 있다.

```powershell
# Plan 결과의 32자리 실행 ID로 바꾼다.
$destroyRunId = '여기에_Plan에서_출력된_실행_ID'

# 준비·진행 상태를 조회한다. 이 명령은 로컬 기록을 읽는다.
.\infra\scripts\destroy-all.ps1 -Action Status -RunId $destroyRunId

# 모든 삭제 대상과 데이터 삭제를 검토한 뒤에만 실행한다.
.\infra\scripts\destroy-all.ps1 -Action Apply -RunId $destroyRunId -DeleteDataVolumes
```

삭제 순서는 **Bastion → account1~5 workload → shared connectivity → account1~5 foundation**으로 고정된다. 첫 삭제 전에 모든 계획·코드·설정·공개키·원격 상태 변경을 검사한다. 계획 중 하나라도 실패했거나 바뀌면 적용을 거부한다. 진행 중 한 단계가 실패하면 이후 단계는 실행하지 않는다.

실패·Ctrl+C 후에는 Status에서 위치를 확인하고 원인을 해결한 뒤 **새 Plan → 검토 → 새 ID로 Apply**를 수행한다. 이미 비어 있는 상태와 미생성 Bastion은 건너뛴다. 상태 파일이나 S3 버킷을 먼저 삭제하지 않는다. 다른 터미널·팀원 PC의 배포·콘솔 변경은 전체 삭제 중 함께 실행하지 않는다.

모든 삭제 단계 후에는 상태가 비었는지와 주요 AWS 자원 ID가 제거됐는지 확인한다. AWS의 삭제 반영 지연·조회 권한·잔존 자원 때문에 VerificationFailed가 표시되면 **verification.json**과 오류를 확인한다. 삭제 단계가 모두 끝난 경우에만 다음 읽기 전용 재검증을 사용할 수 있다.

```powershell
# 저장된 대상 목록으로 결과만 다시 조회한다. 삭제 Plan을 재적용하지 않는다.
.\infra\scripts\destroy-all.ps1 -Action Verify -RunId $destroyRunId
```

전체 삭제는 `destroy-all.ps1`로 실행한다. 내부용 `infra.ps1 -PlanMode Delete -DestroyRunId ...`는 실행 상태와 선행 단계 완료를 확인하므로 개별 단계의 우회 삭제 명령으로 사용하지 않는다. 구조·검사 범위는 [전체 삭제 라우팅 문서](infra-routing/scripts/destroy-all.ps1.md)에 있다.

## 7. 배포 장애 확인과 재개

이 절은 원인을 확인한 뒤 실패한 단계로 돌아가는 절차다. 성공한 앞 단계를 무조건 반복하거나 DB·클러스터를 삭제해 초기화하지 않는다. 실행 터미널은 [배포 문서의 구분](deployment-runbook.md#2-어느-터미널에서-실행하는가)을 따른다.

### 7.1 실행 대상이 없거나 설치되지 않은 서비스

`skipping: no hosts matched`는 Limit 밖의 play 또는 없는 역할 그룹일 수 있다. 의도한 대상 그룹까지 비어 있는지 WSL에서 확인한다.

```bash
# 실제 배포에서 생성한 인벤토리 파일을 선택한다.
source "$HOME/.venvs/platform/bin/activate"
cd /mnt/c/third_project/aws-platform/platform
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
inventory="$PWD/inventory/hosts.current.yml"
ansible-inventory -i "$inventory" --graph
ansible -i "$inventory" all -m ansible.builtin.ping
```

Vault가 있는 환경은 [비밀번호 환경변수](deployment-runbook.md#91-vault-비밀번호와-db-secret)를 먼저 준비한다. hosts.budget.yml 등 다른 구성을 썼다면 inventory 경로도 맞춘다. 현재 의도적으로 쓰지 않는 monitoring 그룹이 없다면 해당 역할을 추가할 필요는 없다.

서비스 상태가 `LoadState=not-found`라면 서비스 이름과 [역할 설치 명령](deployment-runbook.md#11-역할별-서비스-설치)을 확인한다. common 태그는 DB·Kafka를 설치하지 않고, zookeeper 태그만 실행하면 Spark 서비스가 생성되지 않는다. SSH ping 성공은 서비스 설치 성공을 뜻하지 않는다.

확인 뒤 [역할별 설치](deployment-runbook.md#11-역할별-서비스-설치)로 돌아간다. 클러스터 역할은 일부 서버만 임의로 골라 재실행하지 않고 해당 역할 전체를 대상으로 한다.

### 7.2 SSH 인증 또는 접속 시간 초과

Windows PowerShell과 배스천·프라이빗 EC2의 터미널을 먼저 구분한다. `C:\...` 파일은 Windows에 있고 배스천 Linux에서는 사용할 수 없다. 기본 배스천 키는 project-bastion.pem, 목적지 서버 키는 해당 계정의 PEM이다. 생성 인벤토리는 두 키를 구분해 경유한다.

| 출력 | 확인할 내용 |
| --- | --- |
| Identity file not accessible / No such file | 파일 경로와 Windows·WSL·EC2 실행 위치. 개인키 내용을 출력하지 않고 존재 여부 확인 |
| UNPROTECTED PRIVATE KEY FILE / bad permissions | WSL 개인키의 소유자와 접근 권한. [WSL 키 준비](deployment-runbook.md#72-기존-windows-키를-wsl에-복사) 참고 |
| Permission denied (publickey) | Ubuntu 로그인 사용자, 배스천·목적지 각각의 키 경로, 등록된 공개키와의 대응 |
| Connection timed out | 현재 EC2 주소·전원 상태, SSH 22 경로, 관리자 CIDR, SG·Peering·라우팅·서버 방화벽 |

EC2 재생성이나 배스천 재시작 뒤에는 [4절 상태 확인](#4-배스천-상태-조회와-중지시작)과 [4.1절 주소 갱신](#41-배스천-주소가-바뀐-뒤-다시-연결)을 먼저 한다. 현재 PC가 다른 네트워크에 있다면 관리자 공인 IP 허용 범위를 대조한다.

게임 접속용 game_client_cidrs는 ALB HTTP 접속 범위이고 배스천 SSH용 admin_public_cidrs와 다르다. [공인 IP 확인](#3-테스트용-공인-ip-조회와-게임-접속-허용-설정) 결과를 바탕으로 선택한 traffic의 해당 목록을 구분해서 수정하고, 영향을 받는 계정 workload의 새 Plan을 검토한다. 전체 인터넷 대역을 열어 우회하지 않는다.

파일·권한·네트워크를 확인했는데 실제 등록 키 전환이 필요한 경우에만 [5절 키 전환](#5-계정별-새-ssh-키-준비와-기존-서버-등록)을 따른다. 복구 뒤 [WSL 접속 검사](deployment-runbook.md#73-wsl-실행-환경과-인벤토리-확인)에서 ping을 다시 확인한다.

### 7.3 Squid 접근 거부 또는 프록시 연결 실패

`ERR_ACCESS_DENIED`·Squid 403 응답은 요청이 프록시까지 도달했지만 접근 규칙에서 거부된 경우다. 배스천 프록시 IP와 선택한 인벤토리의 VPC CIDR·proxy_client_cidrs를 대조하고 [bootstrap-proxy 설명](../../aws-platform/platform/docs/platform-routing/bootstrap-proxy.yml.md)에서 관리 ACL과 최종 deny 순서를 확인한다.

프록시 접속 자체가 시간 초과라면 배스천 서비스의 수신 포트와 클라이언트 → 배스천 TCP 3128의 SG·서버 방화벽·Peering 경로를 확인한다. 현재 프록시 포트가 설정에서 변경됐다면 그 값을 사용한다. 배스천 EC2 터미널에서 상태를 조회할 수 있다.

```bash
# 배스천에서 서비스와 기본 프록시 수신 포트를 조회한다.
sudo systemctl is-active squid
sudo ss -lntp '( sport = :3128 )'
```

입력·주소가 맞으면 [8절 프록시 준비](deployment-runbook.md#8-전체-프록시와-apt-준비)의 방법 하나를 선택해 재실행한다. 이 단계는 Squid ACL·배스천 방화벽·APT를 관리하므로 deny all을 지우거나 임의의 전역 허용 규칙을 덧붙이는 방식으로 고치지 않는다. `failed=0`, `unreachable=0`과 `프록시 준비 완료`를 확인하고 중단된 설치 단계로 돌아간다.

### 7.4 Vault 비밀번호 또는 Secret 오류

`Attempting to decrypt but no vault secrets found`는 Ansible에 Vault 비밀번호가 전달되지 않은 경우다. WSL에서 기존 비밀번호 파일을 사용하도록 설정한다.

```bash
# 기존 파일을 사용한다. 파일 내용이나 비밀값은 출력하지 않는다.
export ANSIBLE_VAULT_PASSWORD_FILE="$HOME/.config/platform/vault-pass"
test -r "$ANSIBLE_VAULT_PASSWORD_FILE"
```

파일이 없거나 Secret이 아직 준비되지 않았다면 [9.1절 Vault 준비](deployment-runbook.md#91-vault-비밀번호와-db-secret)로 돌아간다. 암호가 틀리면 기존 Vault를 만든 비밀번호를 사용한다. 비밀번호를 잃었다는 이유로 새 비밀번호·DB Secret을 생성해서 기존 DB와 다른 값으로 덮어쓰지 않는다.

WSL에서 설정한 환경변수는 PowerShell이 새로 여는 WSL 프로세스에 자동 전달되지 않는다. Vault가 있는 환경의 프록시 재실행은 [8절 WSL 실행 방법](deployment-runbook.md#8-전체-프록시와-apt-준비)을 사용한다. 준비 뒤 실패한 역할 전체의 설치 명령을 다시 실행한다.

### 7.5 ZooKeeper 역할 조회 실패 또는 Spark 설치 중단

ZooKeeper의 `This ZooKeeper instance is not currently serving requests` 또는 빈 `Mode` 응답은 정상 ensemble 검증을 통과한 상태가 아니다. WSL에서 해당 역할의 로그와 포트 수신 상태를 조회한다. 아래 inventory 변수는 7.1절에서 선택한 실제 파일을 사용한다.

```bash
# 로그와 포트는 조회만 한다. 서비스를 초기화하거나 데이터를 지우지 않는다.
ansible spark -i "$inventory" -b -m ansible.builtin.command \
  -a 'journalctl -u zookeeper.service -n 80 --no-pager'
ansible spark -i "$inventory" -b -m ansible.builtin.command \
  -a 'ss -lnt'
```

Spark 노드끼리 클라이언트 2181·동기화 2888·리더 선출 3888을 허용해야 한다. 연결 시간 초과는 SG·서버 방화벽·Peering·라우팅과 수신 상태를 함께 확인해야 하며, TCP 연결 한 번의 실패만으로 SG를 원인으로 단정하지 않는다. 선택한 구성의 traffic과 실제 적용한 계정·단계를 대조한다.

기본 배치의 관련 계정은 account2·account3·account4다. 선택한 프로필의 배치가 다르면 실제 Spark 계정을 사용한다. 필요한 변경을 [9.3절 통신 조건](deployment-runbook.md#93-현재-서비스-통신과-선택한-구성-확인)과 [workload Plan·Apply](deployment-runbook.md#53-서비스-ec2ebs통신-규칙alb-workload)에 따라 반영한 후 [ZooKeeper·Spark 설치](deployment-runbook.md#114-zookeeper와-spark--통신-조건-반영-후)를 다시 실행한다.

Spark Worker의 active만으로 Master 선출·Worker 등록·PySpark 작업까지 성공했다고 판단하지 않는다. [Spark 검증 작업](../../aws-platform/platform/docs/platform-routing/roles/spark/tasks/verify.yml.md)을 설치 결과와 함께 확인한다. 로그에 나온 다른 오류는 해당 역할의 코드·문서에서 확인하며 여기서는 클러스터 데이터 삭제를 복구 절차로 제시하지 않는다.

### 7.6 PowerShell 또는 WSL 실행 오류

깨진 한글과 `문자열에 " 종결자가 없습니다`가 함께 나오면 Windows PowerShell 5.1이 읽는 한국어 ps1 파일의 UTF-8 BOM 여부와 실제 구문 오류를 확인한다. 이 문서 작업은 실행 파일의 인코딩을 변경하지 않는다.

WSL 실행 경로 여러 개가 하나의 명령처럼 나온다면 [deploy.ps1 설명](infra-routing/scripts/deploy.ps1.md)의 단일 실행 파일 선택과 실제 체크아웃을 대조한다. WSL 배포판·Ansible 가상환경이 없다는 오류는 [7절 도구 준비](deployment-runbook.md#7-내-pc의-wsl에-ansible과-키-준비)로 돌아간다. 프록시 단계는 준비된 WSL에서 [8절 스크립트](deployment-runbook.md#8-전체-프록시와-apt-준비)를 직접 실행할 수 있다.

### 7.7 Terraform 계획 오류와 배포 재개

| 출력 또는 상황 | 조치 |
| --- | --- |
| S3 NoSuchBucket·버킷 이름 누락 | [1절](#1-s3-상태-버킷-설정-복원)에서 이전 배포의 버킷을 대조. 실제 상태 객체가 사라졌다면 이 이름 설정만으로 복구되지 않음 |
| AWS 만료 인증·AccessDenied | [3.1절 인증](deployment-runbook.md#31-windows-도구와-aws-인증)에서 실제 계정·프로필 확인. 잘못된 계정으로 다시 배포하지 않음 |
| AMI 값 누락·InvalidAMIID | [2절](#2-account-1-ubuntu-ami-조회와-설정)에서 계정·리전·AMI 조회 결과 확인 |
| 저장 Plan·fingerprint·원격 상태 변경 오류 | 선택한 프로필·단계·계정으로 새 Plan 생성. 예전 계획을 강제로 재사용하지 않음 |
| prevent_destroy로 삭제·교체 Plan 실패 | 데이터 EBS 보호와 변경 범위 확인. 배치 변경은 데이터 이전 계획을 먼저 준비하며 전체 삭제를 의도한 경우에만 [6절](#6-전체-인프라-삭제) 선택 |
| Apply 중 일부 단계 실패 | 앞 단계의 성공한 자원은 남아 있음. 오류 원인을 해결한 뒤 실패 단계의 새 Plan부터 재개 |
| 삭제 단계 실패·VerificationFailed·ProtectionRestoreFailed | 배포 재실행과 구분해 [6절의 실행 ID·상태·복원 확인](#6-전체-인프라-삭제) 수행 |

인프라 변경 후 주소가 바뀌면 [Inventory](deployment-runbook.md#6-현재-ec2-주소로-인벤토리-생성)를 갱신한다. 프록시·방화벽·클러스터 설정의 IP 변경 영향도 [4.1절](#41-배스천-주소가-바뀐-뒤-다시-연결)에 따라 확인한다. 실패한 배포를 이어서 진행할 때는 [5절 단계별 실행](deployment-runbook.md#5-terraform으로-네트워크와-ec2-생성)으로 돌아간다.

## 문서의 검증 범위

기존 scripts.md의 명령과 현재 로컬 실행기·라우팅 설명을 기준으로 정리했다. 문서 링크·제목·명령 구문은 정적으로 검사하며 AWS·SSH·Ansible 원격 적용 또는 데이터 복구를 실행한 기록은 아니다. 실제 오류의 원인은 로그·선택한 구성·적용 상태를 대조하여 확인한다.
