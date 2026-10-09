# 설정 파일 지도

[탐색 시작점](../ROUTING-README.md) · [model 검증](../terraform/README.md#model) · [공통 입력 검사](../scripts/lib/infra-common.ps1.md)

## 파일별 책임

| 파일 | 주요 키 | 읽는 곳 |
| --- | --- | --- |
| [infra/config/topology.tfvars.json](../../../infra/config/topology.tfvars.json) | topology.project / region / az_ids / accounts / nodes / peerings / alb | 실행기 및 세 stack의 model |
| [infra/config/traffic.tfvars.json](../../../infra/config/traffic.tfvars.json) | traffic.admin_public_cidrs / game_client_cidrs / ports / connections / internet_https_roles | 실행기·model·workload |
| [infra/config/backend.json](../../../infra/config/backend.json) | bucket / region / profile / key_prefix | 실행기의 init, connectivity/workload의 원격 상태 조회 |
| [infra/config/keys/account1.pub](../../../infra/config/keys/account1.pub) | OpenSSH 공개키 | 해당 계정 workload의 aws_key_pair |

JSON에는 주석이나 AWS 액세스 키·시크릿 키를 넣지 않는다. 공개키 상대 경로의 기준은 **infra/**다.

## topology

| 키 | 의미·현재 값 |
| --- | --- |
| project / region | aws-infra / ap-northeast-2 |
| az_ids | 논리 a = apne2-az1, c = apne2-az3. 계정 콘솔의 AZ 끝 글자와 구분 |
| accounts | id, profile, vpc_cidr, public_subnets, egress, ami_id, ssh_public_key_path, key_pair_name |
| nodes | 고정 서버 키별 account, role, az, subnet_tier, instance_type, root_gib, public_ip, data_disks |
| nodes.*.data_disks | 디스크 키별 size_gib, type, device_name. 현재 gp3 |
| peerings | account1-account2 같은 정렬된 계정 쌍 10개 |
| alb | enabled, account, certificate_arn, frontend_role, game_role, static_path, 두 health_path |

| 계정 | VPC | 현재 노드 | Public 서브넷 / egress |
| --- | --- | --- | --- |
| account1 | 10.10.0.0/16 | bastion, front-a, front-b, game-server | true / proxy |
| account2 | 10.20.0.0/16 | mongo-1, spark-2, ad-server | false / proxy |
| account3 | 10.30.0.0/16 | kafka-1, mysql-1, spark-1, mongo-2 | false / proxy |
| account4 | 10.40.0.0/16 | kafka-2, spark-3 | false / proxy |
| account5 | 10.50.0.0/16 | mysql-2, mongo-3, kafka-3 | false / proxy |

노드명과 data_disks의 키는 Terraform for_each 식별자다. 이름 변경이나 계정·AZ 이동은 단순 표시 변경이 아니며 생성·교체·이전 계획을 확인해야 한다. 세부 노드 사양표는 [기존 실행 안내](../../../infra/scripts/README.md)에 있다.

## traffic

connections는 소스 역할 목록·대상 역할 목록·ports의 키를 지정한다. model이 이를 계정/역할 SG 쌍으로 펼치고 workload가 해당 계정의 입출력 규칙을 만든다. 이 설정은 통신 허용이며 애플리케이션의 처리 경로를 강제하지 않는다.

| 연결 키 | 소스 → 대상 | 현재 TCP 포트 |
| --- | --- | --- |
| alb_front / alb_game | ALB → frontend / game | 80 / 8000 |
| admin_nodes | bastion → 나머지 서버 역할 | 22 |
| game_kafka / spark_kafka | game·ad / spark → kafka | 9092 |
| kafka_replication / kafka_controller | kafka → kafka | 9092 / 9093 |
| mongo_replication / mysql_replication | mongo → mongo / mysql → mysql | 27017 / 3306 |
| spark_mongo / spark_mysql | spark → mongo / mysql | 27017 / 3306 |
| game_mysql | game → mysql | 3306 |
| spark_master / spark_driver / spark_block | spark → spark | 7077 / 7078 / 7079 |
| forward_proxy | frontend·game·mongo·spark·ad·kafka·mysql → bastion | 3128 |

admin_public_cidrs와 game_client_cidrs는 현재 빈 배열이다. internet_https_roles에는 bastion만 있어 그 역할에 외부 TCP 443 egress를 만든다. game→MySQL 허용 규칙은 코드상 존재하지만, DB 직접 쓰기나 읽기 중 무엇을 수행하는지는 보안규칙으로 구분하지 않는다.

## backend와 아직 비어 있는 입력

현재 backend는 bucket이 비어 있고 region은 ap-northeast-2, profile은 account1, key_prefix는 aws-infra-v2다. 버전 관리가 켜진 기존 S3 버킷을 지정해야 Plan·Apply·Output을 진행할 수 있다.

모든 계정의 ami_id와 ALB certificate_arn이 비어 있다. Account 1 공개키만 경로가 있고 Account 2~5의 ssh_public_key_path는 비어 있다. 이 값들은 배포 준비 상태를 의미하며 문서가 자동으로 채우거나 AWS 값을 조회하지 않는다.

| 변경 종류 | 확인할 단계 |
| --- | --- |
| 사양·같은 AZ의 데이터 디스크 용량 | 해당 계정 workload. 파일시스템 확장은 별도 |
| 서버 계정·AZ·역할·VPC·송신 방식 | 관련 foundation → connectivity → workload, 데이터 이전 검토 |
| 관리자 IP·서비스 연결·포트 | 규칙 양끝 계정 workload. 프로그램 포트도 별도 조정 |
| ALB 경로·대상 역할·활성화 | ALB 계정 workload. 역할 집합이 바뀌면 foundation도 확인 |
| backend 버킷·prefix | 상태 위치와 이관 검토. 값을 바꿔도 기존 상태가 자동 이전되지 않음 |
