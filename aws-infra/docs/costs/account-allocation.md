# 5개 계정 비용 균등 배치 설계

- 작성일: 2026-10-08, 한국 시간
- 목적: 선택한 EC2 16대·사양·기본 디스크를 유지하면서 계정별 비용 편차를 줄이고, 원본 저장 비용이 한 계정에 몰리지 않도록 배치한다.
- 상태: 사용자 요청에 따른 새 배치 제안. 이전의 서비스별 전용 계정 배치를 대체하는 문서 기준이며, AWS 리소스나 Terraform 설정에 적용하지 않았다.
- 비용 기준: [가용 영역 2개 견적](../costs/dual-az.md). EC2 45시간, EBS·NAT·고정 IPv4 153시간, 세전·크레딧 차감 전.

## 1. 추천 배치와 비용

**account1에 4대, 나머지 계정에 3대씩 둔다. 계정별 EC2 비용은 모두 $9.36이며, EBS·NAT·IP를 포함한 기본 비용은 $24.06~$25.90이다.** 최대·최소 차이는 반올림 전 기준 $1.845871로 약 $1.85다. 전체 기본 비용 $126.56은 이전과 같다.

| 계정 | 배치하는 별도 EC2 | 대수 | EC2 비용 | EBS 용량 / 비용 | NAT + NAT IP | 서비스 공인 IP 비용 | 기본 소계 |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| account1 | Frontend·Bastion·Backend·Kafka 1 | 4 | $9.36 | 180GB / $3.375871 | $9.792 | 2개 / $1.530 | **$24.06** |
| account2 | Kafka 2·MySQL 1·Spark Master | 3 | $9.36 | 360GB / $6.751742 | $9.792 | 0 | **$25.90** |
| account3 | Spark Worker 1·MongoDB 1·MySQL 2 | 3 | $9.36 | 360GB / $6.751742 | $9.792 | 0 | **$25.90** |
| account4 | Spark Worker 2·MongoDB 2·MySQL 3 | 3 | $9.36 | 360GB / $6.751742 | $9.792 | 0 | **$25.90** |
| account5 | Kafka 3·MongoDB 3·광고 | 3 | $9.36 | 260GB / $4.876258 | $9.792 | 1개 / $0.765 | **$24.79** |
| **합계** | | **16** | **$46.80** | **1,520GB / $28.507355** | **$48.960** | **$2.295** | **$126.56** |

합계와 편차는 반올림 전 값으로 계산한다. 계정별 두 자리 표시값을 더한 값과 전체 합계가 다를 수 있다. 광고의 서비스 공인 IP 1개는 아직 계산 가정이다.

계정별 NAT 1개와 전용 IPv4 1개는 모두 동일한 $9.792다. 계정1의 EC2는 small 2대 + medium 1대 + large 1대, 나머지는 medium 2대 + large 1대이므로 실행비가 정확히 같다. EBS와 공인 IP 때문에 남는 차이를 줄이려고 불필요한 자원을 추가하지 않는다.

## 2. 이 배치를 선택한 이유

- 기존 서비스별 계정 배치는 기본 비용이 $17.89~$30.58, 최대·최소 차이 약 $12.69였다. 새 배치는 그 차이를 약 $1.85로 줄인다.
- Frontend와 Bastion을 같은 계정에 두는 기존 방향을 유지한다. Backend도 같은 VPC에 두므로 Frontend → Backend는 계정 간 Peering을 거치지 않는다. 두 노드의 AZ가 다르면 AZ 전송료는 여전히 발생한다.
- MongoDB는 account3·4·5에, Kafka는 account1·2·5에, MySQL은 account2·3·4에 한 대씩 분산한다. 클러스터별 EC2 수량과 각 노드의 별도 디스크는 유지한다.
- MongoDB와 Kafka의 디스크 증설이 같은 계정에 함께 반영되는 곳은 기본 비용이 낮은 account5 한 곳으로 제한한다.
- 게임의 외부 응답은 주로 account1, 광고 직접 공개 시 외부 응답은 account5에서 발생하도록 나뉜다. 실제 전송료 균등은 보장하지 않는다.
- 같은 계정의 MongoDB·MySQL은 **서로 다른 EC2**다. 두 DB를 같은 EC2에서 실행하는 제안이 아니다.

