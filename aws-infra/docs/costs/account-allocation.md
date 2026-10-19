# 현재 5개 계정의 서버·AZ·비용 배치

갱신일: 2026-10-18. AWS EC2·연결 EBS 조회와 current 프로필을 대조했다. [현재 운영 구성](../operations/current-state.md)에 서버별 주소와 검증 범위가 있다.

| 계정 / VPC | 현재 노드 | Bastion 포함 대수 | 연결 EBS GiB |
| --- | --- | ---: | ---: |
| account1 / 10.10.0.0/16 | bastion, front-a, front-b, game-server, game-server-test, ad-server, flatten-1 | 7 | 140 |
| account2 / 10.20.0.0/16 | mongo-1, spark-2 | 2 | 1,040 |
| account3 / 10.30.0.0/16 | mysql-1, mongo-2, spark-1 | 3 | 1,160 |
| account4 / 10.40.0.0/16 | kafka-1, kafka-2, mysql-3, spark-3 | 4 | 680 |
| account5 / 10.50.0.0/16 | mysql-2, mongo-3, kafka-3 | 3 | 1,260 |
| 합계 | 서비스 18대 + Bastion 1대 | 19 | 4,280 |

기본 topology에는 테스트 Backend가 없어 account1이 6대이고 전체 18대·4,260GiB다. flatten-1은 account1, kafka-1은 account4다. 모든 구성 노드는 논리 A(apne2-az1)에 있고 C 서브넷은 유지한다. Public 서버는 account1의 Front 2대와 Bastion이며 각각 EIP를 사용한다. 별도 edge-1, ALB, NAT는 현재 구성에 없다.

MySQL은 account3·4·5, MongoDB는 account2·3·5, Kafka는 account4의 2대와 account5의 1대, Spark는 account2·3·4에 있다. 3노드 클러스터라고 해서 3개 계정·AZ로 균등 분산된 것은 아니다. A 전체 장애에 대한 가용성을 보장하지 않는다.

## 비용 계산 범위

위 수량·용량은 실제 연결 자원이며 파일 사용량·새 비용 견적이 아니다. 계정별 실행 시간·EBS·IPv4 유지 시간·트래픽·CPU 크레딧·모니터링 비용이 다르므로 총액을 5로 나누지 않는다. Project 태그만으로 EBS를 조회하면 일부 연결 볼륨이 누락돼 연결 관계로 집계했다.

[일별 기록](../operations/daily-usage.md)은 10월 16일 15:30까지의 계산값이다. [비용 견적](costs.md)·[계산 기준](cost-calculator.md)·[과거 dual-AZ 시나리오](dual-az.md)는 각 계산 당시의 배치와 단가를 유지한다. 이번에는 새 단가·청구·잔액을 조회하지 않았고 과거 금액을 현재 배치로 소급 재계산하지 않았다.

## 변경과 설치

선택 프로필의 topology가 실제 Plan 입력이다. NewProfile은 기본값을 복사하며 current와 동일한 운영 환경을 복제하지 않는다. 계정·AZ·노드 이동은 데이터 이전이 아니므로 [배포 절차](../deployment-runbook.md)와 [보안규칙](../security-groups.md)을 확인한다. 서비스 설치·마운트·복제 검증은 [플랫폼](../../../aws-platform/platform/README.md) 단계다.
