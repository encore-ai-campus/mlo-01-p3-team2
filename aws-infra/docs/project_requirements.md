# AWS 인프라 요구사항과 현재 구현의 경계

문서 갱신: 2026-10-13. 아래 현재 구현은 로컬 코드·설정과 라우팅 문서에 근거한다. 과거 대화의 요구사항과 실제 배포 성공 여부를 동일하게 취급하지 않는다.

## 1. 프로젝트 목적

게임 이벤트를 Kafka로 수집하고 Spark로 처리하며 MongoDB에 원본을 보관하는 EC2 기반 플랫폼이다. 게임·광고 애플리케이션의 모든 쓰기를 Kafka로 보내려는 요구는 애플리케이션 구현 사항이다. 보안그룹과 설치 플레이북만으로 그 경로를 보장하지 않는다.

## 2. 운영·예산 요구

서울 리전의 AWS 계정 5개를 사용하며 모든 서버를 논리 A(apne2-az1)에 배치한다. A·C 서브넷과 공통 AZ 설정은 유지한다. 과거 운영 일정은 2026-10-13·14·15·16·19, 매일 09:00~18:00의 총 45시간이다. 계정당 최초 크레딧 $60, 총 $300과 19일 이후 만료 조건은 사용자 답변 기록이며 현재 잔액·정확한 만료 시각은 미확인이다. 준비·테스트 비용과 운영 후 자원 보관료도 계정별 예산에 포함해야 한다.

50·100·150명, 1인당 초당 30개 이벤트는 견적 시나리오다. 서버가 이 부하를 처리한다는 성능 검증 결과가 아니다. 원본을 계속 보관하려는 의도는 유지하지만 백업·장기 보관·삭제 시점은 별도 결정 사항이다.

## 3. 현재 기본 서버 구성

