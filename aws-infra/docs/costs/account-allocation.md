# 현재 5개 계정의 서버·AZ·비용 배치

갱신일: 2026-10-10. 기준은 [기본 topology](../../infra/config/topology.tfvars.json)와 [구성 지도](../infra-routing/config/README.md)다. 과거 t3·NAT 5개·MySQL 3대 균등 배치 제안은 현재 구현과 다르며 이 문서의 현 구성으로 사용하지 않는다. 비용 프로필을 선택했다면 그 topology가 기본값보다 우선한다.

## 계정별 현재 자원

| 계정 / VPC | A | C | 서비스 대수 | Bastion 포함 small / large | 전체 EBS GiB |
| --- | --- | --- | ---: | ---: | ---: |
| account1 / 10.10.0.0/16 | Public Bastion·front-a, Private game-server | Public front-b, Private ad-server | 4 | 3 / 2 | 100 |
| account2 / 10.20.0.0/16 | Private mongo-1·spark-2 | 서비스 없음 | 2 | 1 / 1 | 1,040 |
| account3 / 10.30.0.0/16 | Private kafka-1·mysql-1·spark-1 | Private mongo-2 | 4 | 2 / 2 | 1,380 |
| account4 / 10.40.0.0/16 | Private kafka-2 | Private spark-3 | 2 | 0 / 2 | 340 |
| account5 / 10.50.0.0/16 | Private mongo-3 | Private mysql-2·kafka-3 | 3 | 2 / 1 | 1,260 |
| 합계 | A 10대 | C 6대 | 15 | 8 / 8 | 4,120 |

EBS 합계는 OS 20GiB/대와 데이터 디스크를 합친 값이다. Bastion을 생성하지 않으면 account1에서 EC2 한 대·OS 20GiB가 빠진다. 역할별 사양·데이터 디스크는 [프로젝트 구성](../../README.md#서버-수와-사양)에 있다. 광고는 account1 Private C이며 account2에 있지 않다.

## VPC·서브넷·송신

논리 A=apne2-az1, C=apne2-az3다. 모든 VPC에 Private A/C(/24, 세 번째 옥텟 10/11), account1에만 Public A/C(/24, 0/1)와 IGW가 있다. 기본 egress는 proxy, NAT Gateway는 0개다. 다섯 VPC의 모든 쌍을 직접 Peering으로 연결한다.

Front 두 대에 EIP, Bastion 실행 중에는 자동 공인 IP를 사용한다. ALB는 account1 Public A/C에 한 개다. 중앙 Squid는 사설 주소의 TCP 3128로 클라이언트 요청을 받아 인터넷 HTTPS에 연결한다. Private 기본 인터넷 라우트를 다른 VPC의 IGW·NAT로 공유하지 않는다.

## 현재 배치와 과거 견적의 차이

계정별 비용을 균등하게 하려던 요구와 현재 자원 배치는 구분한다. EC2 수량·사양·EBS가 계정마다 다르고 ALB·외부 송신·Proxy도 account1에 집중된다. 계정별 금액을 단순히 총액의 1/5로 나누지 않는다.

[상세 견적](dual-az.md)은 2026-10-08 단가·트래픽 가정을 보존한 계산 기록이다. 그 기록의 account2 광고 서버와 Bastion EIP·153시간 공인 IP 가정은 현재 구성과 다르다. 과거 $24.06~$25.90의 NAT 균등 배치 금액이나 기존 계정별 합계를 현 설정의 비용으로 사용하지 않는다. 이번 문서 동기화는 새 가격 조회·실제 잔액 확인·청구 예측을 수행하지 않았다.

재계산에는 선택한 프로필의 노드 사양·데이터 디스크, Bastion 실제 실행 시간, EIP·ALB 유지 시간과 IPv4 수, ALB 처리량·인터넷 송신, AZ 교차 복제·Spark·Consumer 통신, CPU 크레딧·로그·백업을 입력한다. 기본 데이터 용량은 150명 시나리오의 값을 유지하며 인원이 줄어도 Terraform이 자동으로 줄이지 않는다.

## 구성 변경과 설치

deploy.ps1 NewProfile로 topology·traffic·platform.json을 복사하고 노드 계정·사양·대수와 역할 연결을 맞춘다. 동일 원격 상태의 변경 계획을 검토한 뒤 적용하며, 별도 환경을 자동 복제하지 않는다. 노드 이름·계정·AZ 변경은 자원 교체와 데이터 이전을 동반할 수 있다.

MySQL은 account3·5 두 대의 InnoDB ReplicaSet, MongoDB는 account2·3·5 세 대, Kafka는 account3·4·5 세 대다. Spark는 account2·3·4 세 대에 Worker·ZooKeeper를 함께 두고 인벤토리 앞 두 대에 Master를 둔다. 프로그램 버전·포트·OS 방화벽과 데이터 마운트는 [플랫폼](../../../aws-platform/platform/README.md)에서 별도로 준비한다.

[보안규칙](../security-groups.md)과 [배포 절차](../deployment-runbook.md)를 함께 확인한다. SG·Peering 선언만으로 서비스 성능·복제·장애 복구가 보장되는 것은 아니다.
