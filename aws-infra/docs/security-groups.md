# 현재 EC2 보안그룹과 서비스 통신

기준: 2026-10-13의 기본 topology·traffic과 workload 선언. 전체 표는 설정상의 규칙이다. 2026-10-10 mysql-3 증설 규칙 23개의 AWS 대조 기록과, 2026-10-11 애플리케이션 연결 추가의 로컬 검증 결과를 구분한다. 현재 문서는 코드 대조 결과이며 실제 AWS 적용 완료를 뜻하지 않는다.

[계정 배치](costs/account-allocation.md), [설정](infra-routing/config/README.md), [workload](infra-routing/terraform/stacks/workload.md), [플랫폼 방화벽](../../aws-platform/platform/docs/platform-routing/roles/firewall/README.md)이 각 계층을 설명한다.

## 계정별 SG

| 계정 | 역할 | SG 수 |
| --- | --- | ---: |
| account1 | ad, bastion, game_frontend, ad_frontend, game | 5 |
| account2 | mongo, spark, consumer | 3 |
| account3 | kafka, mongo, mysql, spark | 4 |
| account4 | kafka, mysql, spark | 3 |
| account5 | kafka, mongo, mysql | 3 |

총 18개다. 이름은 aws-infra-계정-역할이며 실제 ID는 foundation 출력으로 읽는다. 서비스 역할 SG 17개와 Bastion 하나다. 현재 설정에서는 ALB SG를 생성하지 않는다. SG 자체는 foundation, 입출력 규칙은 workload가 소유한다. 같은 역할 서버는 같은 계정의 SG를 공유한다. 광고는 account1 Private A이고 MySQL은 account3·4·5 세 대다.

## 역할별 TCP 연결

아래는 기본 traffic의 전체 connections다. 같은 역할 간 연결은 로컬 SG와 다른 계정의 해당 역할 SG 조합으로 확장된다. 서로 다른 계정은 소유 계정 ID/SG ID 형식으로 참조하며, 소스 계정의 egress와 대상 계정의 ingress를 각각 계산한다. 단, Account 1 Backend 8000의 ingress는 workload에서 해당 Front 출처만 남긴다. 아래 game_ad·ad_game·mysql_game·mysql_ad는 traffic 및 송신 선언에 남아 있지만 Account 1의 해당 수신 규칙은 생성하지 않으므로 API 연결 허용을 뜻하지 않는다.

| 연결 키 | 출발 역할 → 목적 역할 | 포트 |
| --- | --- | --- |
| admin_nodes | bastion → game_frontend, ad_frontend, game, mongo, spark, ad, kafka, mysql, consumer | 22 |
| game_kafka | game, ad → kafka | 9092 |
| spark_kafka | spark → kafka | 9092 |
| consumer_kafka | consumer → kafka | 9092 |
| kafka_replication | kafka → kafka | 9092 |
| kafka_controller | kafka → kafka | 9093 |
| mongo_replication | mongo → mongo | 27017 |
| mysql_replication | mysql → mysql | 3306 |
| spark_mongo | spark → mongo | 27017 |
| spark_mysql | spark → mysql | 3306 |
| game_mysql | game → mysql | 3306 |
| front_game | game_frontend → game | 8000 |
| front_ad | ad_frontend → ad | 8000 |
| game_ad | game → ad | 8000 |
| ad_game | ad → game | 8000 |
| consumer_mongo | consumer → mongo | 27017 |
| ad_mongo | ad → mongo | 27017 |
| ad_mysql | ad → mysql | 3306 |
| mysql_kafka | mysql → kafka | 9092 |
| mysql_game | mysql → game | 8000 |
| mysql_ad | mysql → ad | 8000 |
| spark_master | spark → spark | 7077 |
| spark_driver | spark → spark | 7078–7094 |
| spark_block | spark → spark | 7079–7095 |
| spark_worker | spark → spark | 7100 |
| spark_master_ui | spark → spark | 8080 |
| zookeeper_client | spark → spark | 2181 |
| zookeeper_peer | spark → spark | 2888 |
| zookeeper_election | spark → spark | 3888 |
| forward_proxy | game_frontend, ad_frontend, game, mongo, spark, ad, kafka, mysql, consumer → bastion | 3128 |

