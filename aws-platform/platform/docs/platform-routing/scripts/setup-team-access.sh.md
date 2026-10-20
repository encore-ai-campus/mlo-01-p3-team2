# scripts/setup-team-access.sh

[스크립트 지도](README.md) · [인벤토리 지도](../inventory/README.md) · [원본](../../../scripts/setup-team-access.sh)

## 역할과 실행 경계

운영 PC의 WSL 또는 Linux Ansible 환경에서 실행한다. 준비된 EC2 Instance Connect Endpoint로 배스천의 사설 IP에 SSH 접속하고, 배스천을 거쳐 나머지 서버에 접속할 로컬 설정을 만든다. 프로젝트 위치·사용자 이름·AWS 프로필·키 디렉터리를 특정 PC 값으로 고정하지 않는다.

도구 설치, AWS 로그인, Endpoint·IAM·보안그룹 생성, 서버 공개키 등록, Squid 설정과 서비스 설치는 실행하지 않는다. 관리자가 접속 경로와 권한을 먼저 준비하고 사용자는 자신의 AWS 인증과 SSH 키를 준비한다. 배스천의 인터넷 다운로드용 공인 IP는 이 스크립트가 변경하지 않는다.

## 준비 조건

- WSL/Linux에 Bash, Python 3.8 이상, AWS CLI v2, OpenSSH와 Ansible이 있어야 한다. 일반 YAML 인벤토리를 읽을 때는 PyYAML도 필요하므로 Ansible 가상환경에서 실행한다. JSON 형식 YAML은 Python 표준 라이브러리로 읽는다.
- AWS 프로필에는 `sts:GetCallerIdentity` 호출이 가능한 인증, `ec2:DescribeInstanceConnectEndpoints`, 지정 Endpoint를 통한 배스천 IP·22번 포트의 `ec2-instance-connect:OpenTunnel` 사용 권한이 필요하다. SSH는 이미 서버에 등록된 키를 사용하므로 임시 공개키 전송은 하지 않는다.
- Endpoint는 `create-complete` 상태여야 한다. Endpoint → 배스천, 배스천 → 각 서버의 TCP 22 경로와 SG·OS 방화벽을 미리 준비한다. 클라이언트 IP 보존을 사용하면 그에 맞는 출발지 규칙도 필요하다.
- `bastion` 그룹에 정확히 한 대와 배스천 외 서버 한 대 이상이 필요하다. 각 서버에는 실제 사설 `ip`(없으면 `ansible_host`), `ansible_user`, `ansible_ssh_private_key_file`을 지정한다. SSH 포트는 22다.
- 키가 암호화되어 있다면 해당 키를 SSH agent에 먼저 등록한다. 접속 검사는 `BatchMode yes`를 사용하므로 비밀번호·키 암호를 물어보지 않는다.

Windows용 `install-tools.ps1`의 설치·인증 상태와 WSL의 상태는 별개다. 도구가 없거나 인증이 만료되면 해당 준비를 마친 뒤 재실행한다.

## 입력 옵션

| 옵션 | 필수 / 기본값 | 의미 |
| --- | --- | --- |
| `--inventory` | 필수 | 기존 정적 YAML/JSON 인벤토리. 상대 경로는 실행한 디렉터리 기준 |
| `--aws-profile` | 필수 | 현재 WSL의 AWS 프로필 이름 |
| `--region` | 필수 | Endpoint를 조회·사용할 리전 |
| `--endpoint-id` | 필수 | 이미 생성된 `eice-...` ID |
| `--key-directory` | 선택 | 기존 키 경로의 파일명은 유지하고 지정 디렉터리로 변경 |
| `--output-inventory` | 입력 파일 옆 hosts.team.yml | 생성할 접속용 인벤토리 |
| `--ssh-config` | `~/.ssh/project-access/config` | 생성할 프로젝트 전용 SSH 설정 |
| `--check-host` | 배스천 외 호스트명 중 이름순 첫 번째 | Ansible ping으로 검사할 실제 호스트 이름 |
| `--help` | 선택 | 사용법 출력. AWS·SSH를 실행하지 않음 |

