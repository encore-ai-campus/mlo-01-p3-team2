# aws-infra-test

사람들이 게임을 시험하는 데 쓰는 별도 인프라다. 기존 `aws-infra` 파일·상태는 변경하지 않는다. 실제 AWS 생성·클러스터 설치·부하 검증은 아직 수행하지 않았다.

## 구성

- 서울 리전, 모든 계정에서 실제 AZ ID `apne2-az1` 하나만 사용한다.
- account1~account5의 VPC와 Peering 10개를 별도로 만든다. CIDR은 기존과 같지만 다른 VPC이며 기존 VPC와 Peering하지 않는다.
- 서비스 16대 + 필요 시 Bastion 1대, 모두 `t3a.small`. Front는 `front-a` 한 대다.
- ALB·HTTPS·CloudFront·NAT는 생성하지 않는다. 접속은 `http://Front공인IP`다.
- Nginx: `/static/*` → 로컬 정적 파일, `/ads/*` → ad-server:8000, 나머지 및 WebSocket → game-server:8000.
- OS 20GiB × 17, 데이터 20GiB × 12 = Bastion 포함 총 EBS 580GiB. 테스트 데이터 보존 기간·용량은 직접 관리한다.
- Front EIP 한 개를 사용한다. Bastion은 EIP 없이 자동 공인 IP를 사용한다. 실행 중 공인 IPv4와 EC2·EBS 등은 과금 대상이며 전체 비용이 무료라는 의미가 아니다.
- CPU 크레딧은 `standard`: 초과 크레딧 과금 대신 소진 시 성능이 제한된다. small·단일 AZ는 150명 부하나 장애 가용성을 보장하지 않는다.

## 기존 환경과 분리

| 항목 | 테스트 |
|---|---|
| Project 및 자원 이름 prefix | aws-infra-test |
| S3 상태 prefix | aws-infra-test |
| 상태 예시 | aws-infra-test/account1/workload/terraform.tfstate |
| 키페어 이름 | aws-infra-test-accountN, aws-infra-test-account1-bastion |
| 로컬 계획·삭제 기록 | infra/.local/ |
| Ansible 인벤토리 | infra/bootstrap/inventory/hosts.test.yml |

S3 버킷은 기존 버전 관리 버킷을 재사용하되 key가 다르다. 실행기는 prefix·프로젝트·키페어·A·small을 검사한다. 기존 상태·Plan·Terraform 캐시·개인키는 복사하지 않았다. AWS CLI 프로필은 기존 account1~account5를 사용한다. 두 환경을 동시에 생성하면 비용도 동시에 발생한다.

## 실행 준비

PowerShell에서 이 README가 있는 `aws-infra-test` 폴더로 이동한다. 현재 PC 경로는 `C:\third-project\aws\aws-infra-test`다.

1. Terraform, AWS CLI, PowerShell 및 계정별 인증을 준비한다.
2. `infra/config/backend.json`의 버킷·리전·프로필, topology의 계정 ID·AMI를 확인한다. `key_prefix`는 바꾸지 않는다.
3. `traffic.tfvars.json`의 `admin_public_cidrs`와 `game_client_cidrs`를 접속할 현재 공인 IP CIDR로 맞춘다. 원본에서 가져온 IP가 현재 학교 IP라는 보장은 없다.
4. 아래 명령으로 기존의 계정별 공개키를 복사한다. `.pub`만 복사하며 개인키는 PC에 둔다.

```powershell
.\infra\scripts\prepare.ps1
```

다른 곳의 공개키는 `-PublicKeyDirectory '공개키 폴더'`로 지정한다. WSL의 개인키 경로·배포판·Ansible 가상환경은 `infra/config/platform.json`에서 설정한다. 기존 `../aws-platform/platform`의 역할과 Ansible 환경을 읽어서 사용하며 해당 폴더에는 쓰지 않는다.

## 한 번에 생성

```powershell
.\infra\scripts\deploy.ps1 -Action Deploy
```

