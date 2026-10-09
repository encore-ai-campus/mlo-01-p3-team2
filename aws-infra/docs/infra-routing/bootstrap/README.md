# EC2 생성 이후의 설치 경계

[탐색 시작점](../ROUTING-README.md) · [현재 bootstrap 안내](../../../infra/bootstrap/README.md) · [compute 모듈](../terraform/README.md#compute)

현재 infra/bootstrap에는 안내 Markdown만 있다. 실제 설치·배포 스크립트가 있는 것으로 해석하지 않는다.

| 항목 | 현재 코드의 처리 |
| --- | --- |
| 서비스 EC2·EBS·SG 규칙·키페어·EIP | workload의 Terraform 모듈이 생성. SG 자체는 foundation 소유 |
| Bastion EC2·OS 디스크·전용 키페어·자동 공인 IP | 별도 bastion 단계. EIP 없음 |
| 노드 메타데이터 | compute·bastion의 user_data가 /etc/aws-infra/node.json에 name·role·account 기록 |
| EBS 포맷·마운트·파일시스템 증설 | 자동화 없음 |
| Kafka·MongoDB·MySQL·Spark·Django·Nginx 설치·실행 | 자동화 없음 |
| Proxy 패키지 설치 | [setup-proxy.sh](../setup-proxy.sh.md)를 Bastion에서 수동 실행해 Squid 패키지 설치. ACL·클라이언트 설정은 별도 |
| Front A·C 정적 파일 배포 | 자동화 없음. HTTP /static/* 전달만 ALB가 구성 |
| DB 복제·Kafka 토픽·Spark checkpoint·Kappa 처리 경로 | 별도 서비스·애플리케이션 설정 대상 |
| OS 사용자·sudo·파일 권한 | 보안그룹으로 설정하지 않으며 현재 설치 자동화 없음 |
| Bastion 생성·삭제·상태·전원 | [bastion.ps1](../scripts/bastion.ps1.md)의 PlanCreate/Create·PlanDelete/Delete·Status/Output·Stop/Start/Restart |
| EC2 전체 예약 기동·종료·백업·복구·데이터 이전 | 자동화 없음 |

서비스 주소·디스크 ID는 [workload 출력](../terraform/stacks/workload.md#출력), Bastion 주소·Proxy endpoint는 [Bastion 출력](../terraform/stacks/bastion.md#출력)에서 찾는다. 출력 값만으로 클러스터가 설치되었거나 데이터가 별도 EBS에 저장된다고 판단하지 않는다.

현재 proxy 모드는 내부 EC2가 Bastion의 사설 주소·3128 포트에 접속하도록 SG를 허용한다. Squid 패키지 설치 스크립트가 있지만 프록시 ACL·클라이언트 설정·인증과 실제 송신 검증은 별도로 준비해야 한다. Bastion 재생성 후에는 패키지를 재설치하고 변경된 주소·팀원 공개키를 갱신해야 한다. Private 기본 라우트를 Bastion으로 연결하는 NAT 구현은 없다.

현재 HTTP ALB 경로에 맞추려면 Front 두 대가 동일한 정적 파일을 HTTP 80에서 제공하고, game-server와 ad-server가 각 EC2의 HTTP 8000에서 요청을 처리해야 한다. 광고 Django는 사용자가 해당 서버에서 `python manage.py runserver 0.0.0.0:8000`으로 실행하는 구성이다. ALB가 /ads/*의 접두사를 제거하지 않으므로 광고 앱이 /ads/와 필요한 하위 경로를 처리해야 한다. 현재 코드가 프로그램 설치·파일 복사·Django 허용 호스트 설정을 수행하는 것은 아니다. 대상 그룹의 health check 경로 /에 응답하도록 서버 설정도 별도로 준비한다. 광고 앱의 실제 URL·ALLOWED_HOSTS·헬스 체크 응답은 확인하지 못했다.
