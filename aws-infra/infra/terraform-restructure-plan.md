# 공통 Terraform 구조와 개편 이력

기준: 2026-10-10의 구현. 이 문서는 2026-10-09 최초 개편안을 이후 Bastion 분리·HTTP ALB·구성별 배포·Proxy·전체 삭제·Spark 범위 변경까지 반영해 설명한다. 실제 AWS 이관·배포 완료 기록과 구분한다. 코드 위치는 [라우팅](../docs/infra-routing/ROUTING-README.md), 운영 명령은 [실행 안내](README.md)와 [배포 절차](../docs/deployment-runbook.md)에 있다.

## 입력과 상태 소유권

| stack | 대상 | 책임 |
| --- | --- | --- |
| foundation | account1~5 각각 | VPC·서브넷·라우팅 테이블·IGW/NAT·역할 SG |
| connectivity | shared | 설정한 계정 쌍 Peering·상대 CIDR 경로 |
| workload | account1~5 각각 | SG 규칙·서비스 EC2·키페어·데이터 EBS·Front EIP·해당 계정 ALB |
| bastion | account1 | 선택 Bastion EC2·루트 디스크·전용 키페어 |

기본 topology에는 서비스 15대와 Bastion 정의가 있다. workload는 role=bastion을 제외한다. 광고는 account1 Private C다. 공통 model이 계정·AZ·역할·연결을 검사하고, security-rules가 포트 또는 선택적 끝 포트 범위를 만든다. 현재 데이터 EBS의 prevent_destroy는 false다.

상태는 계정별 foundation/workload 10개, shared/connectivity 1개와 선택 Bastion 1개, 총 12개 경로다. 원격 상태는 S3 버전 관리와 use_lockfile을 사용한다. 상태 자체·자원·라우팅을 다른 stack에 중복 선언하지 않는다.

## 네트워크와 서비스 포트

서울 리전의 물리 AZ ID apne2-az1·apne2-az3를 논리 A/C로 쓴다. account1만 Public A/C·IGW·ALB가 있고 기본 NAT는 0개다. 중앙 Forward Proxy를 사용하며 Private 기본 라우트는 Bastion에 지정하지 않는다. 모든 VPC 쌍의 직접 Peering 10개와 각 상대 CIDR 경로를 만든다.

ALB는 HTTP 80이고 /static/* → Front:80, /ads/* → ad:8000, 기본 → game:8000이다. certificate_arn은 공통 입력에 남아 있지만 ALB 모듈에 전달하지 않는다. HTTPS listener·자동 TLS는 없다. 서비스 콘솔 SSH는 리전별 IPv4 EC2 Instance Connect 접두사 목록의 22 규칙이며 Private 접속 경로를 새로 만드는 것은 아니다.

Spark Worker 7100·Master UI 8080, 작업 Driver 7078–7094·BlockManager 7079–7095, ZooKeeper 2181·2888·3888을 Spark SG 사이에 허용한다. port_end가 없으면 단일 포트이고 같은 SG 쌍·시작 포트는 최대 끝 값으로 합친다. [모듈·stack 테스트](../docs/infra-routing/tests/README.md#spark-포트-범위)와 [플랫폼 포트](../../platform/docs/platform-routing/roles/spark/README.md#프라이빗-서버의-통신-포트)를 함께 본다.

## 실행기와 비용별 구성

infra.ps1은 Validate/Test/Plan/Apply/Output, 구성 선택과 저장 계획 검사를 담당한다. 온라인 동작은 실제 계정·backend 인증과 S3 버전 관리를 확인한다. 새 Plan에서 이전 계획을 무효화하고 성공한 Apply에서 계획과 manifest를 제거한다. 설정·코드·공개키·대상이 바뀌면 새 Plan이 필요하다.

deploy.ps1 NewProfile은 topology·traffic·platform.json을 로컬 복사하고 노드 크기·대수·계정 배치를 선택하게 한다. 모든 프로필은 동일 원격 상태를 바꾸며 경로 해시로 로컬 캐시만 구분한다. Deploy는 foundation → connectivity → workload → bastion의 단계별 검토·적용 후 Inventory·Proxy를 수행한다. 자동 가격 비교·DB 설치·클러스터 데이터 이전은 포함하지 않는다.

Inventory는 소유 EC2의 현재 주소·태그·상태·사양을 확인하고, 목적지 계정 키와 Bastion 키를 구분해 플랫폼 인벤토리를 만든다. Proxy는 Squid·ACL·Ubuntu HTTPS 저장소·APT·다운로드를 준비한다. 서비스는 WSL의 Ansible 역할로 별도 설치한다. backend bucket·AMI·공개키는 현재 기본 파일에 채워져 있으나 실제 유효성은 배포 시 확인한다.

## 설치·변경·삭제 경계

Terraform은 EC2·EBS 연결까지다. [bootstrap](bootstrap/README.md)과 플랫폼이 프로그램 설치 경계를 안내한다. 데이터 포맷·마운트·백업·이전은 자동화하지 않았다. 현재 EBS 보호가 꺼져 있으므로 노드 이름·계정·AZ·디스크 변경의 삭제·교체를 확인한다.

bastion.ps1은 별도 상태의 생성·삭제와 중지·시작·재시작·현재 IP를 관리한다. 자동 공인 IP이며 EIP를 만들지 않는다. destroy-all.ps1은 상태 범위의 삭제 Plan을 모두 준비한 뒤 검토한 실행 ID로 Bastion → workload 5개 → connectivity → foundation 5개를 적용한다. 데이터 삭제 선택이 필요하고 상태 밖 자원·S3 상태 버킷을 모두 지우는 기능은 아니다.

## 이전 자료와 검증

최초 개편 기록상 대체된 scripts/account1·상위 config·terraform 소스는 C:\third_project\trash\aws-infra-legacy-20261009에 보관했다. 현재 실행기는 그 파일을 읽지 않는다. 과거 Account 1의 10.11.0.0/16와 로컬 상태가 새 10.10.0.0/16·S3 상태에 자동 이관되지 않는다. 상태 연결·import·데이터 이전은 별도 작업이다.

[테스트 안내](tests/README.md)는 모의 CLI·mock provider 검사와 실제 배포를 구분한다. 기존 workload 테스트에 남은 노드 수·SG ID 기대값 차이를 새 Spark·콘솔 SSH 테스트가 해결한 것으로 기록하지 않는다. 이번 문서 작업에서는 테스트·AWS·설치 명령을 재실행하지 않았다. 비용 자료는 [docs/costs](../docs/costs/README.md)로 옮겨졌으며 이전 ../costs 경로는 사용하지 않는다.
