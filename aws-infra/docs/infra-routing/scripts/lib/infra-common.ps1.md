# infra/scripts/lib/infra-common.ps1

[탐색 시작점](../../ROUTING-README.md) · [원본 파일](../../../../infra/scripts/lib/infra-common.ps1) · [호출하는 실행기](../infra.ps1.md)

PowerShell 5.1 공통 함수 모음이다. 아래 선언은 원본 PowerShell을 대조한 것이며 Python AST 스킬로 검증한 결과가 아니다.

| 함수 | param 선언 | 역할 |
| --- | --- | --- |
| Read-InfraJson | ([string]$Path) | 파일을 읽어 ConvertFrom-Json 결과 반환 |
| Get-InfraFileHash | ([string]$Path) | 파일 바이트의 SHA-256을 계산하고 스트림·알고리즘 객체 정리 |
| Write-InfraJson | ([string]$Path, $Value) | 깊이 30의 JSON을 UTF-8 BOM 없이 저장 |
| Invoke-InfraTerraform | ([string]$Command, [string]$Directory, [string[]]$Arguments) | -chdir로 실행하고 0이 아닌 종료 코드를 오류로 전달 |
| Assert-InfraConfiguration | ($Topology, $Traffic) | 계정·VPC·송신 방식·외부 CIDR·포트 검사 |
| Assert-InfraBackend | ($Backend, $Topology) | S3 버킷 이름·key_prefix 형식·리전·등록 프로필 검사 |
| Get-InfraFingerprint | ([string]$Root, [string]$PublicKeyPath) | 배포 입력 파일 목록과 각 해시를 합쳐 전체 fingerprint 생성 |

## 설정 검사의 범위

Assert-InfraConfiguration은 정확히 account1~account5가 있는지, ID·profile·VPC CIDR이 중복되지 않는지 확인한다. ID는 12자리, VPC는 IPv4 /16 형식이며 송신 방식은 proxy/nat/none 중 하나다. nat에는 public_subnets가 필요하다.

관리자·서비스 CIDR의 옥텟과 prefix, 네트워크 주소 정규화를 검사한다. 관리자 SSH의 0.0.0.0/0은 거부하며 포트는 1~65535 정수여야 한다. 전체 서버 스키마·역할 참조·Peering 관계 검사는 [model 모듈](../../terraform/README.md#model)이 추가로 담당한다.

Assert-InfraBackend는 로컬 값의 형식을 검사한다. 실제 AWS 계정·버킷 접근과 버전 관리는 호출자인 infra.ps1에서 AWS CLI로 검사한다.

## fingerprint에 들어가는 파일

- infra/config 바로 아래의 JSON 파일.
- infra/terraform 아래의 .tf 및 .terraform.lock.hcl 파일. .terraform 캐시 내부는 제외한다.
- infra/scripts/infra.ps1 및 infra/scripts/lib 바로 아래의 .ps1 파일.
- 선택한 공개키 파일이 존재하면 그 내용의 해시.

Markdown, 로컬 상태·계획·캐시, .tftest.hcl, prepare-key.sh, 설치 스크립트는 이 함수의 목록에 포함되지 않는다. 이 해시는 실행기의 저장 계획 유효성 검사에 사용하며, 프로젝트의 모든 파일이나 실제 AWS 상태를 비교하는 해시는 아니다.
