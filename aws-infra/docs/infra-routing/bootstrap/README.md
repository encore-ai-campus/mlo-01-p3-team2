# EC2 생성 이후의 설치 경계

[탐색 시작점](../ROUTING-README.md) · [현재 bootstrap 안내](../../../infra/bootstrap/bootstrap.md) · [compute 모듈](../terraform/README.md#compute)

현재 infra/bootstrap에는 안내 Markdown만 있다. 프로그램 설치는 별도 [플랫폼 역할](../../../../aws-platform/platform/docs/platform-routing/roles/README.md)이 담당한다. 아래 표는 Terraform이 만드는 자원과 플랫폼이 적용하는 설치 작업을 구분한다.

| 항목 | Terraform과 플랫폼의 처리 경계 |
| --- | --- |
| 서비스 EC2·EBS·SG 규칙·키페어·EIP | workload의 Terraform 모듈이 생성. SG 자체는 foundation 소유 |
| Bastion EC2·OS 디스크·전용 키페어·자동 공인 IP | 별도 bastion 단계. EIP 없음 |
| 노드 메타데이터 | compute·bastion의 user_data가 /etc/aws-infra/node.json에 name·role·account 기록 |
| EBS 포맷·마운트·파일시스템 증설 | 자동화 없음 |
| MySQL·MongoDB·Kafka·ZooKeeper·Spark 설치 | Terraform은 설치하지 않음. 플랫폼 site.yml의 역할별 설치·검증 사용. 현재 MySQL은 3~9대 Cluster가 필요하며 기본 인프라는 세 대. mysql-3 포함 인벤토리·Proxy·데이터 마운트·OS 방화벽 확인 후 설치 |
| MySQL Router | 플랫폼 backend 역할이 game·Spark·선택 backend에 로컬 Router 설치·bootstrap·Primary 연결 검사. 별도 Router EC2 없음 |
| Proxy 패키지·접근 규칙·클라이언트 준비 | deploy.ps1 Proxy가 [플랫폼 프록시 실행기](../../../../aws-platform/platform/docs/platform-routing/scripts/setup-proxy.sh.md)를 연결. Squid 설치·ACL·수신 포트 → Bastion APT·방화벽 → 대상 서버 APT·다운로드 검사 |
| Django·Nginx·flatten-1 Consumer 프로그램 | 해당 앱·평탄화 프로그램의 설치 역할 없음. 별도 배포 |
| Front A·C 정적 파일 배포 | 자동화 없음. 기본 설정의 ALB가 비활성화돼 외부 웹 전달 경로도 없음 |
| DB 복제·서비스 검증 / 업무 처리 경로 | 플랫폼 DB·Kafka·Spark 역할의 구성·검증과 업무 Consumer·Spark 잡·checkpoint·Kappa 처리 경로를 구분. 업무 처리 배포는 별도 |
| OS 사용자·sudo·SSH·시간원 | 보안그룹으로 설정하지 않음. 플랫폼 common 역할이 공통 보안·사용자·sudo·시간 동기화 처리 |
| Bastion 생성·삭제·상태·전원 | [bastion.ps1](../scripts/bastion.ps1.md)의 PlanCreate/Create·PlanDelete/Delete·Status/Output·Stop/Start/Restart |
| EC2 전체 예약 기동·종료·백업·복구·데이터 이전 | 자동화 없음 |

서비스 주소·디스크 ID는 [workload 출력](../terraform/stacks/workload.md#출력), Bastion 주소·Proxy endpoint는 [Bastion 출력](../terraform/stacks/bastion.md#출력)에서 찾는다. 출력 값만으로 클러스터가 설치되었거나 데이터가 별도 EBS에 저장된다고 판단하지 않는다.

현재 proxy 모드는 내부 EC2가 Bastion의 사설 주소·3128 포트에 접속하도록 SG를 허용한다. Terraform 적용 뒤 Inventory·Proxy를 실행해야 플랫폼 인벤토리와 Squid·ACL·APT·다운로드 환경을 준비한다. 수동 install-squid.sh는 패키지만 설치하며 전체 프록시 준비와 범위가 다르다. Bastion 재생성 후 현재 주소로 인벤토리를 갱신하고 프록시를 다시 준비한다. 추가 팀원 공개키를 사용하는 접속 구성은 재등록도 별도로 확인한다. Private 기본 라우트를 Bastion으로 연결하는 NAT 구현은 없다.

ALB를 선택적으로 다시 활성화해 이전 HTTP 경로를 사용할 때는 Front 두 대가 동일한 정적 파일을 HTTP 80에서 제공하고, game-server와 ad-server가 각 EC2의 HTTP 8000에서 요청을 처리해야 한다. 광고 Django는 사용자가 해당 서버에서 `python manage.py runserver 0.0.0.0:8000`으로 실행하는 구성이다. ALB가 /ads/*의 접두사를 제거하지 않으므로 광고 앱이 /ads/와 필요한 하위 경로를 처리해야 한다. 현재 코드가 프로그램 설치·파일 복사·Django 허용 호스트 설정을 수행하는 것은 아니다. 대상 그룹의 health check 경로 /에 응답하도록 서버 설정도 별도로 준비한다. 광고 앱의 실제 URL·ALLOWED_HOSTS·헬스 체크 응답은 확인하지 못했다.


## 광고 서버 생성 위치

기본 topology의 nodes.ad-server.az는 a이며 account1 Private A(apne2-az1)에 새로 생성한다. 기존 프로필은 자동 갱신되지 않으므로 선택한 프로필의 동일 항목을 확인한다. profiles/current도 로컬에서 A로 변경했지만 Git 제외 대상이다. ALB 설정·클러스터 노드 수는 이 AZ 변경에 포함하지 않는다. 사용자는 전체 삭제 명령 후 VPC 등 자원 삭제를 확인했다고 알렸으며, 이번 작업에서 실제 AWS 상태를 조회하거나 재생성하지 않았다.

## 평탄화 Consumer 변경 연결

flatten-1은 account2 Private A의 t3a.medium·OS 20GiB·공인 IP 및 별도 데이터 디스크 없음으로 정의한다. role=consumer를 유지하고 Kafka·Spark 그룹에 넣지 않는다. traffic의 consumer_kafka는 consumer→Kafka TCP 9092, consumer_mongo는 consumer→MongoDB TCP 27017, forward_proxy는 consumer→Bastion TCP 3128, SSH 연결은 Bastion→consumer TCP 22를 허용한다. 역할별 흐름은 송신·수신 보안그룹 규칙으로 펼쳐진다. 플랫폼 방화벽의 Kafka·MongoDB 허용 출처에도 consumer를 포함한다. Consumer 프로그램 배포와 원격 방화벽 적용은 별도다. foundation의 account2_private, workload의 account2_three_nodes·flatten.tftest.hcl·console-ssh.tftest.hcl과 fixtures.json의 consumer SG가 관련 검사 위치다. 이번 문서 작업은 테스트 실행 결과를 새로 주장하지 않는다.
