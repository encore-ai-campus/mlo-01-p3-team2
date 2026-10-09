# 현재 EC2 보안그룹과 서비스 통신

기준: 2026-10-10의 기본 topology·traffic과 workload 선언. 과거 HTTPS/WSS·MySQL 3대·NAT 배치 초안을 현재 규칙으로 사용하지 않는다. 이 문서는 AWS의 현재 규칙이나 애플리케이션 동작을 직접 조회한 결과가 아니다.

[계정 배치](costs/account-allocation.md), [설정](infra-routing/config/README.md), [workload](infra-routing/terraform/stacks/workload.md), [플랫폼 방화벽](../../platform/docs/platform-routing/roles/firewall/README.md)이 각 계층을 설명한다.

## 계정별 SG

| 계정 | 역할 | SG 수 |
| --- | --- | ---: |
| account1 | ad, bastion, frontend, game, alb | 5 |
| account2 | mongo, spark | 2 |
| account3 | kafka, mongo, mysql, spark | 4 |
| account4 | kafka, spark | 2 |
| account5 | kafka, mongo, mysql | 3 |

총 16개다. 이름은 aws-infra-계정-역할이며 실제 ID는 foundation 출력으로 읽는다. 서비스 역할 SG 14개와 Bastion·ALB 각 하나다. SG 자체는 foundation, 입출력 규칙은 workload가 소유한다. 같은 역할 서버는 같은 계정의 SG를 공유한다. 광고는 account1 Private C이고 MySQL은 account3·5 두 대다.

## 역할별 TCP 연결

아래는 기본 traffic의 전체 connections다. 같은 역할 간 연결은 로컬 SG와 다른 계정의 해당 역할 SG 조합으로 확장된다. 서로 다른 계정은 소유 계정 ID/SG ID 형식으로 참조하며, 소스 계정의 egress와 대상 계정의 ingress를 각각 적용한다.

| 연결 키 | 출발 역할 → 목적 역할 | 포트 |
| --- | --- | --- |
| alb_front | alb → frontend | 80 |
| alb_ad | alb → ad | 8000 |
| alb_game | alb → game | 8000 |
| admin_nodes | bastion → frontend, game, mongo, spark, ad, kafka, mysql | 22 |
| game_kafka | game, ad → kafka | 9092 |
| spark_kafka | spark → kafka | 9092 |
| kafka_replication | kafka → kafka | 9092 |
| kafka_controller | kafka → kafka | 9093 |
| mongo_replication | mongo → mongo | 27017 |
| mysql_replication | mysql → mysql | 3306 |
| spark_mongo | spark → mongo | 27017 |
| spark_mysql | spark → mysql | 3306 |
| game_mysql | game → mysql | 3306 |
| spark_master | spark → spark | 7077 |
| spark_driver | spark → spark | 7078–7094 |
| spark_block | spark → spark | 7079–7095 |
| spark_worker | spark → spark | 7100 |
| spark_master_ui | spark → spark | 8080 |
| zookeeper_client | spark → spark | 2181 |
| zookeeper_peer | spark → spark | 2888 |
| zookeeper_election | spark → spark | 3888 |
| forward_proxy | frontend, game, mongo, spark, ad, kafka, mysql → bastion | 3128 |

port_end는 ports의 끝 키를 선택하는 항목이며 생략하면 단일 포트다. 같은 SG 쌍·시작 포트의 연결은 가장 큰 끝 값으로 합쳐 기존 Terraform 규칙 키를 유지한다. 기본 파일 수정이 이미 생성한 프로필의 복사본을 자동으로 갱신하지 않는다.

## 외부 접속과 콘솔 SSH

