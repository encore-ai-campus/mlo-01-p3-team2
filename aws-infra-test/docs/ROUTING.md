# 테스트 환경 코드 지도

이 폴더는 기존 aws-infra의 현재 코드를 선택 복사한 독립 구성이다. 원본 파일별 SHA256은 source-snapshot.json에 기록했다. 캐시·상태·키·기존 변경을 복사한 Git 이력은 포함하지 않는다.

| 위치 | 역할 |
|---|---|
| infra/config/topology.tfvars.json | 5계정·A·small·Front 한 대·20GiB·ALB false |
| infra/config/traffic.tfvars.json | 허용 CIDR·Front→game/ad·SSH·Proxy·클러스터 포트 |
| infra/config/backend.json | 테스트 전용 S3 prefix |
| infra/config/platform.json | WSL·Ansible·계정별 개인키 경로 |
| infra/scripts/prepare.ps1 | 공개키만 검사·복사 |
| infra/scripts/deploy.ps1 | Deploy/All/Install/Front/Inventory/Proxy 및 단계별 Plan/Apply |
| infra/scripts/infra.ps1 | 계정·저장 Plan·해시·상태 확인 후 Terraform 실행 |
| infra/scripts/bastion.ps1 | 전용 Bastion 생성·삭제·시작·중지 |
| infra/scripts/destroy-all.ps1 | 12개 상태의 순서 있는 삭제와 결과 검사 |
| infra/scripts/lib/test-isolation.ps1 | 기존 환경 상태·프로젝트 이름 사용 차단 |
| infra/scripts/lib/infra-common.ps1 | 입력·CIDR·fingerprint·Bastion 범위 검사 |
| infra/scripts/lib/infra-destroy.ps1 | 삭제 순서·자원 주소·기존 태그 검사 |
| infra/terraform/stacks | foundation/connectivity/workload/bastion 네 상태 단위 |
| infra/terraform/modules/network | A 서브넷·라우팅·IGW |
| infra/terraform/modules/model | 단일 AZ·역할·연결 입력 검증 |
| infra/terraform/modules/compute | 서비스 EC2·EBS·Front EIP |
| infra/terraform/modules/bastion | 자동 공인 IP·OS 삭제·EIP 없는 Bastion |
| infra/terraform/modules/alb | 원본 참조 모듈. enabled=false와 실행기 검사로 생성하지 않음 |
| infra/bootstrap/run.sh | 테스트 인벤토리만 허용하고 Ansible 실행 |
| infra/bootstrap/front.yml, templates/front.conf.j2 | Nginx·정적 파일·HTTP/WebSocket 분기 |
| infra/bootstrap/clusters.yml, vars/small.yml | 데이터 마운트 및 기존 platform 역할에 small 설정 전달 |
| infra/bootstrap/mount-data.sh | EBS ID·기존 파일 검사·ext4·fstab UUID 마운트 |
| infra/bootstrap/inventory/group_vars/all/proxy.yml | 명시적 프록시와 내부 IP NO_PROXY |
| infra/tests/check.ps1 | PowerShell·삭제 보호 검사 및 Terraform 검증 실행 |
| infra/terraform/stacks/*/tests | 실제 계정 대신 mock provider로 단일 AZ·small·분리 검증 |

기존 ../aws-platform/platform 역할은 읽어서 재사용한다. 게임·광고·Consumer 앱의 배포와 HTTPS 구성은 포함하지 않는다.
