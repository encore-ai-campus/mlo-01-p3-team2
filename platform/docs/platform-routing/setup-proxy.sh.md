# setup-proxy.sh

[탐색 시작점](ROUTING-README.md) · [원본](../../setup-proxy.sh) · [배스천 설치](bootstrap-proxy.yml.md)

## 역할과 입력

WSL 또는 Linux의 Ansible 컨트롤 노드에서 프록시 준비 명령을 순서대로 실행한다. 계정·서비스 서버 이름·IP·개인키 경로를 스크립트에 고정하지 않는다.

| 옵션 | 의미 |
| --- | --- |
| --inventory | 실제 인벤토리 파일. 필수이며 상대 경로는 호출한 작업 디렉터리 기준이다. |
| --limit | 준비·검사할 Ansible 호스트 패턴. 기본 all이며 account1 등 계정 그룹도 선택할 수 있다. |
| --venv | 사용할 Ansible 가상환경. 생략하면 현재 PATH의 Ansible을 쓴다. ~/ 경로를 지원한다. |
| --help | 실행 방법만 출력한다. |

배스천은 limit에 포함되지 않아도 설치·APT·방화벽을 준비한다. 따라서 일부 클라이언트만 선택한 실행도 공용 배스천 설정에 영향을 준다. 선택한 인벤토리 전체가 한 배포 구성을 나타내야 하며 일부 호스트만 담은 파일로 공용 프록시 범위를 축소하지 않는다.

인벤토리는 [프록시 변수](inventory/group_vars/all/proxy.yml.md)를 읽고 proxy_enabled=true를 지정해야 한다. bootstrap-proxy.yml은 비활성 입력을 오류로 처리한다. --limit은 배스천의 ACL 범위를 결정하지 않으며, ACL은 인벤토리의 proxy_client_cidrs를 따른다.

## 흐름

인벤토리·대상 존재 확인 → 세 playbook 문법 검사 → SSH와 Python 확인 → bootstrap-proxy로 Squid 준비 → 배스천 APT 준비 → 배스천 방화벽 → limit 대상 APT 준비 → proxy_verify.

방화벽을 클라이언트 준비보다 먼저 적용해 프록시 포트나 VPC CIDR 변경 시 새 연결을 허용한다. ANSIBLE_CONFIG는 스크립트 옆 ansible.cfg로 지정한다. 명령이 실패하면 이후 단계를 중단하며 앞 단계의 성공한 변경을 일괄 취소하지 않는다.

기존 [prepare-proxy](prepare-proxy.yml.md)와 site.yml의 firewall 태그를 재사용한다. 서비스 클러스터 역할은 실행하지 않는다. Windows의 [배포 실행기](../../../aws-infra/infra/scripts/deploy.ps1)는 WSL을 통해 이 스크립트를 호출한다.

## 코드 위치와 단계별 연결

아래 행은 현재 원본 setup-proxy.sh 기준이다. 문법 검사는 세 playbook 전체를 대상으로 하며, 실제 준비 단계의 대상과 태그는 별도로 제한한다.

| 원본 행 | 코드 위치 | 책임과 연결 |
| --- | --- | --- |
| 8 | 옵션 처리 루프 | --inventory·--limit·--venv를 읽는다. 값 누락·알 수 없는 옵션은 종료 코드 2이며 -h/--help는 0으로 종료한다. |
| 30 | limit 입력 검사 | -로 시작하는 호스트 패턴을 종료 코드 2로 거부한다. |
| 34 | 가상환경 활성화 | --venv가 있으면 bin/activate를 확인하고 불러온다. 상대 경로는 호출한 작업 디렉터리 기준이며 ~/를 확장한다. 없으면 종료 코드 1이다. |
| 42 | 인벤토리 파일 검사 | 인벤토리 누락·파일 부재는 종료 코드 2다. |
| 46 | Ansible 실행 파일 검사 | ansible·ansible-playbook이 현재 PATH에 없으면 종료 코드 1이다. |
| 54 | 실행 경로 고정 | 인벤토리를 절대 경로로 바꾼 뒤 platform 디렉터리로 이동하고 ANSIBLE_CONFIG를 지정한다. |
| 59 | 실패 알림 | ERR 트랩으로 현재 단계와 종료 코드를 출력한다. 명시적인 exit를 사용하는 입력 오류는 각 오류 메시지로 종료한다. |
| 62 | 대상 존재 검사 | bastion과 limit 패턴을 --list-hosts로 확인한다. 패턴 불일치나 대상 0대는 실패 처리한다. |
| 73 | 1/6 문법 검사 | [bootstrap-proxy](bootstrap-proxy.yml.md), prepare-proxy, [site](site.yml.md)를 차례로 --syntax-check한다. |
| 79, 80, 81 | 2/6 연결 확인 | bastion·limit에 wait_for_connection(timeout=300)을 실행하고 limit 대상에 ping을 실행한다. |
| 85, 86 | 3/6 배스천 준비 | bootstrap-proxy로 Squid를 준비한 뒤 prepare-proxy --limit bastion으로 직접 APT 연결을 준비한다. |
| 90 | 4/6 배스천 방화벽 | site --tags firewall --limit bastion으로 [프록시 허용 규칙](roles/firewall/templates/infra-fw.nft.j2.md)을 적용한다. |
| 94 | 5/6 선택 대상 준비 | prepare-proxy --limit으로 대상의 저장소·APT·프록시를 준비하고 접속을 검사한다. |
| 98 | 6/6 접속 재검사 | prepare-proxy --tags proxy_verify --limit으로 HTTPS와 파일 다운로드를 재검사한다. |

all 또는 bastion을 포함하는 패턴을 선택하면 5/6·6/6에도 배스천이 포함된다. 전체 실행에 대한 일괄 복구는 없으며 Squid 설정 복구는 bootstrap-proxy의 설정 적용 블록에 한정된다.

## 검증 범위

실제 Bash·Ansible·EC2 검증은 운영자가 수행한다. PowerShell 배포 연결과 인벤토리 생성의 로컬 검사 결과는 [검증 기록](verification.md)에 구분해 기록한다.