- 관리자 admin_public_cidrs → Bastion TCP 22. 현재 기본 파일에는 한 항목이며 실제 관리 PC 범위와 대조한다.
- game_client_cidrs → ALB HTTP 80. /static/* → Front:80, /ads/* → ad:8000, 기본 → game:8000이다. Front에 직접 HTTPS 443을 공개하는 규칙이 아니다.
- internet_https_roles의 Bastion만 0.0.0.0/0 TCP 443 egress를 받는다. 일반 Private 서버에 직접 인터넷 HTTPS 송신을 여는 기본 구성은 아니다.
- 해당 리전의 EC2 Instance Connect 관리형 IPv4 접두사 목록 → 서비스 SG의 TCP 22를 별도 허용한다. 대상 SG는 계정별 3/2/4/2/3개이며 기존 Bastion 콘솔 규칙도 유지한다. 접속 경로·Endpoint·키 등록·IAM 권한을 자동 제공하는 기능은 아니다.

현재 ALB 모듈은 HTTP listener만 만들고 인증서·HTTPS 리다이렉트는 없다. Django·정적 파일·광고 앱 설치와 실제 헬스 체크 성공은 별도다. CloudWatch agent·전용 Endpoint나 그 전송 정책은 이 구현에 추가돼 있지 않다.

## Spark·ZooKeeper

| 용도 | 기본 TCP 설정 |
| --- | --- |
| Master RPC / 내부 Master UI | 7077 / 8080 |
| Worker RPC / Worker UI | 7100 / 8081(원격 공개 SG 규칙 없음) |
| 작업 Driver RPC | 7078–7094 |
| Driver·Executor BlockManager | 7079–7095 |
| ZooKeeper 클라이언트 / 동기화 / 선출 | 2181 / 2888 / 3888 |

Spark의 전체 세 서버에 Worker·ZooKeeper를, 인벤토리 앞 두 서버에 Master를 배치한다. Master·Worker 데몬은 포트 재시도 0, 작업은 최대 16회를 사용한다. [Spark 설정](../../platform/docs/platform-routing/roles/spark/README.md#프라이빗-서버의-통신-포트)과 선택한 traffic을 함께 맞춘다. 이전 초안의 Worker 7078·Driver 35000·BlockManager 35100은 현재 값이 아니다.

[포트 범위 테스트](infra-routing/tests/README.md#spark-포트-범위)는 모델·SG 속성·workload 병합을 검사하도록 선언돼 있다. 실제 성공은 ZooKeeper leader/follower, Spark ALIVE/STANDBY·Worker 등록·PySpark 작업까지 따로 확인한다. SG 선언·서비스 active만으로 이 검증을 통과했다고 판단하지 않는다.

## Proxy·Peering·OS 방화벽

VPC 모든 쌍 10개를 직접 Peering으로 연결하고 양쪽 라우팅 테이블에 상대 CIDR 경로를 둔다. 기본 Private 인터넷 라우트는 없다. 클라이언트의 다운로드 요청은 사설 경로로 Bastion Squid:3128에 도달하고 Squid가 인터넷 HTTPS 연결을 만든다. 이는 다른 계정 NAT를 Peering으로 공유하는 구성과 다르다.

SG, Squid ACL과 EC2 안의 nftables는 모두 맞아야 한다. 플랫폼 방화벽은 인벤토리의 역할 그룹 IP를 사용하며 기본 서비스 그룹 간에는 SSH 22를 제외한 포트를 허용한다. Proxy 활성 Bastion에는 프로젝트 CIDR → TCP 3128을 허용한다. 이 OS 정책이 AWS SG의 모든 포트를 여는 것은 아니다.

game·ad 전용 설치 역할과 OS 방화벽 그룹 규칙은 현재 없다. backend 그룹으로 이름만 바꾸어도 앱이 설치되는 것은 아니며, 애플리케이션의 실제 연결·계정 권한·방화벽을 별도로 맞춘다. 앱의 Kafka 우선 쓰기·Consumer 처리·원본 보관·Spark 집계 요구는 네트워크 규칙이 강제하지 않는다. MySQL의 현재 구현은 InnoDB ReplicaSet이며 Group Replication 전용 포트·자동 failover를 구성하지 않는다.

## 적용과 확인

규칙 변경은 해당 구성의 영향받는 계정 workload Plan → 검토 → Apply로 반영한다. 노드·역할·SG가 바뀌면 foundation·connectivity 의존성도 검토한다. 중간 계정의 Peering을 통해 우회하는 경로나 중앙 NAT 경로를 추정하지 않는다. 검증 명령과 설치 순서는 [배포 절차](deployment-runbook.md)를 따른다. 이번 문서 갱신에서 AWS 규칙 조회·Plan·Apply·SSH·Ansible을 실행하지 않았다.