[현재 구성](../README.md#서버-수와-사양)은 서비스 17대와 선택적 배스천 1대다. Account 1은 게임 Front(front-a)·광고 Front(front-b)·game·ad와 별도 배스천을, Account 2는 Mongo-1·Spark-2와 평탄화 Consumer flatten-1을 가진다. flatten-1은 t3a.medium, Private A(apne2-az1), role=consumer이며 Kafka 세 브로커의 9092에 접속한다. 프로그램 배포는 별도다. MySQL 3대·MongoDB 3대·Kafka 3대·Spark 3대이며 크기·대수는 배포 프로필에서 변경할 수 있다. 계정별 자원·통신 비용이 균등하다는 보장은 없다.

인프라에는 MySQL EC2 세 대가 선언돼 있다. mysql-3는 Account 4 Private A의 t3a.small이며 2026-10-10 current 프로필의 EC2·디스크·SG를 실제 반영했다. [플랫폼 MySQL 역할](../../aws-platform/platform/docs/platform-routing/roles/mysql/README.md)은 3~9대의 InnoDB Cluster를 요구한다. 인벤토리 재생성·Proxy·데이터 마운트·OS 방화벽·Cluster 설치와 장애 전환 검증은 별도다. 기존 ReplicaSet은 이전 구현이며 자동 데이터 이전은 제공하지 않는다. Spark는 Master 2개·Worker 3개, ZooKeeper ensemble 3개다. Kafka는 Broker/Controller 3개, MongoDB는 Replica Set 3개다. 모든 서버를 AZ A에 둔 배치는 A 전체 장애에서도 클러스터 가용성을 보장하지 않는다.

Account 1의 게임·광고 Front는 Public A의 t3.small, 게임·광고 Backend는 Private A의 t3.large다. 다른 역할은 기존 t3a.small / t3a.medium / t3a.large를 사용한다. OS 20GiB/대, 데이터 EBS 합계 3,900GiB, 선택 Bastion을 포함한 전체 EBS 4,260GiB는 현재 설정 값이다. 데이터 EBS 포맷·마운트가 자동화되지 않았으므로 별도 볼륨을 만들었다는 사실만으로 서비스 데이터가 그 볼륨에 저장된다고 판단하지 않는다.

## 4. 네트워크와 다운로드

VPC CIDR은 10.10·20·30·40·50.0.0/16이다. 기본 및 current 설정의 ALB는 비활성화돼 있다. 게임 Front→game, 광고 Front→ad TCP 8000만 Backend 수신에 허용한다. 두 Front의 TCP 80·443은 0.0.0.0/0에 공개하며, 각각 Nginx·Certbot으로 자기 공인 IP의 HTTPS를 처리하는 설치 코드가 있다. HTTP는 ACME 검증 경로 외 요청을 HTTPS로 리다이렉트하고 /static/·/assets/도 해당 Backend로 전달한다. 광고 Front 본문 제한은 3m, 게임 Front는 기본 1m이다. 실제 인증서 발급·앱 응답 성공은 별도 검증한다.

기본 NAT는 0개다. 배스천의 Squid TCP 3128을 통해 사설 서버가 HTTPS 저장소·파일을 다운로드한다. Account 1의 Front 2대에만 EIP를 할당하고 배스천은 자동 공인 IP를 사용한다. 계정 간 서비스 연결은 Peering과 역할별 보안그룹을 사용한다. 포트 범위는 [보안그룹 안내](security-groups.md)를 따른다.

## 5. 자동화가 하는 일

Terraform은 foundation·connectivity·workload·bastion 상태를 분리해 서버와 네트워크를 생성한다. deploy.ps1의 Inventory는 실제 서버 주소와 계정별 키를 Ansible 인벤토리로 연결한다. Proxy는 Squid·APT·다운로드 환경을 준비한다. Deploy나 Proxy를 마쳤다고 MySQL·Kafka·Spark 설치가 끝난 것은 아니다.

플랫폼의 site.yml 역할별 실행에서 서비스를 설치한다. zookeeper 태그만 실행하면 Spark 설치는 진행되지 않으므로 zookeeper,spark를 함께 선택한다. game·ad 애플리케이션은 현재 설치 역할이 없고, backend·monitoring은 해당 인벤토리 그룹이 있어야 실행된다. Ubuntu 프록시 준비 단계의 지원 조건은 Ubuntu 24.04 amd64다.

## 6. 삭제와 데이터 보관

현재 compute 데이터 EBS의 prevent_destroy는 true다. 전체 삭제 실행기는 명시적 데이터 삭제 선택을 요구한다. Plan·Apply는 소스의 보호 설정을 자동 변경하지 않는다. 단일 Destroy에 DisableDataVolumeProtection을 지정하면 Plan 전에 임시 해제하고 종료 시 원본으로 복원한다. EBS·서비스 상태·키를 삭제하는 작업과 문서 정리는 별개다. 실제 삭제 범위와 순서는 [실행 안내](deployment-runbook.md)를 따른다.

## 7. 확인이 필요한 범위와 관련 문서

실제 계정 잔액·AMI 제공·AZ 배치·서비스 복제·장애 복구·부하·데이터 보관 정책은 별도 확인한다. 문서의 과거 로컬 테스트 기록은 새로 생성한 EC2의 검증 결과가 아니다.

- [프로젝트 개요](../README.md), [배포·설치 실행 안내](deployment-runbook.md)
- [현재 자원과 과거 비용 견적](costs/costs.md), [상세 과거 견적](costs/dual-az.md)
- [코드 탐색용 라우팅 문서](infra-routing/ROUTING-README.md), [플랫폼 설치 안내](../../aws-platform/platform/README.md)

아래 기록은 당시 사용자 답변과 설계 논의의 이력이다. 초기 MySQL 3대·medium 사양·NAT 등 과거 결정 항목이 현재 코드와 다를 수 있으며, 현재 구현을 설명하는 명령이나 배치로 재사용하지 않는다. 이번 문서 정리를 새 설계 승인으로 기록하지 않는다.

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