foundation 5계정 → connectivity → workload 5계정 → Bastion 순서로 Plan을 만들고 단계별 `APPLY` 입력 뒤 적용한다. 이어 현재 IP 인벤토리 → Bastion Squid·APT → Front Nginx를 준비한다. 실패하면 다음 단계로 가지 않는다. 앞 단계의 자원은 자동 삭제하지 않는다.

**이 명령은 게임·광고 앱·Consumer 코드를 배포하지 않는다.** 앱 코드는 이 저장소의 인프라 설치 범위에 없으므로 각 서버에 따로 배포하고 8000번으로 실행한다. Django의 `ALLOWED_HOSTS`에 Front 접속 주소를 설정한다. 앱이 없으면 Front의 앱 경로는 502를 반환할 수 있다.

정적 파일은 Django `collectstatic` 결과 폴더를 지정해 별도로 배포할 수 있다.

```powershell
.\infra\scripts\deploy.ps1 -Action Front -StaticDirectory 'C:\path\to\collected-static'
```

`-Action Front`에 폴더를 지정하지 않으면 Nginx만 준비하며 빈 정적 파일을 앱 배포 완료로 취급하지 않는다.

## 프록시를 이용한 클러스터 설치

`infra/bootstrap/vars/vault.example.yml`을 참고하여 **테스트용** `vault.yml`을 준비한다. 기존 운영 비밀번호를 자동 복사하지 않는다. MySQL 여섯 계정, MongoDB 세 계정과 Replica Set keyfile이 필요하다. 모니터링 노드를 설치하지 않으므로 예제의 monitor SSH 키는 사용하지 않는다. Vault 비밀번호 파일 경로 설명은 기존 platform 기준이므로 이 테스트 파일에 맞게 지정한다. 파일은 Git에서 제외된다.

이미 Deploy가 끝났다면:

```powershell
.\infra\scripts\deploy.ps1 -Action Install -VaultFile '.\infra\bootstrap\vars\vault.yml'
```

새 인프라부터 클러스터까지 한 명령으로 진행하려면:

```powershell
.\infra\scripts\deploy.ps1 -Action All -VaultFile '.\infra\bootstrap\vars\vault.yml'
```

Install은 테스트 EBS ID로 NVMe 장치를 확인하고 빈 장치만 ext4로 포맷·UUID 마운트한다. 기존 파일·파티션·다른 파일시스템이 있으면 중단한다. MySQL·MongoDB·Kafka·Spark의 데이터 경로를 별도 EBS에 둔다. 이후 common/firewall → MySQL 3노드 → MongoDB 3노드 → Kafka 3노드 → ZooKeeper/Spark 3노드 → game/Spark MySQL Router 순서다. small 전용 메모리 값을 전달한다. 암호화된 Vault는 실행 중 비밀번호를 묻는다.

다운로드는 Bastion Proxy:3128을 사용하고 클러스터 통신은 사설 IP·Peering을 사용한다. `NO_PROXY`에는 내부 IP를 명시한다. 20GiB 데이터 디스크가 가득 차지 않도록 확인한다. 실제 메시지 처리·DB 복제·게임 이벤트 연동은 별도 검증 대상이다. 작은 Spark 노드에 작업을 제출할 때는 `--driver-memory 512m --executor-memory 512m --total-executor-cores 1`부터 시험한다. 기본 1GiB executor 요청은 Worker 예산보다 클 수 있다.

## 부분 실행 및 재개

```powershell
.\infra\scripts\deploy.ps1 -Action Plan -Stage workload -Account account1
.\infra\scripts\deploy.ps1 -Action Apply -Stage workload -Account account1
.\infra\scripts\deploy.ps1 -Action Inventory
.\infra\scripts\deploy.ps1 -Action Proxy
.\infra\scripts\deploy.ps1 -Action Front
```

설정 변경 후에는 새 Plan부터 실행한다. `Apply`는 저장된 Plan의 대상·코드·설정·공개키 해시를 검사한다. 인벤토리를 갱신하면 현재 Bastion 주소도 반영된다.

