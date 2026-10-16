# infra/setup-windows/install-tools.ps1

[탐색 시작점](../ROUTING-README.md) · [원본 설치기](../../../infra/setup-windows/install-tools.ps1) · [기존 설치 안내](../../../infra/setup-windows/setup-windows.md)

## 용도와 입력

Intel/AMD 64비트 Windows, PowerShell 5.1 이상에서 Terraform과 AWS CLI를 현재 사용자에게 설치한다. 유일한 선택 옵션은 CheckOnly다. 이 스크립트는 AWS 로그인·계정 구성·AWS 자원 배포를 실행하지 않는다.

CheckOnly는 설치와 PATH 등록 없이 도구 존재·버전을 확인한다. 일반 실행은 필요한 다운로드·설치와 사용자 PATH 등록을 수행한다. 이번 문서 작성에서 설치기는 실행하지 않았다.

## 함수 탐색

| 함수 | param 선언 | 동작 |
| --- | --- | --- |
| Find-Tool | ([string]$Name, [string[]]$FallbackDirectories) | PATH를 먼저 찾고 지정 폴더의 실행 파일로 보완 |
| Get-ToolVersion | ([string]$Executable, [string]$Name) | 별도 프로세스로 --version 실행, 출력 파싱, 30초 제한 |
| Add-UserPath | ([string]$Directory) | 사용자·현재 프로세스 PATH에 중복 없이 추가 |
| Save-Download | ([string]$Uri, [string]$Destination) | HTTPS 파일 다운로드 |
| Assert-TerraformChecksum | ([string]$ArchivePath, [string]$ChecksumsPath) | 공식 목록의 파일명과 SHA-256 일치 검사 |

PowerShell 원본을 대조한 목록이다. Python AST 스킬의 검증 대상이 아니다.

## 설치 흐름과 위치

1. 운영체제·프로세스 아키텍처를 검사하고 기존 도구와 버전을 찾는다.
2. CheckOnly면 두 도구의 준비 여부에 따라 종료한다.
3. Terraform이 없으면 공식 릴리스 정보를 조회하고 ZIP·체크섬을 받아 검증한 뒤 설치한다.
4. AWS CLI가 없으면 사용자용 MSI를 받아 디지털 서명을 확인하고 숨김·무인 설치한다.
5. PATH와 실행 버전을 다시 확인한다. 성공한 임시 다운로드는 정리하고 실패한 자료는 남긴다.

| 대상 | 위치 |
| --- | --- |
| Terraform 신규 설치 | %USERPROFILE%/tools/terraform |
| AWS CLI 사용자 설치 탐색 | %LOCALAPPDATA%/Programs/Amazon/AWSCLIV2 |
| AWS CLI 시스템 설치 탐색 | %ProgramFiles%/Amazon/AWSCLIV2 |
| 임시 다운로드·MSI 로그 | %TEMP%/aws-infra-tools-{임의 ID} |

## 현재 버전 조건의 차이

설치기는 Terraform **1.6 이상 2.0 미만**, AWS CLI **v2 2.32.0 이상**을 허용한다. 그러나 현재 [Terraform stack](../terraform/README.md)은 Terraform **1.11 이상 2.0 미만**을 요구한다. 따라서 설치기의 CheckOnly 성공만으로 stack 요구사항까지 충족했다고 판단하면 안 된다.

기존 설치 README에는 aws-infra-login/aws-infra 프로필과 과거 config/account1 경로 안내가 남아 있다. 현재 실행기가 읽는 프로필과 설정 경로는 [config 문서](../config/README.md) 및 [실행기 문서](../scripts/infra.ps1.md)를 기준으로 확인한다. 이번 작업은 현재 동작을 문서화했으며 설치기나 기존 안내의 동작을 변경하지 않았다.