이 설계는 현재 기본 자원비를 비슷하게 맞춘 배치다. 현재 크레딧 잔액·이미 발생한 사용료·실제 전송량은 미조회이므로 최종 청구액까지 동일해진다는 뜻은 아니다. 모든 가능한 배치의 수학적 최적해라고 주장하지 않는다.

## 3. 노드별 사양·디스크·AZ

기존 노드별 물리 AZ A/B 배치는 유지하고 계정 소속만 재설계했다. 각 계정에 서로 다른 서비스를 섞지만 서비스 자체의 역할은 바꾸지 않는다.

| 계정 | 노드 | 역할 | 사양 | OS + 추가 gp3 | AZ | 서브넷 / 공인 IPv4 |
| --- | --- | --- | --- | --- | --- | --- |
| account1 | game-01 | Frontend | t3.small | 20GB + 0 | A | public / 1개 |
| account1 | bastion-01 | Bastion | t3.small | 20GB + 0 | B | public / 1개 |
| account1 | game-02 | Backend | t3.medium | 20GB + 0 | B | private / 없음 |
| account1 | kafka-01 | Kafka 1 | t3.large | 20GB + 100GB | A | private / 없음 |
| account2 | kafka-02 | Kafka 2 | t3.large | 20GB + 100GB | A | private / 없음 |
| account2 | mysql-01 | MySQL 1 | t3.medium | 20GB + 100GB | A | private / 없음 |
| account2 | spark-01 | Spark Master | t3.medium | 20GB + 100GB | A | private / 없음 |
| account3 | spark-02 | Spark Worker 1 | t3.large | 20GB + 100GB | B | private / 없음 |
| account3 | mongo-01 | MongoDB 1 | t3.medium | 20GB + 100GB | A | private / 없음 |
| account3 | mysql-02 | MySQL 2 | t3.medium | 20GB + 100GB | A | private / 없음 |
| account4 | spark-03 | Spark Worker 2 | t3.large | 20GB + 100GB | B | private / 없음 |
| account4 | mongo-02 | MongoDB 2 | t3.medium | 20GB + 100GB | A | private / 없음 |
| account4 | mysql-03 | MySQL 3 | t3.medium | 20GB + 100GB | B | private / 없음 |
| account5 | kafka-03 | Kafka 3 | t3.large | 20GB + 100GB | B | private / 없음 |
| account5 | mongo-03 | MongoDB 3 | t3.medium | 20GB + 100GB | B | private / 없음 |
| account5 | ad-01 | 광고 | t3.medium | 20GB + 0 | B | public / 1개를 견적 가정 |

Master·Backend·광고의 medium과 Master 작업 공간 100GB는 기존 계산값 유지다. 광고를 private로 설계하면 IP 1개분 $0.765를 빼고 필요한 서비스 연결을 다시 정한다. Driver·업무 Consumer·원본 저장 Consumer는 Spark 노드 중에 별도 프로세스로 배치하는 제안이며, 정확한 실행 노드·자원·재시작 정책은 아직 정하지 않았다. 이 프로세스용 EC2를 추가하면 비용도 다시 계산한다.

MongoDB·Kafka·MySQL 각각은 A 2대 / B 1대, Spark는 Master A / Worker B 2대다. 전체 EC2는 A 8대 / B 8대다. account2가 A에만 있고 account5가 B에만 있어도 각 클러스터는 계정 경계를 넘어 두 AZ에 배치된다. **3개 투표 멤버의 2:1 배치는 두 멤버가 있는 AZ 전체 장애를 견디지 못한다.** 계정 분산이 세 번째 AZ나 자동 장애 복구를 추가하지 않는다.

## 4. VPC·서브넷·NAT·Peering

각 계정에 VPC 1개와 두 AZ의 public/private 서브넷을 만든다. 즉 계정당 public A·private A·public B·private B의 4개 서브넷을 제안한다. 아래 CIDR은 신규 구축을 위한 예시이며 기존 VPC·현장망·연결망과 중복하지 않는지 실제 적용 전에 확인한다.

