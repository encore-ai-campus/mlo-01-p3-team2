# 현재 운영 구성 — 2026-10-18

확인 근거: 2026-10-18 AWS CLI의 5개 계정 EC2·연결 EBS·EventBridge Scheduler 조회, 로컬 기본 topology와 current 프로필, 게임 도메인 적용 기록. 이번 문서 작업은 AWS 변경·EC2 시작·SSH 접속·새 비용 조회를 수행하지 않았다.

## 구성 기준과 확인 범위

- **운영/current:** 서비스 18대 + Bastion 1대 = EC2 19대. 조회 당시 모두 stopped다.
- **저장소 기본 topology:** 서비스 17대 + Bastion 1대 = 18대. game-server-test는 로컬 current 프로필에만 추가돼 있다.
- 모든 노드의 구성상 배치는 논리 A(apne2-az1)다. C 서브넷은 유지하지만 현재 노드는 배치하지 않는다.
- 5개 VPC, Peering 10개, NAT 0개, ALB 비활성. 별도 edge-1 EC2는 없다.
- 프로필·생성 인벤토리는 Git 제외 대상이다. 기본값으로 NewProfile을 실행해도 운영의 테스트 Backend나 도메인 선택이 자동 복제되지 않는다.

## 계정과 서버

| 계정 | 노드 | 사양 | 사설 IP |
| --- | --- | --- | --- |
| account1 | bastion | t3a.small | 10.10.0.152 |
| account1 | front-a | t3.small | 10.10.0.242 |
| account1 | front-b | t3.small | 10.10.0.181 |
| account1 | game-server | t3.large | 10.10.10.152 |
| account1 | game-server-test | t3.2xlarge | 10.10.10.166 |
| account1 | ad-server | t3.large | 10.10.10.20 |
| account1 | flatten-1 | t3a.medium | 10.10.10.130 |
| account2 | mongo-1 | t3a.small | 10.20.10.210 |
| account2 | spark-2 | t3a.large | 10.20.10.174 |
| account3 | mysql-1 | t3a.small | 10.30.10.111 |
| account3 | mongo-2 | t3a.small | 10.30.10.248 |
| account3 | spark-1 | t3a.large | 10.30.10.113 |
| account4 | mysql-3 | t3a.small | 10.40.10.240 |
| account4 | kafka-1 | t3a.large | 10.40.10.109 |
| account4 | kafka-2 | t3a.large | 10.40.10.90 |
| account4 | spark-3 | t3a.large | 10.40.10.213 |
| account5 | mysql-2 | t3a.small | 10.50.10.205 |
| account5 | mongo-3 | t3a.small | 10.50.10.197 |
| account5 | kafka-3 | t3a.large | 10.50.10.34 |

Account 1/2/3/4/5의 대수는 7/2/3/4/3이다. 기존 game-server는 삭제·대체하지 않았다. 현재 게임 연결은 game-server-test를 사용하며 영구 사양 변경 결정과 구분한다. IP는 생성·교체 후 다시 확인한다.

## EBS와 공인 주소

프로젝트 EC2에 **연결된 볼륨** 기준으로 31개, 합계 **4,280GiB**다. account1~5는 각각 140/1,040/1,160/680/1,260GiB다. Project 태그만으로 조회하면 태그 없는 일부 연결 볼륨이 빠지므로 EC2 연결 관계로 집계했다. 기본 18대 구성의 선언량은 4,260GiB다. 볼륨 용량은 파일 사용량이나 마운트 성공을 뜻하지 않는다.

Front A EIP는 43.203.25.153, Front B는 43.202.118.80, Bastion은 54.117.44.140이다. Bastion도 EIP를 사용한다. 중지해도 EBS·EIP는 유지되며 과금 종료를 뜻하지 않는다.

## 게임 도메인과 배포 코드

정식 게임 주소는 [https://bootcampmetaverse.site](https://bootcampmetaverse.site)다. 10월 17일 EC2 적용과 이후 로그인 HTTP 200 확인은 [도메인 운영 기록](history/2026-10-17-game-domain.md)에 연결한다. 현재는 EC2가 꺼져 있으므로 접속 성공을 보장하는 실시간 상태 문서가 아니다.

HTTP 80은 ACME 검증 경로를 제공하고 일반 요청은 도메인으로 이동한다. IP HTTPS도 도메인으로 이동하며 이동용 IP 인증서를 유지한다. 도메인 HTTPS는 / → 127.0.0.1:8004, /static/ → /var/www/playdata-campus/static/, /ws/campus/ → 선택 Backend:8000, /api/ads/ → 503 ads_disabled다. 광고 Front는 기존 IP HTTPS 방식을 유지한다.

10월 18일 로컬 edge 역할에 이 구조를 반영했다. 도메인 인증서와 IP 인증서를 기존 갱신 타이머에서 함께 갱신한다. 기존 서버의 수동 도메인 갱신 타이머는 자동 삭제하지 않는다. 새 코드는 로컬 검증만 완료했으며 EC2에 재배포하지 않았다. [설정 예제](../../infra/config/game-front-domain.example.json)를 기존 platform.json에 병합하고 [배포 안내](../deployment-runbook.md)를 따른다. 앱·정적 파일·ALLOWED_HOSTS·CSRF 설정은 별도 배포 사항이다.

## 접속 제한

Front HTTP 80은 인증서 검증을 위해 0.0.0.0/0을 허용한다. HTTPS 443은 222.112.208.66/32~222.112.208.72/32의 7개 IP를 허용한다. 10월 18일 게임용 임시 HTTPS 전체 공개는 제거됐다. 80의 기존 전체 허용과 443의 임시 전체 허용을 구분한다. Nginx 임시 허용 제거용 Persistent 타이머는 다음 부팅 때도 정리되도록 유지했다.

## 자동 기동·중지

5개 계정의 aws-infra-office-hours 그룹에서 시작 예약 이름은 ec2-start-0900이지만 실제 실행은 **평일 08:30 Asia/Seoul**이다. ec2-stop-2200은 **매일 22:00 Asia/Seoul**이다. 둘 다 ENABLED다. 이름이 아니라 ScheduleExpression과 시간대를 확인한다.

예약 대상은 기존 18대이며 **game-server-test는 시작·중지 예약 모두 제외**돼 있다. 수동 전체 중지는 예약을 비활성화하지 않는다. power-all.ps1의 current 대상은 테스트 서버를 포함한 19대이므로 예약과 범위가 다르다. 이번 문서 작업은 예약을 변경하지 않았다.

## 비용·서비스 검증의 경계

비용 집계는 [통합 비용계산](daily-usage.md)의 사용자 제공 실제 금액 **91,782원(10월 16일 16:30 KST)**을 새 누적 기준으로 사용한다. 10월 18일 24:00까지 이후 중지를 가정한 추가 추정 약 44,418원을 더해 예상 누적은 **약 136,200원**이다. 이전 추정 $107.37은 보관 이력으로만 남긴다. AWS 청구 상세를 직접 조회한 것은 아니다.

오늘 Front 로그인과 Backend·MySQL 서비스 실행은 이전 전원 작업에서 확인했지만 MySQL 복제 상태는 인증 문제로 확인하지 못했다. 중지 상태에서는 DB 복제·Spark·Kafka 정상 동작을 주장하지 않는다. CloudWatch RAM 수집은 과거 제안·취소 기록과 실제 지표 수신을 구분한다.

compute의 현재 데이터 EBS lifecycle은 prevent_destroy=false다. 삭제 실행기의 DeleteDataVolumes 검사와 이 값은 별개이며 문서 동기화로 보호 설정을 바꾸지 않았다.
