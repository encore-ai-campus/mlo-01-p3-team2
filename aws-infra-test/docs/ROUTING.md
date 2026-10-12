# 테스트 환경 코드 지도

이 폴더는 기존 aws-infra의 현재 코드를 선택 복사한 독립 구성이다. 원본 파일별 SHA256은 source-snapshot.json에 기록했다. 캐시·상태·키·기존 변경을 복사한 Git 이력은 포함하지 않는다.

| 위치 | 역할 |
|---|---|
| infra/config/topology.tfvars.json | 5계정·A·small·Front 한 대·20GiB·ALB false |
| infra/config/traffic.tfvars.json | admin_public_cidrs·game_client_cidrs·public_http_cidrs, Front→game/ad·SSH·Proxy·클러스터 포트 |
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

## 2026-10-12 학원 접속 범위

- 학원 공인 IP는 `222.112.208.69/32`다. 앞서 전달된 `.72`는 사용하지 않는다.
- `admin_public_cidrs`: 학원 IP. Bastion SSH 22 및 Private 서버의 역할별 SG에 학원 IP의 SSH 22를 허용한다.
- `public_http_cidrs`: `0.0.0.0/0`. Public Front의 HTTP 80만 전체 공개한다. 필드가 없는 이전 프로필은 game_client_cidrs로 동작한다.
- `game_client_cidrs`: 학원 IP. 이 테스트 구성에는 edge·HTTPS가 없으며 public_http_cidrs가 없는 이전 입력의 HTTP 대체값으로 사용한다.
- Bastion의 EC2 Instance Connect 콘솔 SSH 출처 규칙은 생성하지 않는다. 기존 규칙이 있다면 다음 workload Plan에 해당 규칙 삭제가 표시된다. 서비스 서버의 기존 콘솔 SSH 규칙은 유지한다.
- Private SSH CIDR 규칙은 인터넷 경로를 만들지 않는다. Bastion 경유 시 목적 서버에는 Bastion 사설 IP가 출처로 보이므로 기존 Bastion→서버 SG 규칙도 유지한다. OS 방화벽·접속 경로의 실제 성공은 별도다.
- 기존 저장 Plan은 다시 만들어야 한다. 코드만 수정했으며 AWS Apply는 실행하지 않았다.

## 학원 접속 규칙의 수정 경로

| 변경 목적 | 구현 위치 |
| --- | --- |
| 학원 IP·HTTP 허용 범위 | [traffic.tfvars.json](../infra/config/traffic.tfvars.json) |
| 선택적 public_http_cidrs 타입·CIDR 검증 | [model/main.tf](../infra/terraform/modules/model/main.tf), [infra-common.ps1](../infra/scripts/lib/infra-common.ps1) |
| Private 역할별 SSH·Front 80·Bastion 콘솔 규칙 제외 | [workload/main.tf](../infra/terraform/stacks/workload/main.tf)의 private_role_sg_ids, private_admin_ingress, front_ingress, bastion_console_ssh |
| HTTP 허용 CIDR을 Nginx에 전달 | [deploy.ps1](../infra/scripts/deploy.ps1)의 hostVars.test_client_cidrs → [front.conf.j2](../infra/bootstrap/templates/front.conf.j2) |
| 계정별 정책 모의 검사 | [school-access.tftest.hcl](../infra/terraform/stacks/workload/tests/school-access.tftest.hcl), [test-environment.tftest.hcl](../infra/terraform/stacks/workload/tests/test-environment.tftest.hcl) |

deploy.ps1은 public_http_cidrs가 있으면 그 목록을, 없으면 game_client_cidrs를 test_client_cidrs에 기록한다. 설정 변경 후 Terraform Plan·검토·Apply와 별도로 Inventory를 갱신하고 Front 작업을 실행해야 원격 Nginx 허용 목록도 바뀐다. 이번 작업에서는 AWS Apply나 원격 Front 작업을 실행하지 않았다.

모의 테스트 실행 결과와 미검증 범위는 [검증 기록](verification.md)을 참고한다.