프로필 이름은 영문·숫자와 `_.@+-`를 사용한다. 경로의 공백은 인수를 따옴표로 감싸 전달한다. `--key-directory`를 지정하지 않으면 기존 절대 경로 또는 입력 인벤토리 디렉터리 기준 상대 경로를 사용한다. `~`와 생성 인벤토리의 `{{ lookup('env', 'HOME') }}`는 현재 사용자 홈으로 바꾸며 다른 Jinja 연결 변수는 지원하지 않는다.

## 실행

Ansible 가상환경을 활성화한 후 프로젝트의 platform 폴더에서 실행한다. AWS 프로필·Endpoint ID·키 파일은 현재 환경에 맞게 준비한다.

```bash
# 기존 인벤토리를 읽고 현재 PC에서 사용할 접속 설정을 생성·검사한다.
bash scripts/setup-team-access.sh \
  --inventory inventory/hosts.current.yml \
  --aws-profile team-access \
  --region ap-northeast-2 \
  --endpoint-id eice-실제EndpointID \
  --key-directory "$HOME/.ssh/project-key" \
  --check-host spark-3
```

예시 Endpoint ID는 실제 값으로 바꾼다. 프로필은 현재 사용자에게 허용된 계정을 사용한다. 스크립트와 프로젝트 설정은 스크립트 위치에서 찾으므로 다른 디렉터리에서 절대 경로로 실행해도 된다.

## 실행 흐름과 생성 파일

1. 옵션·도구·정적 인벤토리 구조·호스트·키 경로를 확인한다. 개인키 본문은 읽거나 복사하지 않는다.
2. AWS CLI v2, AWS 인증과 지정 Endpoint 상태를 확인한다. 확인 실패 시 설정을 생성하지 않는다.
3. 키 파일 권한을 600으로 제한한다. Windows 마운트 등에서 제한이 적용되지 않으면 중단하고 WSL 홈에 키를 배치하도록 안내한다.
4. 두 생성 대상의 소유 표시를 확인하고 SSH 설정과 인벤토리를 쓴다. 각 파일은 임시 파일을 만든 뒤 원자적으로 교체하며 두 파일 전체가 하나의 트랜잭션은 아니다.
5. 배스천에 `ssh ... true`로 접속한 뒤 지정 프라이빗 서버에 Ansible ping을 실행한다. 실패하면 완료로 보고하지 않는다.

| 파일 | 내용 |
| --- | --- |
| 프로젝트 전용 SSH 설정 | 배스천은 `aws ec2-instance-connect open-tunnel` ProxyCommand, 나머지는 별도 배스천 키를 사용하는 `ssh -W` ProxyCommand |
| 접속용 인벤토리 | 원본 역할 그룹·사설 IP·프록시 변수 유지, 각 호스트의 SSH 별칭·사용자·키·전용 설정 파일 인자와 관리 표시 추가 |

입력 인벤토리와 생성 경로를 같은 파일로 지정할 수 없다. 같은 호스트가 여러 그룹에 나타나면 각 선언에 접속 변수를 반영한다. 충돌하는 명시적 호스트 변수는 임의로 선택하지 않고 거부한다. 연결용 그룹 변수는 정적 값이어야 하며 복잡한 그룹 우선순위·동적 인벤토리·외부 변수 해석을 대신하지 않는다.

기존 사용자 SSH 설정을 덮어쓰지 않는다. 생성 SSH 파일의 관리 주석, 생성 인벤토리의 `project_access_managed_by` 표시가 있는 파일만 재실행 때 갱신한다. 기존 `inventory/hosts.current.yml`·`group_vars`·[Ansible 설정 파일](../../../ansible.cfg)·AWS 인증 파일은 변경하지 않는다. 복수 환경은 `--ssh-config`와 `--output-inventory`를 각각 다른 경로로 지정한다.