port_end는 ports의 끝 키를 선택하는 항목이며 생략하면 단일 포트다. 같은 SG 쌍·시작 포트의 연결은 가장 큰 끝 값으로 합쳐 기존 Terraform 규칙 키를 유지한다. 기본 파일 수정이 이미 생성한 프로필의 복사본을 자동으로 갱신하지 않는다.

## 외부 접속과 콘솔 SSH

| 대상 | 방향·포트 | 허용 출처 또는 목적지 |
| --- | --- | --- |
| 게임·광고 Front | 수신 TCP 80·443 | 0.0.0.0/0. HTTP-01 검증 경로 외 HTTP 요청은 Nginx에서 HTTPS로 이동 |
| 게임·광고 Front | 송신 모든 프로토콜 | 0.0.0.0/0 |
| 게임 Backend | 수신 TCP 8000 | game_frontend SG만 |
| 광고 Backend | 수신 TCP 8000 | ad_frontend SG만 |
| Account 1 네 서비스 | 수신 TCP 22 | Bastion SG만 |
| Bastion | 수신 TCP 22 | admin_public_cidrs의 관리자 IP |

Account 1 네 서비스에는 관리자 공인 IP SSH와 EC2 Instance Connect 콘솔 SSH 규칙을 생성하지 않는다. Account 2~5에는 기존 Private 관리자 CIDR SSH 및 콘솔 SSH 규칙(3/4/3/3개 SG)을 유지한다. Private SG의 CIDR 규칙이 인터넷 접속 경로를 만드는 것은 아니다. Bastion 콘솔 SSH 규칙은 생성하지 않는다.

internet_https_roles의 Bastion은 인터넷 TCP 443 송신을 허용한다. 다른 Private 서버의 인터넷 송신 경로는 기존 Proxy 구성을 유지한다. 현재 Front 80·443 공개 범위는 workload에서 직접 선언하며 game_client_cidrs나 public_http_cidrs를 바꿔도 제한되지 않는다. public_http_cidrs는 이전 frontend 역할 및 선택 ALB HTTP에 사용하며, 해당 필드가 없으면 game_client_cidrs로 대체한다.

선택적으로 활성화할 수 있는 ALB 모듈은 HTTP listener만 지원하며 현재 기본 설정에서는 호출하지 않는다. 인증서·HTTPS 리다이렉트는 없다. Django·정적 파일·광고 앱 설치와 실제 헬스 체크 성공은 별도다. CloudWatch agent·전용 Endpoint나 그 전송 정책은 이 구현에 추가돼 있지 않다.

## Spark·ZooKeeper

| 용도 | 기본 TCP 설정 |
| --- | --- |
| Master RPC / 내부 Master UI | 7077 / 8080 |
| Worker RPC / Worker UI | 7100 / 8081(원격 공개 SG 규칙 없음) |
| 작업 Driver RPC | 7078–7094 |
| Driver·Executor BlockManager | 7079–7095 |
| ZooKeeper 클라이언트 / 동기화 / 선출 | 2181 / 2888 / 3888 |

