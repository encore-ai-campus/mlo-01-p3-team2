# EC2 생성 이후의 설치 경계

[탐색 시작점](../ROUTING-README.md) · [현재 bootstrap 안내](../../../infra/bootstrap/README.md) · [compute 모듈](../terraform/README.md#compute)

현재 infra/bootstrap에는 안내 Markdown만 있다. 실제 설치·배포 스크립트가 있는 것으로 해석하지 않는다.

| 항목 | 현재 코드의 처리 |
| --- | --- |
| EC2·EBS·SG·키페어·공인 IP | workload의 Terraform 모듈이 생성 |
| 노드 메타데이터 | compute의 user_data가 /etc/aws-infra/node.json에 name·role·account 기록 |
| EBS 포맷·마운트·파일시스템 증설 | 자동화 없음 |
| Kafka·MongoDB·MySQL·Spark·Django·Proxy 설치·실행 | 자동화 없음 |
| DB 복제·Kafka 토픽·Spark checkpoint·Kappa 처리 경로 | 별도 서비스·애플리케이션 설정 대상 |
| OS 사용자·sudo·파일 권한 | 보안그룹으로 설정하지 않으며 현재 설치 자동화 없음 |
| EC2 Stop/Start·백업·복구·데이터 이전 | 현재 실행기 Action에 없음 |

연결 설정에 사용할 서버 주소와 디스크 ID는 [workload 출력](../terraform/stacks/workload.md#출력)에서 찾는다. 출력 값만으로 클러스터가 설치되었거나 데이터가 별도 EBS에 저장된다고 판단하지 않는다.

현재 proxy 모드는 내부 EC2가 Bastion의 사설 주소·3128 포트에 접속하도록 SG를 허용한다. 실제 Proxy 프로그램·클라이언트 설정·인증과 접근 정책은 추가로 준비해야 한다. Private 기본 라우트를 Bastion으로 연결하는 NAT 구현은 없다.