| 계정 | VPC CIDR 제안 | public A / private A | public B / private B | NAT 배치 |
| --- | --- | --- | --- | --- |
| account1 | 10.11.0.0/16 | 10.11.0.0/24 / 10.11.10.0/24 | 10.11.1.0/24 / 10.11.11.0/24 | public A |
| account2 | 10.12.0.0/16 | 10.12.0.0/24 / 10.12.10.0/24 | 10.12.1.0/24 / 10.12.11.0/24 | public A |
| account3 | 10.13.0.0/16 | 10.13.0.0/24 / 10.13.10.0/24 | 10.13.1.0/24 / 10.13.11.0/24 | public A |
| account4 | 10.14.0.0/16 | 10.14.0.0/24 / 10.14.10.0/24 | 10.14.1.0/24 / 10.14.11.0/24 | public B |
| account5 | 10.15.0.0/16 | 10.15.0.0/24 / 10.15.10.0/24 | 10.15.1.0/24 / 10.15.11.0/24 | public B |

NAT는 Zonal Public NAT Gateway를 계정마다 1개씩, 총 5개 유지한다. 가능하면 private EC2 수가 많은 AZ를 선택했고, account1은 A/B 각 1대로 동수여서 A를 초기안으로 정했다. 실제 트래픽량에 따른 최적 배치를 검증한 것은 아니다. 반대 AZ의 private 서브넷도 같은 계정의 NAT를 쓰므로 그 외부 통신에는 AZ 교차가 발생한다. NAT가 있는 AZ에 장애가 생기면 같은 계정의 다른 AZ도 외부 통신에 영향을 받는다.

