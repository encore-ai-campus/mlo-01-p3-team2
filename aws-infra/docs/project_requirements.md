# AWS 인프라 요구사항과 현재 구현의 경계

문서 갱신: 2026-10-18. 현재 운영 기준은 [AWS 조회와 코드 대조 기록](operations/current-state.md)이다. 요구사항, 기본 코드, 로컬 current 프로필, 실제 서비스 검증을 구분한다.

## 1. 프로젝트 목적

게임 이벤트를 Kafka로 수집하고 Spark로 처리하며 MongoDB에 원본을 보관하는 EC2 플랫폼이다. 모든 애플리케이션 쓰기를 Kafka로 보내려는 요구는 앱 구현 사항이며 SG·설치 플레이북만으로 보장하지 않는다. 50·100·150명과 1인당 초당 30개 이벤트는 견적 시나리오이고 성능 검증 결과가 아니다.

## 2. 운영·예산 요구

서울 리전의 AWS 계정 5개와 논리 A(apne2-az1)를 사용하며 C 서브넷은 유지한다. 과거 45시간·126시간 운영안은 이력이다. 현재 예약은 평일 08:30 시작, 매일 22:00 중지이며 기존 18대만 대상이다. 추가 game-server-test는 수동 관리한다. 19일 이후 종료·삭제를 자동 보장하지 않는다.

계정당 최초 크레딧 $60·총 $300과 만료 조건은 과거 사용자 답변이다. 현재 잔액·정확한 만료 시각을 새로 확인하지 않았다. 계산된 비용은 [일별 기록](operations/daily-usage.md)에 모으며 유지 EBS·EIP, 미기록 실행 구간과 실제 청구를 구분한다.

## 3. 현재 기본 서버 구성

저장소 기본 topology는 서비스 17대와 Bastion 1대다. 실제 운영/current는 game-server-test(t3.2xlarge)를 추가한 **19대**다. 기존 game-server(t3.large)는 보존하며 현재 게임 연결이 테스트 서버를 선택한 것이 영구 교체 결정을 뜻하지 않는다.

Account 1은 게임·광고 Front, 기존 게임·테스트 게임·광고 Backend, flatten-1, Bastion이다. Account 2는 Mongo-1·Spark-2, Account 3은 MySQL-1·Mongo-2·Spark-1, Account 4는 Kafka-1·Kafka-2·MySQL-3·Spark-3, Account 5는 MySQL-2·Mongo-3·Kafka-3다. [계정 배치](costs/account-allocation.md)를 따른다.

MySQL·MongoDB·Kafka·Spark는 각각 3대다. MySQL 역할은 InnoDB Cluster 3~9대와 로컬 Router를 지원한다. Spark Master 2·Worker 3, ZooKeeper ensemble 3 구성이다. 모든 노드를 A에 두므로 A 전체 장애에 대한 가용성을 보장하지 않는다. 설치·복제·장애 전환은 별도 검증이다.

Front는 t3.small, 기존 게임·광고 Backend는 t3.large, 테스트 Backend는 t3.2xlarge다. OS는 20GiB/대이며 current의 연결 EBS는 합계 4,280GiB다. 기본 18대 구성은 4,260GiB다. 연결 용량은 데이터 마운트·사용량 검증 결과가 아니다.

## 4. 네트워크와 다운로드

VPC는 10.10·20·30·40·50.0.0/16이며 Peering 10개, NAT 0개, ALB 비활성이다. Front 2대와 Bastion에 각각 EIP를 사용한다. 사설 서버의 다운로드는 Bastion Squid:3128을 사용한다. 역할별 통신은 [보안규칙](security-groups.md)을 따른다.

게임 정식 접속 주소는 https://bootcampmetaverse.site 이며 EC2에 적용했다. IP HTTPS는 도메인으로 이동한다. Front 앱은 127.0.0.1:8004, WebSocket은 선택한 게임 Backend:8000이다. 광고 Front는 기존 IP 방식이다. 게임 HTTP는 ACME 외 요청을 도메인으로 이동하고 광고의 현재 배포 템플릿은 일반 HTTP 요청에 404를 반환한다.

Front 80은 인증서 검증용 전체 IPv4, 443은 지정한 7개 /32만 허용한다. 임시 0.0.0.0/0 HTTPS 허용은 영구 구성에 포함하지 않는다. 광고 본문 제한 3m, 게임 1m을 유지한다.

## 5. 자동화가 하는 일

Terraform은 foundation·connectivity·workload·bastion 상태로 서버·네트워크를 관리한다. deploy.ps1의 Deploy는 Terraform → Inventory → Proxy까지이며 앱·DB·HTTPS 설치 완료를 뜻하지 않는다. HTTPS는 edge.yml 또는 site.yml의 edge 역할로 별도 적용한다.

