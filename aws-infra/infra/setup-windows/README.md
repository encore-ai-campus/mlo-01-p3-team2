# Windows 노트북 도구 설치

Terraform과 AWS CLI v2를 설치하는 `install-tools.ps1`입니다. 다른 노트북에서도 이 폴더를 복사해서 실행할 수 있습니다. AWS 로그인·계정 설정과 AWS 자원 생성은 설치 이후 별도로 진행합니다.

저장소 내 위치는 `infra/setup-windows/`입니다. 인프라 실행 순서는 [공통 실행 안내](../README.md)를 참고합니다.

**진행 순서: 설치 상태 확인 → 필요한 도구 설치 → 새 PowerShell에서 버전 확인 → AWS 로그인 → 두 프로필의 리전 및 인증 연결 설정 → 계정 확인.**

이 스크립트의 담당 범위는 도구 설치와 PATH 등록입니다. 아래 AWS 로그인 명령은 사용자가 별도로 실행합니다. VPC·EC2 생성은 설치 스크립트가 실행하지 않습니다.

## 실행

Intel/AMD 64비트 Windows에서 **일반 권한의 64비트 Windows PowerShell 5.1 이상**을 사용합니다. Windows 11을 권장하며, Windows 10에서도 PowerShell 5.1 문법으로 실행할 수 있습니다. 인터넷 연결이 필요합니다. ARM 노트북과 WSL은 이 스크립트의 대상이 아닙니다.

저장소를 받은 폴더에서 PowerShell을 열고 실행합니다.

```powershell
# 저장소 위치로 이동한다. 다른 위치에 받았다면 해당 경로로 바꾼다.
Set-Location "C:\third_project\aws-infra"

# 먼저 설치 상태만 확인한다. 필요한 도구가 없으면 설치 필요 메시지가 나온다.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\infra\setup-windows\install-tools.ps1 -CheckOnly

# 이번 실행에만 실행 정책 옵션을 적용하고 설치한다.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\infra\setup-windows\install-tools.ps1
```

마지막 명령은 **사용자 PATH를 영구적으로 등록**합니다. 현재 창에만 `$env:Path`를 추가했던 수동 방식과 적용 범위가 다릅니다. `-CheckOnly`는 설치와 PATH 등록을 하지 않습니다. 이미 도구와 PATH가 준비되어 있다면 설치 명령을 생략하고 버전 확인으로 넘어가도 됩니다.