## Bastion만 생성·삭제

```powershell
.\infra\scripts\bastion.ps1 -Action PlanCreate
.\infra\scripts\bastion.ps1 -Action Create
.\infra\scripts\bastion.ps1 -Action PlanDelete
.\infra\scripts\bastion.ps1 -Action Delete
```

삭제 후 클러스터의 사설 통신은 유지되지만 SSH 경유·프록시 다운로드·그 경로의 외부 API 사용은 중단된다. 재생성 후 Inventory → Proxy를 다시 실행한다. 중지(Stop)는 삭제가 아니므로 디스크 비용을 없애지 못한다.

## 한 번에 전체 삭제

**테스트 서버와 테스트 데이터 EBS까지 삭제한다.** 기존 `aws-infra` 폴더에서 실행하지 않는다.

```powershell
.\infra\scripts\destroy-all.ps1 -Action Destroy -DeleteDataVolumes
```

이 명령은 삭제 계획을 자동 검사한 다음 별도 입력 없이 적용한다. Bastion → workload 5개 → connectivity → foundation 5개 순서이며, 테스트 태그·소유권·상태 해시·자원 범위를 검사한다. 계획을 먼저 직접 검토하려면:

```powershell
.\infra\scripts\destroy-all.ps1 -Action Plan -DeleteDataVolumes
# 앞 명령이 출력한 RunId로만 적용한다.
.\infra\scripts\destroy-all.ps1 -Action Apply -RunId '<출력된 RunId>' -DeleteDataVolumes
```

삭제 중 실패하면 오류를 해결한 뒤 새 Plan부터 진행한다. 상태 버킷과 버전 이력·별도로 만든 스냅샷·콘솔 수동 자원은 삭제하지 않는다. 결과는 `.local/destroy-all/<RunId>/verification.json`에서 확인한다.

## 로컬 검증과 코드 위치

```powershell
.\infra\tests\check.ps1
.\infra\tests\check.ps1 -Terraform
```

`-Terraform`은 backend 없이 Validate와 mock provider Test를 실행한다. 처음에는 provider 다운로드가 필요할 수 있으며 로컬 provider 폴더는 `-PluginDirectory`로 지정할 수 있다. [구조 안내](docs/ROUTING.md)와 [검증 기록](docs/verification.md)을 참고한다.

WSL의 로컬 설치 문법·Front 렌더링 검사는 `bash infra/tests/check-bootstrap.sh`로 실행한다. 이 검사는 원격 서버에 연결하지 않는다.

## 2026-10-12 학원 접속 범위

- 학원 공인 IP는 `222.112.208.69/32`다. 앞서 전달된 `.72`는 사용하지 않는다.
- `admin_public_cidrs`: 학원 IP. Bastion SSH 22 및 Private 서버의 역할별 SG에 학원 IP의 SSH 22를 허용한다.
- `public_http_cidrs`: `0.0.0.0/0`. Public Front의 HTTP 80만 전체 공개한다. 필드가 없는 이전 프로필은 game_client_cidrs로 동작한다.
- `game_client_cidrs`: 학원 IP. 기존 edge HTTPS 443 범위를 전체 공개로 확대하지 않는다.
- Bastion의 EC2 Instance Connect 콘솔 SSH 출처 규칙은 생성하지 않는다. 기존 규칙이 있다면 다음 workload Plan에 해당 규칙 삭제가 표시된다. 서비스 서버의 기존 콘솔 SSH 규칙은 유지한다.
- Private SSH CIDR 규칙은 인터넷 경로를 만들지 않는다. Bastion 경유 시 목적 서버에는 Bastion 사설 IP가 출처로 보이므로 기존 Bastion→서버 SG 규칙도 유지한다. OS 방화벽·접속 경로의 실제 성공은 별도다.
- 기존 저장 Plan은 다시 만들어야 한다. 코드만 수정했으며 AWS Apply는 실행하지 않았다.
