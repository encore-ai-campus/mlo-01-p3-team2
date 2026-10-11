# 서버 설치·배포 경계

Terraform은 EC2·디스크·네트워크·역할 메타데이터(/etc/aws-infra/node.json)까지 구성한다. 프로그램 설치는 [platform](../../../aws-platform/platform/README.md), 운영자가 실행할 순서는 [배포 절차](../../docs/deployment-runbook.md)에 있다.

## 생성·연결·설치 구분

- infra.ps1의 workload Output은 서비스 서버·디스크·ALB 정보를 저장한다. Bastion 주소는 별도 bastion 출력에서 확인한다.
- deploy.ps1 Inventory는 Terraform이 소유한 EC2의 현재 IP를 조회해 플랫폼의 hosts.구성이름.yml을 만든다. 계정별 목적지 키와 Bastion 인증 키를 구분한다.
- deploy.ps1 Proxy 또는 aws-platform/platform/scripts/setup-proxy.sh는 Squid·APT·다운로드 준비만 수행한다.
- site.yml의 MySQL·MongoDB·Kafka·ZooKeeper·Spark 역할을 실행해야 해당 서비스가 설치된다. 현재 MySQL 역할은 3~9대 Cluster를 요구하며 인프라 기본값도 세 대다. mysql-3를 포함한 인벤토리·새 서버 데이터 마운트·Proxy·방화벽 준비 후 설치한다. Cluster 준비 후 game·Spark·선택 backend에 mysql_router 태그로 로컬 Router를 설치한다. zookeeper 태그만 실행하면 spark-worker.service는 배포되지 않는다.

기본 Output 캐시는 infra/.local/계정/단계/outputs.json이다. 구성별 배포에서는 infra/.local/profiles/구성경로해시/계정/단계/outputs.json으로 분리되지만 원격 상태는 공유한다.

## 현재 통신 설정

| 역할·경로 | TCP 포트 |
| --- | --- |
| 외부 → ALB | 허용한 game_client_cidrs의 HTTP 80 |
| ALB → Front | 80, /static/* |
| ALB → game / ad | 8000, 기본 / /ads/* |
| Kafka 클라이언트·복제 / controller | 9092 / 9093 |
| MongoDB / MySQL | 27017 / 3306 |
| Spark Master RPC / 내부 Master UI | 7077 / 8080 |
| Spark Worker RPC | 7100 |
| Spark 작업 Driver / BlockManager | 7078–7094 / 7079–7095 |
| ZooKeeper 클라이언트 / 동기화 / 선출 | 2181 / 2888 / 3888 |
| 사설 서버 → Bastion Proxy / Bastion → 인터넷 | 3128 / HTTPS 443 |

Spark 작업은 포트 재시도 16회, Master·Worker 데몬은 0회를 사용한다. Worker UI 8081은 데몬 설정에 있지만 원격 공개 SG 규칙은 없다. 포트 변경 시 [traffic](../config/traffic.tfvars.json), 선택한 비용 프로필의 복사본과 [Spark 기본 변수](../../../aws-platform/platform/roles/spark/defaults/main.yml)를 함께 맞춘다. HTTP ALB가 TLS·실제 앱 경로·헬스 체크 성공을 대신하지 않는다.

## Proxy와 SSH

Proxy는 Peering으로 다른 VPC의 NAT를 공유하거나 Private 기본 라우트를 Bastion에 지정하는 방식이 아니다. 클라이언트가 Bastion의 사설 주소:3128에 요청하고 Squid가 별도 인터넷 연결을 만든다. Ubuntu 24.04 x86_64의 Squid·프로젝트 ACL·HTTPS 저장소·APT·원격 다운로드 환경을 [프록시 스크립트](../../../aws-platform/platform/scripts/setup-proxy.sh)로 준비한다. Terraform만 적용한 서버에 자동으로 apt가 준비되는 것은 아니다.

SSH는 운영 PC의 키로 Bastion을 경유한다. 개인키를 Bastion에 복사할 필요가 없다. 생성 인벤토리의 ProxyCommand는 Bastion 키와 대상 계정 키를 각각 지정한다. OS 사용자·권한·sudo는 플랫폼 단계의 역할이다.

## 데이터와 애플리케이션

데이터 EBS는 생성·연결만 하며 포맷·마운트·파일시스템 확장은 자동화하지 않았다. MySQL /var/lib/mysql, Ubuntu MongoDB /var/lib/mongodb, Kafka /var/lib/kafka/data, Spark /var/lib/spark, ZooKeeper /var/lib/zookeeper가 실제 사용할 디스크를 설치 전에 확인한다. 마운트가 없으면 OS 디스크에 데이터가 기록된다. 현재 라우팅 문서 기준 compute의 prevent_destroy=true는 데이터 EBS 삭제·교체 보호이며 백업이나 데이터 이전 기능은 아니다.

Front·game·ad 애플리케이션, Kafka 업무 Consumer, Spark 업무 잡과 원본 장기 보관·백업·복구·데이터 이전은 별도다. 전체 인프라 삭제 기능은 이 폴더가 아닌 [destroy-all.ps1](../scripts/destroy-all.ps1)에 있으며 데이터 EBS도 삭제할 수 있다.
