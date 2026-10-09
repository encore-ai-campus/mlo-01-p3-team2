# 서버 설치·배포 경계

Terraform은 EC2·디스크·네트워크와 역할 메타데이터(`/etc/aws-infra/node.json`)까지만 구성한다.
Kafka·MongoDB·MySQL·Spark·Django·Forward Proxy 설치와 실행, EBS 포맷·마운트, 데이터 이전은 이 단계 다음의 작업이다.

`.\infra\scripts\infra.ps1 -Account accountN -Stage workload -Action Output`을 실행하면
`infra/.local/accountN/workload/outputs.json`에 서버 이름·사설 IP·공인 IP·EBS ID·ALB DNS를 저장한다.
5개 계정의 출력을 모아 서비스별 연결 설정을 만들 때 사용한다.

현재 통신 설정과 프로그램을 다음처럼 맞춘다.

| 역할 | 수신 포트 설정 |
|---|---|
| Frontend | HTTP 80, ALB의 `/static/*` 요청 |
| Django game | HTTP 8000, ALB 기본 경로와 WebSocket 연결 |
| Kafka | 클라이언트·복제 9092, KRaft controller 9093 |
| MongoDB | 멤버 간 및 클라이언트 27017 |
| MySQL | 클라이언트·복제 3306 |
| Spark | Master 7077, Driver 7078, BlockManager 7079로 고정 |
| Bastion의 Forward Proxy | 내부 클라이언트용 3128, 인터넷 HTTPS 443 |

이 포트·ALB 경로는 수정 가능한 초기 설정이다. 실제 앱 URL·헬스 체크·Spark 실행 방식에 맞춰
`config/traffic.tfvars.json`과 `config/topology.tfvars.json`을 함께 맞춘다.
현재 SG는 Spark UI·임의 포트·MySQL Group Replication 전용 포트를 열지 않는다.

Proxy 모드는 기본 라우트를 Bastion에 지정하는 NAT 방식이 아니다.
클라이언트에서 Bastion의 사설 주소로 `HTTPS_PROXY` 등을 지정하고, Proxy에 접속 허용 범위와 HTTPS CONNECT를 설정해야 한다.
인터넷 송신은 기본 HTTPS만 허용하므로 HTTP 패키지 저장소가 필요하면 HTTPS 저장소를 사용하거나 필요한 규칙을 명시적으로 추가한다.
프라이빗 인스턴스에서 자동으로 apt 설치가 되는 상태는 아니다.

Bastion을 거쳐 접속할 때는 개인키를 Bastion에 복사하지 않고 로컬 SSH의 `ProxyJump`를 사용할 수 있다.
OS 사용자와 파일 권한·sudo 정책은 서비스 설치 단계에서 관리하며, 보안그룹은 포트 접근만 제한한다.

모든 게임 이벤트를 Kafka에 먼저 기록하고 Consumer가 처리하는 Kappa 파이프라인은 별도 애플리케이션 구현 대상이다.
이 디렉터리에 자동 설치·데이터 삭제 스크립트는 아직 없다.