## 준비 후 사용과 재실행

완료 시 현재 PC에서 사용할 실제 명령과 경로를 출력한다. 기본 경로로 생성한 경우 다음처럼 사용한다.

```bash
# SSH는 프로젝트 전용 설정 파일을 지정한다.
ssh -F "$HOME/.ssh/project-access/config" spark-3

# Ansible은 원본 대신 생성한 접속용 인벤토리를 지정한다.
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
ansible -i inventory/hosts.team.yml spark-3 -m ansible.builtin.ping
```

인프라 재생성으로 주소가 바뀌면 관리자가 Inventory를 갱신하고 사용자는 새 원본 인벤토리로 이 스크립트를 다시 실행한다. 생성된 `inventory/hosts.team.yml` 자체를 입력으로 지정하지 않는다. 개인키 파일명이 바뀌면 원본의 키 경로도 새 파일명에 맞춰야 한다.

Endpoint 터널은 연결당 최대 3,600초이며 긴 SSH·Ansible 작업은 연결 종료와 재연결을 고려해야 한다. 기존 AWS 로그인 환경과 SSH agent를 유지해야 한다. 기존 인벤토리 디렉터리의 group_vars/Vault는 Ansible 검사에서 평소처럼 로드되므로 Vault가 있다면 사용자 환경에서 비밀번호를 준비한다. 스크립트의 정적 인벤토리 변환은 Vault를 읽거나 펼치지 않는다.

Endpoint 조회 성공만으로 `OpenTunnel`·서버 키·프라이빗 서버 경로가 검증된 것은 아니다. 마지막 실제 SSH·ping 성공까지 확인한다. 설정 생성 후 접속이 실패하면 생성 파일은 남으며 입력·인증·네트워크를 고친 뒤 재실행할 수 있다. AWS나 서버 설정을 복원·변경하는 작업은 없다.

## 구조와 검증 범위

Bash 진입부와 내장 Python 처리부로 구성한다. main은 입력부터 검사까지, collect는 중첩 그룹과 중복 호스트를 수집한다. run은 외부 명령 실행, ssh_value는 SSH 설정값 인용, managed_write는 관리 파일 교체, fail은 오류 처리를 맡는다. Bash 안의 Python은 routing-doc-sync의 파일 기반 AST 분석 대상이 아니므로 별도 실행 검사로 확인한다.

2026-10-10 로컬 검증에서는 WSL Bash 문법, 도움말, 임시 정적 인벤토리와 가짜 AWS·SSH·Ansible 명령을 사용한 17개 시나리오가 통과했다. 원본 보존·재실행·공백과 `%` 경로·HOME 치환·중복 그룹·사용자 파일 보호·AWS 인증 및 Endpoint 상태 실패·SSH/Ansible 실패·AWS CLI v1 거부를 검사했다. 실제 OpenSSH의 설정 파싱과 ProxyCommand 인수 전달, Ansible 인벤토리 파싱도 임시 데이터로 확인했다. 실제 AWS 호출·EC2 접속·서버 변경은 수행하지 않았다.

AWS CLI 터널 인수는 [공식 open-tunnel 문서](https://docs.aws.amazon.com/cli/latest/reference/ec2-instance-connect/open-tunnel.html)를 기준으로 한다. 실제 IAM·보안그룹·EC2 접속 검증은 준비된 AWS 환경에서 운영자가 수행해야 한다.

추가로 실제 OpenSSH가 가짜 터널·경유 명령에 전달하는 인수를 별도 2개 시나리오로 검사했으며 최종 모의 검증 결과는 19개 통과다. 공백·퍼센트 경로와 사설 IP·SSH 포트가 올바르게 전달되는지 확인했다. 실제 운영 환경의 성공을 이 결과로 대신하지 않는다.
