# infra/scripts/deploy.ps1

[탐색 시작점](../ROUTING-README.md) · [원본](../../../infra/scripts/deploy.ps1) · [실행 안내](../../../infra/scripts/README.md)

## 역할

비용별 구성 폴더를 선택해 기존 infra.ps1을 실행하고, Terraform이 관리하는 EC2의 현재 주소로 플랫폼 인벤토리를 만든다. Deploy는 단계별 계획 검토·적용 후 WSL의 프록시 준비까지 연결한다. 자동 가격 조회나 예산에 따른 사양 추천 기능은 없다.

Windows PowerShell 5.1에서 한글 문자열을 올바르게 읽도록 소스를 UTF-8 BOM으로 저장한다. BOM 없는 UTF-8을 읽는 방식이 PowerShell 7과 다르므로 5.1 호환 문법 검사는 해당 실행 파일의 파서로 수행한다.

## 입력

ProfileDirectory는 필수이며 호출한 PowerShell 디렉터리 기준의 상대 경로도 받는다.

| 구성 파일 | 내용 |
| --- | --- |
| topology.tfvars.json | nodes의 account·instance_type·AZ·디스크·노드 수와 계정/네트워크 설정 |
| traffic.tfvars.json | 역할 간 연결·외부 허용 범위·프록시 포트 |
| platform.json | inventory_name, ssh_user, 계정별 ssh_keys, role_groups, wsl_distribution, ansible_venv |

NewProfile은 현재 infra/config의 topology·traffic을 복사하고 플랫폼 설정을 생성한다. 초기 사양·노드 수를 자동으로 낮추지 않는다. 기존 세 파일 중 하나라도 있으면 덮어쓰지 않는다. 기본 개인키 경로는 WSL 사용자의 ~/.ssh/project-key이며 platform.json에서 바꾼다. 개인키 내용은 읽거나 복사하지 않는다.

## Action과 실행 경계

| Action | 동작 |
| --- | --- |
| NewProfile | 구성 파일을 로컬에 생성한다. AWS를 호출하지 않는다. |
| Plan | Stage의 계정별 저장 계획을 만든다. Account 기본 all, connectivity는 shared, bastion은 구성의 배스천 계정이다. |
| Apply | 같은 구성·계정·단계의 저장 Plan을 적용한다. 이 동작 자체는 대화형 확인을 추가하지 않는다. |
| Deploy | foundation → connectivity → workload → bastion 순서로 각 단계의 전체 Plan을 만들고 APPLY 입력을 받아 적용한다. 이어 Inventory·Proxy를 실행한다. |
| Inventory | 원격 Terraform 출력의 인스턴스 ID로 AWS에서 현재 IP를 조회한 뒤 인벤토리를 생성한다. |
| Proxy | 이미 생성한 인벤토리를 WSL에 넘겨 배스천 Squid·방화벽과 대상 서버의 프록시를 준비한다. Limit 기본 all이다. |

하위 단계가 상위 단계의 원격 상태를 읽으므로 초기 배포의 모든 Plan을 한꺼번에 만들지 않는다. 중단·실패 시 앞 단계에서 적용한 자원은 남는다. 전체 삭제 실행기를 자동 호출하지 않는다.

## 상태와 비용 구성 전환

모든 구성은 기존 infra/config/backend.json의 동일한 원격 상태를 사용한다. 구성을 선택하면 현재 환경을 그 구성으로 변경한다. 구성별 별도 환경이나 복제 배포를 만들지 않는다.

저장 Plan·출력 캐시는 Get-InfraWorkPath가 구성의 절대 경로 해시로 분리한다. 선택한 topology·traffic 내용과 경로도 fingerprint에 들어가며 변경 후 Apply는 새 Plan을 요구한다. 공개키 상대 경로 기준은 기존 infra다.

현재 Terraform 제약인 account1~5, 서울 리전의 두 AZ, account1의 bastion 한 대는 유지한다. 서비스 EC2의 크기·대수·계정 배치는 nodes에서 바꾼다. 서비스 역할 자체를 없애면 traffic의 연결과 ALB 조건도 함께 맞춰야 한다.

계정/AZ 이동·노드 삭제는 데이터 이전이 아니다. deploy.ps1은 데이터 EBS의 prevent_destroy 값을 변경하거나 우회하지 않는다. 현재 [compute 모듈](../terraform/README.md#compute)의 값은 false이므로 배치 변경 시 데이터 볼륨 삭제·교체 계획도 확인해야 한다. 실행 중 역할을 다른 계정으로 옮겨 기존 SG가 제거되는 경우에는 기존 EC2·SG 참조 정리와 데이터 이전을 별도 단계로 계획해야 한다. Deploy 한 번으로 모든 기존 클러스터를 무중단 이전하는 기능은 아니다.

## 인벤토리와 SSH 연결

workload 출력과 선택한 노드 목록이 일치하는지 검사하고, 실제 AWS 소유 계정·Project/Node/Role 태그·실행 상태·사양을 확인한다. 조건에 맞지 않으면 파일을 쓰지 않는다. 계정에 서비스 노드가 없어도 처리한다.

계정 그룹과 역할 그룹을 함께 생성하고 mongo는 기본적으로 mongodb에 대응시킨다. role_groups는 사용자가 수정할 수 있다. bastion 노드는 Ansible에서 bastion-01이라는 내부 호스트명으로 표현한다. 중복 호스트 이름은 거부한다.

대상 서버는 자신의 계정 키를 사용하고 ProxyCommand는 별도로 배스천 계정 키를 사용한다. 개인키를 배스천으로 복사하거나 모든 계정 키를 배스천에 등록할 필요가 없다. 생성 파일에는 키 경로만 기록한다.

CIDR·프록시 포트·키·접속 주소는 host 변수로 기록해 플랫폼의 기본 group_vars보다 우선한다. 출력은 aws-platform/platform/inventory/hosts.구성이름.yml이며 기존 hosts.yml을 덮어쓰지 않는다. JSON 형식으로 기록한 YAML 인벤토리다.

## 프록시 실행

platform.json의 WSL 배포판과 기존 Ansible 가상환경을 사용한다. wslpath로 경로를 변환하고 bash 스크립트에 인수로 전달한다. AWS 로그인, S3 상태 버킷, WSL·Ansible 설치, Linux 개인키 파일은 미리 준비해야 한다.

Get-Command가 System32와 WindowsApps 등 여러 WSL 실행 경로를 반환해도 검색 순서의 첫 실행 파일 하나만 선택한다. 경로 배열 전체를 호출 연산자에 넘겨 여러 경로가 하나의 명령 이름으로 합쳐지는 오류를 방지한다.

연결 대상은 [플랫폼 실행 스크립트](../../../../aws-platform/platform/scripts/setup-proxy.sh)와 [배스천 초기화](../../../../aws-platform/platform/bootstrap-proxy.yml)다. 프록시 준비에서는 Kafka·Spark·DB 애플리케이션 설치를 실행하지 않는다.