`setup-windows` 폴더만 복사했다면 그 폴더에서 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-tools.ps1
```

사용자 이름이나 저장소 경로를 코드에 입력할 필요가 없습니다. 현재 Windows 사용자에게 설치하므로 관리자 권한으로 다시 열 필요도 없습니다. 회사·학교의 그룹 정책으로 실행이나 설치가 차단된다면 해당 관리자의 정책을 따라야 합니다.

## 실행 순서

1. 기존 Terraform과 AWS CLI를 찾고 실행 가능한 버전인지 확인합니다.
2. Terraform이 없으면 HashiCorp 공식 API에서 현재 정식 버전을 조회하고 ZIP과 SHA256 목록을 받습니다. 체크섬과 실행 파일 버전을 검사한 뒤 설치합니다.
3. AWS CLI v2가 없으면 공식 사용자용 MSI를 받아 Windows 디지털 서명을 검사하고 설치합니다.
4. 사용자 PATH에 필요한 폴더를 중복 없이 추가하고 두 명령의 실행을 확인합니다.

| 도구 | 새로 설치할 위치 | 기존 설치 처리 |
| --- | --- | --- |
| Terraform | `%USERPROFILE%\tools\terraform` | 1.6 이상, 2.0 미만이면 유지 |
| AWS CLI v2 | `%LOCALAPPDATA%\Programs\Amazon\AWSCLIV2` | 2.32.0 이상인 v2 유지; v1 또는 더 오래된 v2면 중단 |

Terraform은 PATH를 먼저 찾고, `%USERPROFILE%\tools\terraform`, `%USERPROFILE%\tools`, `%USERPROFILE%\tools\terraform_<1.x 버전>_windows_amd64` 폴더도 확인합니다. 버전 이름의 폴더가 여러 개면 버전이 높은 순서로 확인합니다. 따라서 현재 컴퓨터의 `C:\Users\user\tools\terraform_1.16.5_windows_amd64\terraform.exe`도 다시 설치하지 않고 재사용합니다. 다른 임의의 폴더는 자동으로 탐색하지 않습니다.

기존 설치를 자동 업그레이드하거나 삭제하지 않습니다. `aws login`을 사용하려면 AWS CLI 2.32.0 이상이 필요하므로 더 오래된 버전이면 공식 설치 파일로 업데이트한 후 다시 실행합니다. Terraform 최신 정식 버전이 프로젝트의 범위인 1.6 이상, 2.0 미만을 벗어나면 설치를 중단합니다. 최신 AWS CLI 설치 파일의 운영체제 지원 범위는 AWS 공식 안내를 따릅니다.

설치가 끝나면 **PowerShell을 새로 열고** 확인합니다. VS Code 터미널을 쓴다면 VS Code 전체를 다시 실행합니다.

```powershell
# 두 프로그램의 버전이 출력되면 명령을 사용할 수 있다.
terraform --version
aws --version
```

`aws --version` 성공은 CLI 설치 확인이며, AWS 계정 로그인 완료를 뜻하지 않습니다.

## 설치 후 AWS 로그인 및 인증 설정

아래는 IAM 사용자로 AWS 콘솔에 로그인하는 현재 프로젝트의 방식입니다. 사용자의 `SignInLocalDevelopmentAccess` 권한이 필요하며, 실제 네트워크 조회·생성 권한은 별도로 필요합니다. IAM Identity Center를 사용하는 조직은 조직의 SSO 설정 방식을 따릅니다.

### 1. 로그인용 프로필에 리전을 저장하고 로그인

```powershell
# 로그인할 때뿐 아니라 나중에 인증 정보를 갱신할 때도 쓸 리전을 저장한다.
aws configure set region ap-northeast-2 --profile aws-infra-login
aws login --profile aws-infra-login --region ap-northeast-2
```

브라우저에서 사용할 계정을 선택하고 승인합니다. 터미널에 AWS skills / MCP 추가 설정 질문이 나오면 이 세팅에는 필요하지 않으므로 `n`을 입력합니다. 로그인에 실패하면 다음 단계로 넘어가지 않고 오류를 확인합니다.

### 2. Terraform용 프로필 연결

```powershell
# Terraform이 로그인용 프로필에서 임시 인증 정보를 받아 사용하도록 연결한다.
aws configure set credential_process "aws configure export-credentials --profile aws-infra-login --format process" --profile aws-infra
aws configure set region ap-northeast-2 --profile aws-infra
```

`aws-infra-login`은 로그인 정보를 관리하는 프로필이고, `aws-infra`는 Terraform이 사용할 프로필입니다. 두 이름은 이 문서에서 정한 이름이며 AWS 계정 이름이나 VPC 이름이 아닙니다. **리전은 두 프로필에 모두 저장합니다.** 로그인 명령에 `--region`만 붙이고 저장을 생략하면 이후 `NoRegion` 오류가 날 수 있습니다.

### 3. 두 프로필의 인증 확인

```powershell
# 두 명령을 하나씩 실행하고 Account 값이 사용할 AWS 계정인지 확인한다.
aws sts get-caller-identity --profile aws-infra-login
aws sts get-caller-identity --profile aws-infra
```

두 명령 모두 성공하고 올바른 계정 ID가 나오면 로컬 세팅이 완료됩니다. 인증 유효기간이 끝난 경우 로그인 명령을 다시 실행합니다. 리전과 프로필 연결 설정은 저장되므로 매번 다시 입력할 필요는 없습니다.

실제로 사용할 계정 설정은 저장소 최상위의 `config/account1/account.tfvars.json`에 저장합니다. `aws_account_id`에는 확인한 계정 ID, `aws_region`에는 서울 리전인 `ap-northeast-2`, `aws_profile`에는 `aws-infra`를 지정합니다. 이 파일은 대상 계정 설정이며, 위의 AWS 로그인과 프로필 연결은 별도로 완료해야 합니다. 현재 작업 폴더에는 이 파일을 자동으로 읽는 배포 스크립트가 없으므로, 추후 배포 구성을 추가할 때 이 경로를 연결합니다.

## 설치 상태만 확인

```powershell
# 다운로드·설치·PATH 변경 없이 확인한다.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\infra\setup-windows\install-tools.ps1 -CheckOnly
```

두 도구가 준비됐으면 종료 코드 0, 설치가 필요하거나 오류가 있으면 0이 아닌 종료 코드를 반환합니다. PATH 외에 위의 기본 설치 폴더도 확인하므로 `-CheckOnly`가 성공해도 현재 터미널의 PATH가 아직 갱신되지 않았을 수 있습니다.

실패하면 오류 원인을 해결한 뒤 다시 실행합니다. 설치된 도구는 재사용합니다. 다운로드 또는 설치에 실패한 경우 `%TEMP%\aws-infra-tools-<임의 ID>`에 파일을 남기며, MSI가 실행된 경우 `aws-cli-install.log`도 확인할 수 있습니다. 성공하면 해당 임시 폴더를 정리합니다. 스크립트는 PC를 자동 재부팅하지 않습니다.

## 공식 설치 자료

- [Terraform 설치와 체크섬 안내](https://developer.hashicorp.com/terraform/install)
- [Terraform 정식 버전 조회](https://checkpoint-api.hashicorp.com/v1/check/terraform)
- [AWS CLI 설치 안내 — Windows 사용자용 MSI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [AWS 로그인 조건 및 Terraform용 인증 연결](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html)