Spark의 전체 세 서버에 Worker·ZooKeeper를, 인벤토리 앞 두 서버에 Master를 배치한다. Master·Worker 데몬은 포트 재시도 0, 작업은 최대 16회를 사용한다. [Spark 설정](../../aws-platform/platform/docs/platform-routing/roles/spark/README.md#프라이빗-서버의-통신-포트)과 선택한 traffic을 함께 맞춘다. 이전 초안의 Worker 7078·Driver 35000·BlockManager 35100은 현재 값이 아니다.

[포트 범위 테스트](infra-routing/tests/README.md#spark-포트-범위)는 모델·SG 속성·workload 병합을 검사하도록 선언돼 있다. 실제 성공은 ZooKeeper leader/follower, Spark ALIVE/STANDBY·Worker 등록·PySpark 작업까지 따로 확인한다. SG 선언·서비스 active만으로 이 검증을 통과했다고 판단하지 않는다.

## Proxy·Peering·OS 방화벽

VPC 모든 쌍 10개를 직접 Peering으로 연결하고 양쪽 라우팅 테이블에 상대 CIDR 경로를 둔다. 기본 Private 인터넷 라우트는 없다. 클라이언트의 다운로드 요청은 사설 경로로 Bastion Squid:3128에 도달하고 Squid가 인터넷 HTTPS 연결을 만든다. 이는 다른 계정 NAT를 Peering으로 공유하는 구성과 다르다.

SG, Squid ACL과 EC2 안의 nftables는 모두 맞아야 한다. 플랫폼 방화벽은 인벤토리의 역할 그룹 IP를 사용한다. account1_service_restricted가 설정된 네 서비스는 Front 웹 80·443, Backend의 대응 Front 8000, Bastion SSH 22로 수신을 제한하며 일반 from/self 허용 분기를 건너뛴다. 다른 계정의 기존 역할별 from/self 정책은 유지한다. Proxy 활성 Bastion에는 프로젝트 CIDR → TCP 3128을 허용한다. 이 OS 정책이 AWS SG의 모든 포트를 여는 것은 아니다.

game·ad 애플리케이션 전용 설치 역할은 현재 없다. 다만 game·Spark·선택 backend에는 기존 backend 역할로 로컬 MySQL Router를 설치하며, 플랫폼 MySQL 방화벽의 허용 출처에는 game·ad를 포함한다. 광고 서버의 Router 설치는 이번 변경에 추가하지 않았다. 앱 런타임과 나머지 애플리케이션 통신·계정 권한은 별도로 맞춘다. 앱의 Kafka 우선 쓰기·Consumer 처리·원본 보관·Spark 집계 요구는 네트워크 규칙이 강제하지 않는다.

현재 [MySQL 역할](../../aws-platform/platform/docs/platform-routing/roles/mysql/README.md)은 3~9대의 단일 Primary InnoDB Cluster와 자동 Primary 선출을 구성한다. MYSQL 통신 스택을 사용하므로 멤버 간 기본 TCP 3306이 필요하다. 기본 인프라에 MySQL 세 대를 선언했고 current 프로필의 mysql-3 EC2·SG 반영을 확인했다. 인벤토리·Proxy·데이터 마운트·OS 방화벽은 설치 전에 다시 준비한다. [로컬 Router](../../aws-platform/platform/docs/platform-routing/roles/backend/README.md)의 6446(RW)·6447(RO)은 127.0.0.1에서 받으므로 원격 SG 포트로 추가하지 않는다. 실제 자동 선출·Router 재접속과 쓰기 성공은 별도 운영 검증 대상이다.

평탄화 Consumer의 AWS SG는 Kafka 9092·MongoDB 27017·프록시 3128 송신을 허용한다. MySQL·Kafka Controller 9093 연결은 열지 않는다. Kafka·MongoDB의 OS 방화벽 허용 출처에 consumer를 포함한다. 생성 인벤토리의 consumer 역할은 유지한다.

## 적용과 확인

규칙 변경은 해당 구성의 영향받는 계정 workload Plan → 검토 → Apply로 반영한다. 노드·역할·SG가 바뀌면 foundation·connectivity 의존성도 검토한다. 중간 계정의 Peering을 통해 우회하는 경로나 중앙 NAT 경로를 추정하지 않는다. 검증 명령과 설치 순서는 [배포 절차](deployment-runbook.md)를 따른다. 2026-10-10 mysql-3 증설에서는 다섯 계정 workload Plan·Apply 후 추가 규칙 23개의 포트·방향·소스 SG를 AWS에서 확인했다. 기존 서버는 유지했다. [실제 검증 기록](infra-routing/verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)을 참고한다. SSH·MySQL 서비스 통신·Ansible 설치·OS 방화벽 적용은 이번 작업에서 실행하지 않았다.

<a id="2026-10-11-애플리케이션-연결-추가"></a>

## 과거 기록: 2026-10-11 애플리케이션 연결 추가

아래는 당시 구현·검증 기록이다. 현재 Backend 8000 허용 범위는 위의 Account 1 제한 규칙을 따른다.

Front→게임·광고, 게임↔광고 API, 평탄화·광고→MongoDB, 광고→MySQL, MySQL 서버→Kafka·게임·광고의 10종류를 기본 및 current 프로필에 반영했다. 새 SG 연결 28쌍의 ingress·egress가 생성되며 기존 연결은 제거하지 않는다. 서버 간 출발지·목적지는 역할 SG를 참조하고, 지정한 단일 TCP 포트만 추가한다.

Kafka와 Spark·평탄화의 양방향 데이터 흐름은 Spark·Consumer가 시작하는 9092 연결을 사용한다. SG는 허용된 연결의 응답을 통과시키므로 Kafka가 Spark·Consumer에 새로 접속하는 규칙은 필요하지 않다. MySQL→게임·광고 8000은 해당 MySQL 서버에서 별도 프로그램이 API를 호출하는 경로이며 MySQL 쿼리 응답은 기존 3306 연결을 사용한다.

플랫폼 firewall에는 game·ad 수신 역할을 추가하고 MySQL·MongoDB·Kafka의 from 목록을 맞췄다. from/self는 기존처럼 SSH 22를 제외한 포트를 허용하며, 실제 서비스 포트 범위는 AWS SG가 제한한다. 외부 사용자→Front 443 및 Nginx·인증서 설치는 추가하지 않았다.

[로컬 검증 기록](infra-routing/verification.md#2026-10-11-애플리케이션-통신-규칙)은 Terraform 모의 테스트 13건과 방화벽 템플릿 9종·출처 검사 67건이다. 실제 AWS Plan·Apply, 원격 Ansible, 서비스 데이터 송수신은 실행하지 않았다.

<a id="2026-10-11-alb-비활성화"></a>

## 과거 기록: 2026-10-11 ALB 비활성화

앞선 애플리케이션 연결 추가 후, 기본 및 current 설정에서 ALB와 전용 연결 3개를 제외했다. ALB 비활성화 직후는 30개 연결이었고, 당시에는 이후 edge_front를 추가해 31개 연결이 됐다. 현재는 edge_front를 제거했다. ALB의 대상 연결 3쌍과 양쪽 규칙은 제거 대상이고 Front→게임·광고 8000 등 다른 연결은 유지한다. 현재 EC2의 보안그룹 상태를 조회하거나 적용한 결과가 아니다. [기존 자원 정리 순서](deployment-runbook.md#alb-비활성화-적용-순서)를 따른다.

<a id="진입용-edge-생성-설정"></a>

## 과거 기록: 진입용 edge 생성 설정

아래는 제거 전 설계다. 현재 topology에는 edge-1이 없고 두 Front가 각자 HTTPS를 처리한다.

edge-1은 account1 Public A의 전용 edge SG를 사용한다. edge_front·admin_nodes·forward_proxy로 연결 3쌍의 ingress·egress를 선언한다. 앱 연결은 Front 80이며 관리 연결은 Bastion→edge 22, edge→Bastion 3128이다. 외부 ACME 80·허용 사용자 443·관리자 22와 인증기관·패키지 저장소 접근용 인터넷 443을 추가한다. 초기 구축 모드는 이 계정의 edge 관련 규칙만 생성하며 EC2는 edge-1만 선택한다. 프로그램·OS 방화벽·실제 TLS 성공은 별도로 확인한다.

<a id="2026-10-12-학원-접속-범위"></a>

## 과거 기록: 2026-10-12 학원 접속 범위

아래는 당시 정책이다. 현재 Front는 80·443 전체 공개이며 Account 1 네 서비스의 SSH는 Bastion만 허용한다. 아래 edge 및 전체 서비스 콘솔 SSH 설명을 현재 정책으로 적용하지 않는다.

- 학원 공인 IP는 `222.112.208.69/32`다. 앞서 전달된 `.72`는 사용하지 않는다.
- `admin_public_cidrs`: 학원 IP. Bastion SSH 22 및 Private 서버의 역할별 SG에 학원 IP의 SSH 22를 허용한다.
- `public_http_cidrs`: `0.0.0.0/0`. Public Front의 HTTP 80만 전체 공개한다. 필드가 없는 이전 프로필은 game_client_cidrs로 동작한다.
- `game_client_cidrs`: 학원 IP. 기존 edge HTTPS 443 범위를 전체 공개로 확대하지 않는다.
- Bastion의 EC2 Instance Connect 콘솔 SSH 출처 규칙은 생성하지 않는다. 기존 규칙이 있다면 다음 workload Plan에 해당 규칙 삭제가 표시된다. 서비스 서버의 기존 콘솔 SSH 규칙은 유지한다.
- Private SSH CIDR 규칙은 인터넷 경로를 만들지 않는다. Bastion 경유 시 목적 서버에는 Bastion 사설 IP가 출처로 보이므로 기존 Bastion→서버 SG 규칙도 유지한다. OS 방화벽·접속 경로의 실제 성공은 별도다.
- 기존 저장 Plan은 다시 만들어야 한다. 코드만 수정했으며 AWS Apply는 실행하지 않았다.
