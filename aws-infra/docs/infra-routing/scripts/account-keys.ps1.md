# 계정별 SSH 키 준비·등록

대상 코드는 [account-keys.ps1](../../../infra/scripts/account-keys.ps1)이다. PowerShell 5.1 이상에서 실행한다. 실제 AWS 등록 성공을 기록한 문서는 아니다.

## 입력과 키 배치

- `Action`: `Prepare` 또는 `Register`.
- `Account`: `all` 또는 `account1`~`account5`. 기본값은 `all`. `Prepare`는 다섯 계정을 함께 준비한다.
- `KeyDirectory`: 기본값은 현재 사용자 프로필의 `.ssh/project-key`.
- Account 1 개인키 이름은 **project-bastion.pem**, 나머지는 **account2.pem**~**account5.pem**이다.

## 코드 흐름

| 함수 | 역할 |
| --- | --- |
| `Write-KeyText` | 공개키·설정·접속 안내 텍스트를 UTF-8 BOM 없이 저장 |
| `Protect-KeyFile` | 개인키가 현재 Windows 사용자 소유인지 확인하고, 그 사용자만 읽을 수 있도록 파일 ACL 설정 |
| `Read-KeyMaterial`, `Get-KeyInputs` | 다섯 파일 존재·공개키 추출·계정별 키 중복 검사. 개인키 내용은 출력하지 않음 |
| `Invoke-KeyPrepare` | 기존 공개키를 `.local/ssh-keys/previous-public/`에 백업. `config/keys/account1.pub`~`config/keys/account5.pub`와 계정별 `ssh_public_key_path`만 갱신 |
| `Invoke-KeyAws`, `Invoke-KeySsh` | 대상 프로필·리전을 명시하고 외부 명령 실패 시 중단 |
| `Get-KeyTag` | EC2 Tags에서 지정한 태그 값을 읽어 등록 대상 검사에 사용 |
| `Get-KeyInstallCommand` | `ubuntu`의 `authorized_keys`에 새 공개키를 중복 없이 추가. 기존 키는 보존 |
| `Invoke-KeyRegister` | 계정 ID·서버 태그·역할·개수·기동 상태를 확인한 뒤 Bastion과 서비스 서버에 공개키 등록 |

## AWS 등록과 경계

`Register`는 새 Account 1 키로 접근 가능한 Bastion이 필요하다. Bastion의 `authorized_keys`에 다섯 공개키를 추가하여 팀원이 자기 계정의 개인키로 Bastion을 경유하게 한다.

기존 서비스 서버는 각 계정의 EC2 Instance Connect `SendSSHPublicKey`로 임시 키를 전달한 후 Bastion을 거쳐 SSH로 접속한다. 원격 명령은 `ubuntu`의 `.ssh` 권한과 공개키 추가만 수행한다. EC2·EBS·ALB를 삭제하거나 재생성하지 않는다. EIC 설치, IAM 권한 및 SSH 경로가 필요하며 조건이 충족되지 않으면 오류로 중단한다.

필요한 AWS 권한은 STS `GetCallerIdentity`, EC2 `DescribeInstances`, EC2 Instance Connect `SendSSHPublicKey`다. Ubuntu 20.04 이후의 공식 AWS 이미지는 EIC가 기본 설치되지만 실제 원격 등록은 실행 결과로 확인해야 한다.

부분 성공 후 실패하면 앞서 등록한 키는 유지된다. 동일한 `Register`를 다시 실행할 수 있다. 새 공개키가 파일에 기록된 것을 확인하지만, EIC 임시 키가 만료된 뒤의 독립적인 SSH 접속 확인은 별도로 수행해야 한다.

## 출력과 후속 작업

접속 설정은 `.local/ssh-keys/ssh-config`에 생성된다. Bastion의 새 공인 IP와 서비스 사설 IP를 사용하며 개인키 파일 경로만 기록한다. 키 내용은 포함하지 않는다. 등록 완료 후 각 서비스의 `ProxyJump`는 해당 계정 개인키를 사용하는 Bastion 별칭으로 지정된다.

`Prepare`와 `Register`는 Terraform `Apply`를 실행하지 않는다. 서비스 키페어의 AWS 등록 정보를 맞추려면 이후 계정별 workload `Plan`을 검토하고 `Apply`해야 한다. 키페어 교체 외에 EC2 교체가 있으면 적용하지 말고 원인을 확인한다.

Bastion 재생성 시 추가 팀원 공개키는 자동 복원되지 않는다. 같은 설정으로 `Register -Account account1`을 다시 실행하면 Bastion의 다섯 공개키와 Account 1 서비스 서버의 공개키를 재등록한다.

팀원에게는 해당 계정 개인키와 필요한 SSH 접속 설정을 전달한다. 팀원 PC에서는 그 파일의 권한을 제한하고 `IdentityFile`을 자기 PC의 경로로 수정한다. 팀원 인터넷망의 공인 IP도 Bastion SSH 허용 CIDR에 포함되어야 한다.