게임 도메인과 Backend 선택은 platform.json의 frontend_domains·frontend_backend_nodes에 선언한다. [예제](../infra/config/game-front-domain.example.json)를 기존 프로필에 병합한다. 프로필은 Git 제외 대상이며 새 프로필에 자동 복사되지 않는다. 10월 18일 도메인 재현 코드는 로컬 검증을 마쳤지만 EC2 재배포는 하지 않았다. 앱·정적 파일·환경 변수는 별도 준비한다.

## 6. 삭제와 데이터 보관

현재 compute 데이터 EBS의 prevent_destroy는 false다. 전체 삭제 실행기의 명시적 데이터 삭제 선택과 계획 검사는 별도다. true인 구성에서만 DisableDataVolumeProtection의 임시 해제·복원 의미가 있다. [실행 안내](deployment-runbook.md)와 실제 계획을 확인한다. 원본 보관·백업·삭제 시점은 별도 결정 사항이다.

## 7. 확인이 필요한 범위와 관련 문서

실제 청구·잔액, MySQL 복제·장애 복구, Kafka/Spark 연동, 부하 성능은 이번 문서 작업에서 재검증하지 않았다. 중지·시작 성공과 서비스 데이터 정상 상태를 동일시하지 않는다.

- [프로젝트 개요](../README.md), [현재 운영 구성](operations/current-state.md)
- [배포 안내](deployment-runbook.md), [전원·예약](operations/ec2-power.md)
- [플랫폼](../../aws-platform/platform/README.md), [코드 지도](infra-routing/ROUTING-README.md)

아래는 당시 결정 이력이며 현재 코드·운영 상태보다 우선하지 않는다.

## 8. 과거 결정 기록

추가 답변이 나오면 해당 항목의 상태를 갱신하고 아래에 결정 근거를 남긴다. 제안만 나온 항목은 확정으로 기록하지 않는다.

| 날짜 | 항목 | 결정 내용 | 근거 |
|---|---|---|---|
| 2026-10-07 | 최초 요구사항 정리 | 기존 대화의 사용자 답변을 기준으로 확정 조건·잠정안·미확인 정보를 기록 | 사용자가 제공한 대화 |
| 2026-10-07 | 운영 일정 갱신 | 평일 5일, 매일 09:00~18:00, 총 45시간. 10월 13일 시작 예정에 따라 13·14·15·16·19일로 계산 | 사용자의 운영 시간·시작일 추가 답변 |
| 2026-10-07 | 시작일·가용 영역 확정 | 10월 13일 시작을 확정하고 가용 영역 2개로 운영. 기존 비용 비교 문서를 선택한 구성의 견적으로 통합 | 사용자 추가 답변 및 ‘1번’ 의미 확인 |
| 2026-10-08 | 광고 서버 추가 | 별도 EC2 1대 추가. 당시 MySQL 1대 기준 전체 EC2 14대였으며 이후 아래 결정으로 갱신 | 사용자 광고 서버 추가 요청 |
| 2026-10-08 | MySQL 클러스터 정정 | EC2 3대로 MySQL 클러스터 직접 구성. 전체 EC2 16대(서비스용 15대 + Bastion 1대) | 사용자 ‘EC2 3대로 MySQL 클러스터 직접 구성’ 답변 |
| 2026-10-08 | Kafka 우선 쓰기 | 로그인·계정 변경·게임 상태 변경까지 모든 애플리케이션 쓰기를 Kafka 경유로 처리 | 사용자 ‘로그인·게임 상태 변경까지 모든 쓰기를 Kafka 경유’ 답변 |
| 2026-10-08 | 초기 사양 선택 | Frontend·Bastion t3.small, MongoDB·MySQL t3.medium, Kafka 3대·Spark Worker 2대 t3.large. 선택표 밖의 Master·Backend·광고는 기존 medium 계산값 유지 | 사용자가 추천표를 선택해 README 수정·비용 재계산 요청 |
| 2026-10-08 | 5개 계정 균등 배치 설계 | 5개 계정의 지출을 비슷하게 하려는 요구. 사양·총량을 유지하고 계정별 기본 비용 약 $24.06~$25.90, MongoDB·Kafka·MySQL 각각 3개 계정에 분산하는 새 배치 제안 | 사용자 계정별 금액을 비슷하게 나누는 설계·문서화 요청 |

이번 MySQL 증설의 [AWS 검증 기록](infra-routing/verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)을 현재 상태 근거로 추가했다. 당시에는 ALB 설정을 활성화한 채 재생성을 보류했다. 이후 2026-10-11 사용자 요청으로 기본 및 current 설정의 ALB와 전용 연결을 제거했다. AWS 적용은 하지 않았으며 다른 프로필은 별도 확인한다.

과거 기록: 2026-10-11에는 edge-1을 추가했다. 2026-10-13 현재 설정에서는 edge-1을 제거하고 두 Front가 HTTPS를 각각 담당한다. 과거 배포 결과는 현재 Front 구성의 실제 적용 완료를 뜻하지 않는다.
