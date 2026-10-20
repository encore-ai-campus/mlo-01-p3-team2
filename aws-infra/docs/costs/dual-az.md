# 서울 A·C 비용 견적 기록 — 50·100·150명 × 초당 30회

기존 견적 작성일은 2026-10-08이고 문서 구분을 갱신한 날짜는 2026-10-10이다. 아래 1~9절의 수치·단가·전송 모델은 당시 가정의 기록이다. 이번 작업에서 최신 가격·실제 청구·계정 잔액을 조회하거나 재견적하지 않았다.

현재 코드의 배치는 [비용 안내](costs.md#현재-기본-구성)와 [계정별 자원 배분](account-allocation.md)을 따른다. 현재 ad는 Account 1 Private A이며 Account 2에는 Mongo-1·Spark-2·flatten-1 Consumer가 있다. 서비스 18대와 별도 배스천 1대, OS·데이터 EBS 합계 4,280GiB가 기본값이다. Front 및 edge EIP 3개와 자동 공인 IP의 배스천을 사용한다. 2026-10-11 기본 및 current 설정은 ALB를 비활성화했으며 아래 ALB 포함 견적은 당시 가정으로 보존한다.

과거 견적은 ad가 Account 2에 있고 배스천 고정 IP를 153시간 유지한다고 계산했다. 당시 Spark Master 1대·Worker 2대의 소비 배분도 현재 Master 2개·Worker 3개 구성과 다르다. 따라서 아래 계정별 비용과 트래픽 비율은 현재 설정의 비용 예측이 아니다. 기존 50명·100명 디스크 축소 시나리오도 현재 프로필에 자동 적용되지 않는다.

현재 설정에는 A=apne2-az1, C=apne2-az3이 선언되어 있다. 실제 AWS 리소스의 AZ ID는 이번 문서 작업에서 조회하지 않았다. 가격과 트래픽을 재산정할 때 현재 프로필·운영 시간·실측 전송량을 기준으로 갱신한다.

## 1. 결과와 해석

세 시나리오는 독립 비교다. 150명 중 일부가 50명/100명이라는 단계별 시간표가 아니며, 세 금액을 합산하지 않는다.

| 항목 | 50명 | 100명 | 150명 |
|---|---:|---:|---:|
| EC2 16대, 45시간 | $42.12 | $42.12 | $42.12 |
| EBS, 153시간 | $37.88 | $60.39 | $77.27 |
| ALB 기본료, 153시간 | $3.44 | $3.44 | $3.44 |
| 공인 IPv4 5개, 153시간 | $3.83 | $3.83 | $3.83 |
| 주요 경로 A↔C 전송 | $24.05 | $48.11 | $72.16 |
| ALB 처리량 LCU | $3.98 | $7.96 | $11.94 |
| 인터넷 송신 — 무료량 차감 전 | $31.35 | $62.71 | $94.06 |
| **주요 경로 계산 소계** | **$146.66** | **$228.55** | **$304.82** |
| 추가 Spark 교차 통신 0.5D 예시 | $2.49 | $4.98 | $7.46 |
| 추가 MySQL binlog 전송 D 예시 | $4.98 | $9.95 | $14.93 |
| **추가 통신 예시까지 포함** | **$154.13** | **$243.48** | **$327.22** |
| 위 예시에서 인터넷 무료 100GB가 남아 있는 경우 | **$141.53** | **$230.88** | **$314.62** |

금액은 세전·크레딧 차감 전이다. 합계는 반올림 전 계산값을 합산하므로 표시된 행을 더한 값과 차이가 날 수 있다.

앞서 계산한 **$76.02**는 EBS 1,420GiB와 EC2·ALB 기본료·공인 IP만 포함한 자원비였다. 이번 표는 원본 보관량에 따른 디스크 증설과 실제 사용량을 가정한 네트워크·LCU·인터넷 송신을 추가했으므로 같은 범위의 금액이 아니다.

**실측 예측·청구 확정액·상한/하한 보장이 아니다.** 특히 입력 및 응답 크기, Kafka 추가 발행, Spark 처리 계획, MySQL 변경량, 게임 방송 범위가 바뀌면 결과가 달라진다. 광고·이미지/영상·추가 결과/조회·CPU 초과 크레딧·백업/로그·디스크 추가·세금 등은 이 표 밖이다. 알려지지 않은 경로를 무료라고 판단한 것이 아니다.

## 2. 사용자 조건과 계산 가정

| 구분 | 적용 내용 |
|---|---|
| 사용자 지정 기간 | 2026-10-13·14·15·16·19, 평일 5일 |
| 사용자 지정 시간 | 09:00~18:00, 한국 시간. 서버당 총 45시간 |
| 사용자 지정 부하 | 50명·100명·150명 각각, 1인당 초당 30회 |
| 사용자 지정 구성 | 아래 5계정별 서버·사양, 가용 영역 A·C |
| 부하 지속 가정 | 각 시나리오의 전원이 45시간 내내 초당 30회를 지속 |
| 자원 유지 가정 | EBS·ALB·고정 IP는 13일 09시부터 19일 18시까지 153시간 |
| 요금 방식 | 서울 Linux 온디맨드·공유 테넌시. 예약 할인·크레딧 미적용 |
| 입력 크기 | 이벤트 1개 = **1KiB = 1,024바이트**. 기존 견적의 미측정 가정 유지 |
| 응답 크기 | 이벤트마다 **전체 수신자 합계 1KiB**, 기본 예시는 1명에게 응답 |
| Kafka 발행 | 입력당 같은 크기 레코드 1개, RF3, Broker별 리더 데이터 1/3 |
| Kafka 소비 | 업무 Consumer·원본 Consumer·Spark가 각각 입력 전량 1회 소비 |
| MongoDB | 샤딩 없이 3개 데이터 노드가 기간 원본 전체를 각각 보관 |
| Kafka 보관 | 24시간 보관, 이 일정에서 정상 삭제 시 최대 9시간 입력량을 기본 산정 |
| 프론트 분산 | A·C Front에 입력/응답 바이트가 각각 절반씩 분산 |
| 연결 예시 | 사용자당 지속 연결 1개, 평균 분당 1회 재연결, 처리 규칙 10개 이하 |
| 공인 IP | Bastion·Front A·Front C에 고정 IP 각 1개, ALB IP 2개, 총 5개 유지 |
| 인터넷 무료량 | 기본값 0GB. 잔여 무료량 100GB는 별도 비교 |
| 추가 통신 예시 | Spark의 추가 A↔C 바이트 합계 0.5D, MySQL binlog A→C 바이트 D |
| 용량 여유 가정 | Mongo/Kafka의 원본량에 25% 여유를 두고 100GiB 단위 올림 |

초당 30회는 **이벤트 발생 횟수**다. 모든 이벤트가 별도 HTTP/TLS 새 연결이라는 가정도, 각 DB에 초당 30개 쿼리를 따로 실행한다는 가정도 아니다. 모든 이벤트를 다른 참가자에게 방송하면 응답량은 훨씬 커지며, 그때는 응답 바이트 합계로 다시 계산한다.

저장 용량은 **GiB = 2³⁰바이트**, 네트워크 견적은 **GB = 10⁹바이트**로 환산한다. 네트워크 GB는 이 문서의 요금 산정 가정이며, 실제 청구에는 AWS가 계량한 사용량을 적용한다. 이전 문서처럼 GiB 수치를 네트워크 GB에 그대로 대입하지 않는다. [ALB 공식 계산 예시](https://aws.amazon.com/elasticloadbalancing/pricing/)

## 3. 당시 견적의 계정·A/C 배치 — 현재 배치는 비용 안내 참조

A·C는 서로 다른 두 물리 AZ의 구분이다. 계정별 `ap-northeast-2a`·`ap-northeast-2c` 이름이 같은 물리 위치인지 **AZ ID로 확인**해야 한다. 실제 AZ ID와 리소스는 아직 조회하지 않았다. [AWS AZ ID](https://docs.aws.amazon.com/ram/latest/userguide/working-with-az-ids.html)

| 계정 / VPC | AZ A | AZ C |
|---|---|---|
| Account 1 / 10.10.0.0/16 | Bastion/Proxy small, Front(A) small, game-server large | Front(C) small |
| Account 2 / 10.20.0.0/16 | Mongo-1 small, Spark-2 large | Ad-server large |
| Account 3 / 10.30.0.0/16 | Kafka-1 large, MySQL-1 small, Spark-1 large | Mongo-2 small |
| Account 4 / 10.40.0.0/16 | Kafka-2 large | Spark-3 large |
| Account 5 / 10.50.0.0/16 | Mongo-3 small | MySQL-2 small, Kafka-3 large |
| 합계 | 10대 | 6대 |

표의 small/large는 모두 `t3a.small` / `t3a.large`다. 기존 Front(B)는 AZ C에 배치하므로 Front(C)로 표시한다. **EC2는 small 8대 + large 8대**, ALB는 별도 요금의 1개다.

Account 1의 ALB는 Public-A/C에 연결한다. 사용자의 표를 유지해 Bastion과 Front 2대는 Public, game과 다른 계정의 EC2는 Private인 비용 예시다. Account 1만 IGW와 공인 IPv4를 사용하며, 외부 통신은 Bastion의 명시적 Forward Proxy를 이용한다. **NAT Gateway는 0개**다. 서비스 간 통신은 직접 Peering 경로를 사용한다.

계산용 역할은 다음과 같다.

- Spark-1(A): Master·Driver·업무 Consumer·원본 Consumer. 추가 EC2 없이 함께 두는 가정으로, 실제 자원 배분은 미검증.
- Spark-2(A)와 Spark-3(C): Worker, 각각 Kafka 입력의 절반 처리.
- Mongo-1(A): Primary. Mongo-2(C)와 Mongo-3(A): 복제본.
- MySQL-1(A): Primary. MySQL-2(C): Secondary. 2노드 복제 방식·장애 전환 설정은 별도이며 자동 전환을 비용표가 보장하지 않는다.
- Kafka-1/2(A), Kafka-3(C): Broker와 Controller 겸용 가정, 토픽 RF3.

Kafka·Mongo의 2A/1C 배치는 A 전체 장애를 견디는 구성이 아니다. 게임·광고·Spark Master·중앙 Proxy도 각각 한 대다. 이 배치는 비용 계산을 위한 위치이며 양쪽 AZ 장애에서의 무중단 운영을 보장하지 않는다.

## 4. 당시 단가와 검증 시점 — 최신 단가 재확인 필요

| 항목 | 단가 (USD) | 근거·시점 |
|---|---:|---|
| t3a.small | 0.0234/시간 | 2026-10-08 공식 서울 Linux 가격 재조회 |
| t3a.large | 0.0936/시간 | 2026-10-08 공식 서울 Linux 가격 재조회 |
| EBS gp3 | 0.0912/GB·월 | 기존 문서의 2026-10-08 공식 카탈로그 검증값 재사용 |
| ALB 기본료 | 0.0225/시간 | 2026-10-08 서울 AWSELB 카탈로그 직접 조회 |
| ALB LCU | 0.008/LCU·시간 | APN2-LCUUsage, 같은 카탈로그 |
| 공인 IPv4 | 0.005/IP·시간 | AWS VPC 공식 요금 |
| AZ 교차 일반 EC2/Peering | 송신 0.01 + 수신 0.01/GB | 한 방향 전송 1GB의 양끝 합계 0.02 |
| 인터넷 송신 | 0.126/유료 GB | 기존 문서의 **2026-10-07** 서울 첫 유료 10TB 구간 조회값 재사용 |
| T3a Linux 초과 CPU 크레딧 | 0.05/vCPU·시간 | EC2 공식 요금 |

EC2: [AWS 서울 Linux 공개 가격](https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/Asia%20Pacific%20%28Seoul%29/Linux/index.json). small rate code는 `C2X6J7RSNDMJVBF6.JRTCKXETXF.6YS6EN2CT7`, large는 `5U4PTNB2JS3SSWPQ.JRTCKXETXF.6YS6EN2CT7`다.

ALB: [서울 AWSELB 가격표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSELB/current/ap-northeast-2/index.json), `APN2-LoadBalancerUsage`·`APN2-LCUUsage`. 확인한 카탈로그 게시일은 2026-09-11, 적용일은 2026-08-01이다.

EBS: [공식 가격표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-2/index.json)의 `APN2-EBS:VolumeUsage.gp3` 기존 검증값과 [과금 방식](https://aws.amazon.com/ebs/pricing/)을 적용했다. gp3 기본 3,000 IOPS·125MiB/s를 넘는 추가 성능 구매는 제외한다.

인터넷 송신: [AWS Data Transfer 가격표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSDataTransfer/current/index.json)의 `APN2-DataTransfer-Out-Bytes` 기존 검증값. [EC2 과금·무료 송신 집계](https://aws.amazon.com/ec2/pricing/on-demand/), [VPC IPv4·Peering 요금](https://aws.amazon.com/vpc/pricing/)도 참조한다. 재사용한 EBS·인터넷 단가를 이번 작업에서 새로 API 조회한 것으로 표시하지 않는다.

## 5. 이벤트와 저장 공간

`기간 초 = 45 × 3,600 = 162,000`

`이벤트 수 = 인원 × 30 × 162,000`

`D = 이벤트 수 × 입력 바이트 / 10⁹` (네트워크 GB), `O = 이벤트 수 × 전체 응답 바이트 / 10⁹`. 기본값은 O=D다.

| 항목 | 50명 | 100명 | 150명 |
|---|---:|---:|---:|
| 이벤트/초 | 1,500 | 3,000 | 4,500 |
| 기간 이벤트 수 | 243,000,000 | 486,000,000 | 729,000,000 |
| 원본량 D, 네트워크 GB | 248.832 | 497.664 | 746.496 |
| 원본 저장량, GiB | 231.74 | 463.49 | 695.23 |
| 하루 9시간 원본량, GiB | 46.35 | 92.70 | 139.05 |
| MongoDB 추가 디스크/대 | 300GiB | 600GiB | 900GiB |
| Kafka 추가 디스크/대 | 100GiB | 200GiB | 200GiB |
| Spark 추가 디스크/대 | 100GiB | 100GiB | 100GiB |
| MySQL 추가 디스크/대 | 100GiB | 100GiB | 100GiB |
| OS 전체 — 20GiB × 16 | 320GiB | 320GiB | 320GiB |
| **EBS 전체** | **2,020GiB** | **3,220GiB** | **4,120GiB** |

MongoDB는 세 노드가 전체 원본을 각각 복제한다. 원본량을 3으로 나누지 않는다. Kafka도 RF3이므로 각 노드에 하루 전체 원본량 수준의 디스크를 산정했다. Mongo/Kafka 용량은 `max(100, ceil(원본 GiB × 1.25 / 100) × 100)`이다.

25% 여유는 견적용 가정이다. BSON 변환·인덱스·oplog·압축·Kafka 세그먼트·삭제 지연을 검증한 값이 아니다. 야간 중지 후 Kafka 재시작 시 만료 삭제 지연과 재처리 공간이 필요할 수 있다. Spark 상태/체크포인트와 MySQL 데이터/binlog의 100GiB가 충분한지도 미검증이다. binlog 전송량과 보관 기간은 다르며, 모든 binlog를 5일간 보관한다면 디스크를 별도로 늘려야 한다.

모든 용량을 처음부터 153시간 유지한다고 계산했다. 10월은 31일이므로 EBS 비용은 `용량 × 0.0912 × 153/744`다. 100GiB를 이 기간에 추가하면 **$1.87548**가 추가된다.

## 6. 주요 A↔C 경로 — 전송료를 계산한 이유

같은 물리 AZ의 사설 Peering 통신은 계정이 달라도 이 표의 전송료가 없다. 다른 AZ의 일반 EC2 통신은 계정이 같아도 양끝에 요금이 붙는다. **Account 1의 ALB↔Front 사설 IP 구간은 같은 VPC에서 AZ가 달라도 전송료 면제이므로 아래 유료 바이트에 넣지 않는다.** ALB 처리 LCU는 별도로 계산한다. [AWS ALB 전송료 설명](https://aws.amazon.com/blogs/networking-and-content-delivery/exploring-data-transfer-costs-for-classic-and-application-load-balancers/)

| 경로 | A↔C 바이트량의 D/O 비율 | 계산 가정 |
|---|---:|---|
| Front ↔ game | 0.5(D+O) | C Front가 절반을 받고 game은 A |
| game → Kafka | D/3 | 리더 데이터 중 C Broker 몫 1/3 |
| Kafka RF3 복제 | 4D/3 | A 리더 두 개→C 각 D/3, C 리더→A 두 개 각 D/3 |
| Kafka → 업무 Consumer | D/3 | Consumer A, C Broker 데이터 1/3 |
| Kafka → 원본 Consumer | D/3 | Spark와 별도 Consumer group |
| Kafka → Spark Worker | D/2 | 두 Worker가 절반씩 소비, Broker 리더 균등 |
| 원본 Consumer → Mongo Primary | 0 | 둘 다 A. 처리량 자체가 0이라는 뜻이 아님 |
| 업무 Consumer → MySQL Primary | 0 | 둘 다 A |
| MongoDB 복제 | D | Primary A → C 복제본 하나 |
| **주요 경로 교차량 C** | **(13/3)D + 0.5O** | O=D이면 **29D/6** |

위 C는 **각 구간·방향으로 전달한 바이트를 한 번씩** 합친 값이다. 여기에 양끝 단가 `0.02 × C`를 적용한다. 같은 바이트가 여러 서비스 구간을 거치면 각 구간별 전송이 발생하므로 해당 구간마다 계산한다.

| 시나리오 | 교차량 C (GB) | 양끝 합계 비용 |
|---|---:|---:|
| 50명 | 1,202.688 | $24.05 |
| 100명 | 2,405.376 | $48.11 |
| 150명 | 3,608.064 | $72.16 |

Kafka의 압축률·리더 배분·중복/확정 이벤트 추가 발행·Consumer 필터링·재처리가 달라지면 이 비율을 바꿔야 한다. Kafka Controller 제어 트래픽, 프로토콜·TLS 헤더 및 재전송은 입력 1KiB 모델에 따로 측정해 추가해야 한다.

### 미측정 추가 경로를 포함한 계산 예시

- **Spark 추가 교차 통신 S:** Worker 간 shuffle·결과 교환 등 기존 Kafka→Spark 입력 외의 A↔C 전송량 합계. 예시에서는 **S=0.5D**, Account 2↔4 경로로 배분했다.
- **MySQL binlog M:** Primary(Account 3 A)→Secondary(Account 5 C)의 교차 바이트. 예시에서는 **M=D**다.
- 그 외 조회·추가 결과 쓰기·Driver/Executor 통신·광고·관리 Proxy 등을 `X`로 측정해 추가한다.

`추가 교차 전송료 = 0.02 × (S+M+X)`

선택한 예시 S+M=1.5D는 총 **$7.46 / $14.93 / $22.39**를 더한다. 이는 실측도 제품 기본 비율도 아니다. 추가 교차 통신 100GB마다 총 **$2**, 송신 계정과 수신 계정에 각각 **$1**씩 더한다. 동일 계정 내 AZ 교차라면 양쪽 비용을 그 계정에 합산한다.

## 7. ALB와 인터넷 송신

ALB는 A·C에 걸친 **1개**다. 기본료는 `153 × 0.0225 = $3.4425`, 공인 IPv4 5개는 `5 × 153 × 0.005 = $3.825`다. ALB 확장으로 IP가 늘면 추가된다.

ALB LCU는 신규 연결·활성 연결·처리 바이트·규칙 평가 중 가장 큰 값을 사용한다. 이 예시는 EC2 대상, 지속 연결 1개/인, 분당 1회 재연결, 규칙 10개 이하이므로 **요청+응답 바이트 차원**이 가장 크다. 이벤트 30회를 새 TLS 연결 30개로 계산하지 않는다. [AWS ALB LCU](https://aws.amazon.com/elasticloadbalancing/pricing/)

`LCU/시간 = max((D+O)/45, 인원/3000, (인원/60)/25)`

`LCU 비용 = LCU/시간 × 45 × 0.008`

| 항목 | 50명 | 100명 | 150명 |
|---|---:|---:|---:|
| 처리 바이트 LCU/시간 | 11.0592 | 22.1184 | 33.1776 |
| 기간 LCU 비용 | $3.98 | $7.96 | $11.94 |
| 외부 응답량 O (GB) | 248.832 | 497.664 | 746.496 |
| 인터넷 송신, 무료량 차감 전 | $31.35 | $62.71 | $94.06 |

야간·주말 처리량은 0으로 놓았으며, 외부 스캔·추가 요청 등 실제 사용량이 있으면 LCU도 더해진다. 입력 방향 인터넷 전송은 요금 계산에서 0, 인터넷 송신은 `max(0, O−남은 무료GB) × 0.126`이다.

인터넷 무료 100GB는 서비스·리전의 집계 조건과 기존 사용량을 확인한 뒤 적용한다. 사용자 응답이 Account 1 ALB에서 나가는 이 구조에서 **계정이 5개라고 500GB를 차감하지 않는다**. 100GB 전부 남아 있는 비교는 Account 1에서 **$12.60**만 차감한다. 실제 잔액은 미조회다.

## 8. 당시 계정별 배분과 한도 — 현재 계정 배분에 적용 불가

고정 사양의 EC2 비용은 인원에 따라 변하지 않는다.

| 계정 | small / large | 45시간 EC2 비용 | 50명 EBS | 100명 EBS | 150명 EBS |
|---|---:|---:|---:|---:|---:|
| Account 1 | 3 / 1 | $7.37 | 80GiB | 80GiB | 80GiB |
| Account 2 | 1 / 2 | $9.48 | 460GiB | 760GiB | 1,060GiB |
| Account 3 | 2 / 2 | $10.53 | 680GiB | 1,080GiB | 1,380GiB |
| Account 4 | 0 / 2 | $8.42 | 240GiB | 340GiB | 340GiB |
| Account 5 | 2 / 1 | $6.32 | 560GiB | 960GiB | 1,260GiB |
| 합계 | 8 / 8 | $42.12 | 2,020GiB | 3,220GiB | 4,120GiB |

주요 경로 교차 요금은 O=D일 때 Account 1~5 각각 `0.01 × D`에 `7/3, 7/6, 5/2, 7/6, 5/2`를 곱한 값이다. ALB·IPv4·LCU·인터넷 송신은 Account 1에 합산한다. 추가 Spark 예시는 Account 2/4에 각각 `0.005D`, MySQL 예시는 Account 3/5에 각각 `0.01D`를 더한다.

| 계정 | 50명 주요 경로 | 50명 추가 예시 포함 | 100명 주요 경로 | 100명 추가 예시 포함 | 150명 주요 경로 | 150명 추가 예시 포함 |
|---|---:|---:|---:|---:|---:|---:|
| Account 1 | $57.28 | $57.28 | $98.42 | $98.42 | $139.56 | $139.56 |
| Account 2 | $21.01 | $22.25 | $29.54 | $32.03 | $38.07 | $41.80 |
| Account 3 | $29.50 | $31.99 | $43.23 | $48.20 | $55.07 | $62.54 |
| Account 4 | $15.83 | $17.07 | $20.61 | $23.10 | $23.51 | $27.24 |
| Account 5 | $23.04 | $25.53 | $36.76 | $41.74 | $48.61 | $56.08 |
| **합계** | **$146.66** | **$154.13** | **$228.55** | **$243.48** | **$304.82** | **$327.22** |

100명·150명은 Account 1이 소계만으로 $60을 넘고, 잔여 무료 송신 100GB를 적용해도 $85.82·$126.96이다. 150명은 추가 통신 예시에서 Account 3도 $62.54다. 50명은 Account 1의 $60 대비 차액이 $2.72뿐이다. 계정별 실제 기존 사용액·크레딧·미포함 비용을 더해야 하므로 한도 충족을 보장하지 않는다.

## 9. 비용을 바꾸는 항목과 성능 한계

- **CPU 초과 크레딧:** T3a Unlimited는 중지 시에도 미상환 잉여 크레딧이 청구될 수 있다. 야간 정지 중 크레딧을 회복한다고 계산하지 않는다. 기존 크레딧 0·16대 모두 45시간 CPU 100%라는 별도 예시라면 small 8대 $28.80 + large 8대 $25.20 = **$54 추가**다. 이 인원에서 실제 CPU 100%가 된다는 예측은 아니다. [Unlimited 과금 조건](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode-concepts.html), [T3a 사양](https://aws.amazon.com/ec2/instance-types/t3/)
- **응답과 방송:** 수신자 전체에게 보내는 바이트를 O에 넣는다. 전체 참가자에게 방송하거나 이미지/영상을 제공하면 사용자 수만으로 비용을 확정할 수 없다.
- **명령/확정 이벤트:** 입력 1개당 Kafka 레코드가 둘 이상이면 발행·복제·소비·보관량을 해당 토픽별로 다시 계산한다.
- **MySQL·Spark 용량:** 상태 테이블·binlog·shuffle spill·체크포인트의 유지량이 추가 100GiB를 넘으면 저장료도 더한다. 추가 전송 예시가 이 디스크 용량을 검증한 것은 아니다.
- **공인 IP:** Front 두 대의 IP를 없애 ALB로만 받으면 153시간 고정 IP 비용 **$1.53 감소**. 자동 할당 IP라면 중지 시간의 과금 조건도 달라진다.
- **추가 준비/테스트:** 16대 전체를 1시간 더 실행하면 EC2만 **$0.936 추가**다.
- **153시간 이후 보관:** 이 견적은 해당 기간만 산정했다. 19일에 원본을 삭제하라는 지시나 자동 삭제 정책은 없다. EBS·스냅샷 등을 보관하면 이후 비용을 추가한다.
- **성능:** 산술 비용과 처리 가능성은 다르다. small DB의 2GiB RAM, Kafka·Spark·게임의 CPU 크레딧, 복제/Consumer lag·EBS 지연 등을 부하 테스트해야 한다. 증설이 필요하면 단가와 대수를 다시 적용한다.

현재 mysql-3는 Account 4 Private A에 추가됐다. 본문의 2026-10-08 16대·MySQL 2대·153시간 비용 및 트래픽 모델은 flatten-1과 mysql-3 추가 전 기록으로 보존하며 현재 견적으로 사용하지 않는다. 최신 유휴 비용은 [요금 계산 기준](cost-calculator.md), 실제 ALB 복원 보류와 mysql-3 증설은 [AWS 검증 기록](../infra-routing/verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)을 따른다.