AZ A/B는 모든 계정에서 같은 물리 AZ ID를 사용한다. `ap-northeast-2a` 같은 표시 이름만으로 대응시키지 않는다. [AWS AZ ID](https://docs.aws.amazon.com/ram/latest/userguide/working-with-az-ids.html)

5개 VPC의 모든 쌍을 직접 Peering으로 연결한다. **1–2, 1–3, 1–4, 1–5, 2–3, 2–4, 2–5, 3–4, 3–5, 4–5의 10개**다. Kafka는 account1·2·5, Spark는 account2·3·4에서 내부 및 상호 통신하므로 이 배치는 10쌍 모두 연결이 필요하다.

- public 서브넷의 기본 외부 경로는 자기 VPC의 IGW, private 서브넷은 자기 VPC의 NAT다.
- 필요한 public/private 라우팅 테이블에 각 상대 VPC CIDR → 해당 직접 Peering 경로를 양쪽 모두 등록한다.
- Peering에는 중계 기능이 없다. 다른 VPC를 거쳐 DB에 연결하거나 다른 계정의 NAT를 공유하지 않는다. [AWS Peering 제약](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-basics.html)
- Peering 연결 자체에는 시간 고정비가 없고, 같은 물리 AZ의 사설 통신은 무료다. 다른 AZ의 통신은 별도로 계산한다. 계정이 다르다는 이유로 인터넷을 경유할 필요는 없다. [AWS Peering 비용](https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-network-access-options/evaluating.html)

Peering은 이전 8개에서 10개로 늘지만 연결 시간 고정비는 추가되지 않는다. 노드별 AZ를 유지해도 Consumer 실행 위치·NAT 경로·외부 통신에 따라 전송료가 달라지므로 전체 청구액이 반드시 같다고 보장하지 않는다.

## 5. 보안 규칙과 접속 대상

세부 포트는 [보안 그룹 설계](security-groups.md)를 참조한다. 논리적인 역할은 8종류지만, 이 독립 계정 VPC 구성에서는 역할이 존재하는 VPC마다 그룹을 만들므로 **실제 SG는 16개**다. 다른 계정에 같은 이름의 SG를 만들어도 동일한 그룹이 되지는 않는다.

같은 클러스터의 복제 연결에는 로컬 SG뿐 아니라 다른 계정의 같은 역할 SG도 명시적으로 허용한다. 서비스 간 연결도 실제 상대 계정 ID/SG ID를 참조하며 Peering은 active여야 한다. [AWS 교차 계정 SG 참조](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-security-groups.html)

Frontend·Bastion·Backend는 같은 VPC에서도 별도 SG를 사용하고, DB·Kafka·Spark는 인터넷에 공개하지 않는다. Backend의 DB 접근은 읽기 전용 계정으로 제한하며 모든 업무 쓰기의 Kafka 우선 방침을 유지한다. Consumer·Spark에서 MySQL 3대로, 원본 저장 Consumer에서 MongoDB 3대로, Backend·Consumer·Spark에서 Kafka 3대로 연결을 허용한다.

Kafka advertised.listeners, MongoDB Replica Set 멤버, MySQL 클러스터 접속 대상, Spark Master·Driver 주소는 모든 이용 노드에서 해석·접속 가능한 사설 주소나 이름을 사용한다. MySQL Router는 Backend와 실제 DB에 연결하는 Spark·Consumer 노드에 함께 두고 DB 3대 모두에 연결 가능하게 한다. Private DNS를 쓰면 이름 해석 방법도 별도로 설정·검증한다.

## 6. 데이터 증가 시 비용 편차

현재 비용 예시와 동일하게 MongoDB 데이터 디스크를 각 300GB, 또는 MongoDB 각 1,000GB·Kafka 각 200GB로 늘린 경우의 **자원비만** 비교한다. 증설 용량도 153시간 전체 유지하는 계산이며, 전송료·CPU 초과 크레딧·기존 사용액·추가 테스트 비용은 포함하지 않는다.

| 계정 | 기본 디스크 | MongoDB 각 300GB | MongoDB 각 1,000GB + Kafka 각 200GB |
| --- | ---: | ---: | ---: |
| account1 | $24.06 | $24.06 | $25.93 |
| account2 | $25.90 | $25.90 | $27.78 |
| account3 | $25.90 | $29.65 | $42.78 |
| account4 | $25.90 | $29.65 | $42.78 |
| account5 | $24.79 | $28.54 | $43.55 |
| **합계** | **$126.56** | **$137.82** | **$182.83** |

이전 MongoDB 집중 계정은 대용량 예시에서 자원비만 $74.20이었지만, 이번 분산안에서는 같은 용량에서도 계정별 최대 $43.55다. 다만 **모든 계정이 $60 이내라는 보장은 아니다.** account5는 최초 $60 기준으로도 남은 $16.45 안에 전송료·광고 송신·CPU 초과·기존 사용액 등이 들어와야 한다.

MongoDB는 복제본 3개를 세 계정에서 보유하므로 데이터 증가분을 다섯 계정에 균등 분할할 수 없다. 광고 송신이나 Kafka·Spark CPU 부하에 따른 변동비도 편중될 수 있다. 기존 전체 트래픽 예시 $147.92/$175.85/$257.95를 단순히 5등분해 계정별 청구액으로 사용하지 않는다.

## 7. 적용 전 확인과 변경 범위

현재 비용 기준은 최초 크레딧 각 $60이며 실제 잔액은 미확인이다. 실제 계정에 적용할 때 기존 사용액을 확인하고 잔액이 작은 계정에 대용량 MongoDB나 광고 송신을 집중시키지 않는다. `기존 사용액 + 기본 자원비 + 추가 디스크 + 해당 계정 전송료 + CPU 초과·기타`를 합산해 비교한다.

`config/account1`~`account5`에 계정 식별 정보 파일이 있다. 2026-10-08 account5에 AWS 계정 `217016296352`의 `student` 사용자를 등록했으며, 서울 리전(`ap-northeast-2`)과 사용 프로필 `account5`를 저장했다. 로그인용 프로필은 `aws-infra-login5`이며 두 프로필의 STS 계정 ID 일치를 확인했다. 나머지 계정의 현재 인증 유효성·VPC·기존 리소스는 이번 등록에서 확인하지 않았다. 계정 식별 정보 등록만으로 이 배치 설계가 AWS에 적용된 것은 아니다.

이미 다른 계정에서 노드를 구축했다면 이 표만으로 계정 소속을 바로 바꾸는 것은 아니다. 이전할 대상·데이터·중단 시간·중복 실행비를 확인해 별도 절차를 만든다. 신규 구축이면 VPC·서브넷·SG 생성, Peering 수락과 경로, 상호 SG 규칙, 클러스터 설정, 데이터 경로·장애 복구 시험 순으로 구체화한다. AWS 리소스 생성·변경·삭제는 수행하지 않았다.
