# 설정 파일 지도

[탐색 시작점](../ROUTING-README.md) · [model 검증](../terraform/README.md#model) · [공통 입력 검사](../scripts/lib/infra-common.ps1.md)

## 파일별 책임

| 파일 | 주요 키 | 읽는 곳 |
| --- | --- | --- |
| [infra/config/topology.tfvars.json](../../../infra/config/topology.tfvars.json) | topology.project / region / az_ids / accounts / nodes / peerings / alb | 실행기 및 네 stack의 model |
| [infra/config/traffic.tfvars.json](../../../infra/config/traffic.tfvars.json) | traffic.admin_public_cidrs / game_client_cidrs / ports / connections / internet_https_roles | 실행기·model·workload |
| [infra/config/backend.json](../../../infra/config/backend.json) | bucket / region / profile / key_prefix | 실행기의 init, connectivity/workload/bastion의 원격 상태 조회 |
| [account1.pub](../../../infra/config/keys/account1.pub), [account2.pub](../../../infra/config/keys/account2.pub), [account3.pub](../../../infra/config/keys/account3.pub), [account4.pub](../../../infra/config/keys/account4.pub), [account5.pub](../../../infra/config/keys/account5.pub) | 계정별 OpenSSH 공개키 | 각 계정 workload의 aws_key_pair, Account 1 bastion의 전용 aws_key_pair |

JSON에는 주석이나 AWS 액세스 키·시크릿 키를 넣지 않는다. 공개키 상대 경로의 기준은 **infra/**다.

## topology

비용별로 편집할 복사본은 [deploy.ps1 NewProfile](../scripts/deploy.ps1.md)로 infra/config/profiles/구성이름 아래에 만든다. topology·traffic·platform.json을 함께 보관하며 이 폴더는 Git에서 제외한다. 구성별 EC2 배치·사양을 선택해 기존 동일 원격 상태에 반영하고, backend.json과 공개키 상대 경로의 infra 기준은 유지한다. 현재 infra/config의 원본 파일은 NewProfile이 수정하지 않는다.

[infra/.gitignore](../../../infra/.gitignore)는 .local/·Terraform 작업 폴더·상태·계획, 개인키와 로컬 설정·구성 프로필을 제외한다. Python 검사 도구가 만드는 __pycache__/와 *.py[cod]도 제외한다. Terraform 의존성 잠금 파일 .terraform.lock.hcl과 config/keys/*.pub 공개키는 이 규칙의 제외 대상이 아니다.

| 키 | 의미·현재 값 |
| --- | --- |
| project / region | aws-infra / ap-northeast-2 |
| az_ids | 논리 a = apne2-az1, c = apne2-az3. 계정 콘솔의 AZ 끝 글자와 구분 |
| accounts | id, profile, vpc_cidr, public_subnets, egress, ami_id, ssh_public_key_path, key_pair_name |
| nodes | 고정 서버 키별 account, role, az, subnet_tier, instance_type, root_gib, public_ip, data_disks |
| nodes.*.data_disks | 디스크 키별 size_gib, type, device_name. 현재 gp3 |
| peerings | account1-account2 같은 정렬된 계정 쌍 10개 |
| alb | enabled, account, frontend_role, game_role, ad_role, static_path, ad_path, frontend_health_path, game_health_path, ad_health_path. certificate_arn은 공통 타입에 남아 있으나 현재 HTTP 배포에는 사용하지 않음 |

| 계정 | VPC | 현재 노드 | Public 서브넷 / egress |
| --- | --- | --- | --- |
| account1 | 10.10.0.0/16 | bastion, front-a, front-b, game-server, ad-server | true / proxy |
| account2 | 10.20.0.0/16 | mongo-1, spark-2, flatten-1 | false / proxy |
| account3 | 10.30.0.0/16 | kafka-1, mysql-1, spark-1, mongo-2 | false / proxy |
| account4 | 10.40.0.0/16 | kafka-2, mysql-3, spark-3 | false / proxy |
| account5 | 10.50.0.0/16 | mysql-2, mongo-3, kafka-3 | false / proxy |

노드명과 data_disks의 키는 Terraform for_each 식별자다. 이름 변경이나 계정·AZ 이동은 단순 표시 변경이 아니며 생성·교체·이전 계획을 확인해야 한다. 세부 노드 사양표는 [기존 실행 안내](../../../infra/scripts/scripts.md)에 있다.

nodes.bastion은 Account 1의 Public A, t3a.small, root_gib=20, public_ip=true를 유지한다. 이 정의는 foundation의 Bastion SG와 통신 역할 계산에 필요하지만 workload EC2에서는 role != bastion 조건으로 제외한다. [Bastion 전용 단계](../terraform/stacks/bastion.md)는 자동 공인 IP를 사용하고 EIP는 생성하지 않는다. EC2 삭제 시 OS 디스크도 삭제한다. Front 두 대는 workload에서 EIP를 각각 만든다. game-server는 Private A, t3a.large, public_ip=false다. 노드별 enabled 필드는 없다. [bastion.ps1](../scripts/bastion.ps1.md)은 생성·삭제와 기존 중지·시작을 구분해 제공한다.

광고 서버는 account1의 Private A에 배치하며 role=ad, t3a.large, root_gib=20, public_ip=false, data_disks={}를 유지한다. ALB 설정은 ad_role=ad, ad_path=/ads/*, ad_health_path=/이다. `/ads/`와 그 하위 경로는 원래 경로 그대로 광고 서버로 전달하며 Django URL 설정은 변경하지 않는다.

flatten-1은 account2의 Private A(apne2-az1), t3a.medium, root_gib=20, public_ip=false, data_disks={}다. role=consumer로 전용 SG와 인벤토리 그룹을 만들고 Kafka·Spark 서비스 설치 대상과 분리한다. 기본 설정과 profiles/current 복사본을 함께 갱신했다.

## traffic

consumer_kafka는 consumer → kafka TCP 9092다. admin_nodes의 대상과 forward_proxy의 출발 역할에도 consumer를 포함한다. 직접 인터넷 HTTPS, DB, Controller 접속은 추가하지 않는다.

connections는 소스 역할 목록·대상 역할 목록·시작 포트인 port를 지정한다. port와 선택 항목 port_end는 모두 ports의 키다. port_end를 생략하면 포트 하나만 허용하고, 지정하면 시작부터 끝까지 포함한 범위를 허용한다. 끝 포트는 시작 포트 이상이어야 한다. model이 이를 계정/역할 SG 쌍으로 펼치고 workload가 해당 계정의 입출력 규칙을 만든다. 이 설정은 통신 허용이며 애플리케이션의 처리 경로를 강제하지 않는다.

| 연결 키 | 소스 → 대상 | 현재 TCP 포트 |
| --- | --- | --- |
| alb_front / alb_game / alb_ad | ALB → frontend / game / ad | 80 / 8000 / 8000 |
| admin_nodes | bastion → 나머지 서버 역할 | 22 |
| game_kafka / spark_kafka | game·ad / spark → kafka | 9092 |
| kafka_replication / kafka_controller | kafka → kafka | 9092 / 9093 |
| mongo_replication / mysql_replication | mongo → mongo / mysql → mysql | 27017 / 3306 |
| spark_mongo / spark_mysql | spark → mongo / mysql | 27017 / 3306 |
| game_mysql | game → mysql | 3306 |
| spark_master / spark_driver / spark_block | spark → spark | 7077 / 7078–7094 / 7079–7095 |
| spark_worker / spark_master_ui | spark → spark | 7100 / 8080 |
| zookeeper_client / zookeeper_peer / zookeeper_election | spark → spark | 2181 / 2888 / 3888 |
| forward_proxy | frontend·game·mongo·spark·ad·kafka·mysql·consumer → bastion | 3128 |

admin_public_cidrs에는 현재 관리자 IPv4 CIDR 한 항목이 설정돼 Bastion SSH 22 규칙의 입력이 된다. game_client_cidrs에 지정한 IPv4 CIDR에서 ALB의 TCP 80 접속만 허용한다. 빈 배열이면 사용자 접속용 허용 규칙을 만들지 않는다. 이 사용자 목록은 Bastion SSH에 자동 적용되지 않는다. 설정 방법은 [공인 IP 설정 명령](../../operations-recovery.md#3-테스트용-공인-ip-조회와-게임-접속-허용-설정)을 참고한다. 구체적인 접속 IP 값은 이 문서에 기재하지 않는다.

internet_https_roles에는 bastion만 있어 그 역할에 외부 TCP 443 egress를 만든다. 이는 Bastion의 인터넷 송신 허용이며 ALB HTTPS 리스너를 만들거나 외부 사용자 접속을 여는 설정이 아니다. game→MySQL 허용 규칙은 코드상 존재하지만, DB 직접 쓰기나 읽기 중 무엇을 수행하는지는 보안규칙으로 구분하지 않는다.

ZooKeeper 세 포트는 Spark 노드의 클라이언트 접속·동기화·리더 선출에 사용한다. 기본 traffic과 현재 로컬 profiles/current/traffic 모두에 spark → spark 연결을 추가했다. model이 Spark 역할이 배치된 계정의 SG 쌍으로 펼치므로 현재 적용 대상은 account2·account3·account4의 workload다. 외부 CIDR 허용을 추가하는 설정이 아니며, 로컬 파일 변경 후 해당 구성의 새 Plan을 검토하고 Apply해야 AWS에 반영된다.

Spark는 platform 역할의 Worker RPC 7100, Master UI 8080, Driver 시작 포트 7078, BlockManager 시작 포트 7079와 맞춘다. 작업의 spark.port.maxRetries=16에 맞춰 Driver는 7094, BlockManager는 7095까지 허용한다. 같은 서버의 Driver·Executor가 BlockManager 시작 포트를 함께 쓰면 다음 허용 포트로 재시도한다. 이 두 범위는 일부 겹치며 기존 규칙의 시작 포트와 Terraform 주소는 유지한다. Master·Worker 데몬은 별도로 포트 재시도를 0으로 설정해 지정 포트를 벗어나지 않는다. 포트를 바꾸면 aws-platform/platform/roles/spark/defaults/main.yml과 선택한 구성의 traffic을 함께 맞춰야 한다. 두 신규 연결도 Spark SG끼리만 허용한다.

대응하는 [Spark 기본 변수](../../../../aws-platform/platform/docs/platform-routing/roles/spark/defaults/main.yml.md)와 [데몬·작업 통신 포트](../../../../aws-platform/platform/docs/platform-routing/roles/spark/README.md#프라이빗-서버의-통신-포트), 인프라의 [포트 범위 테스트](../tests/README.md#spark-포트-범위)를 함께 확인한다. 기본 파일을 고쳐도 기존 NewProfile 복사본은 자동 갱신되지 않으므로 선택한 구성 폴더의 traffic도 대조해야 한다.

## backend와 계정별 배포 입력

현재 로컬 backend의 bucket은 `aws-infra-tfstate-541308265856`으로 복원됐고 region은 ap-northeast-2, profile은 account1, key_prefix는 aws-infra-v2다. 버킷 이름을 채운 것만으로 실제 버전 관리와 접근 권한이 검증됐다는 뜻은 아니다. Plan·Apply·Output에는 버전 관리가 켜진 기존 S3 버킷과 접근 권한이 필요하다.

현재 로컬 설정의 다섯 계정 ami_id는 모두 `ami-0c713e716602facc2`다. 각 ssh_public_key_path는 config/keys/account1.pub부터 config/keys/account5.pub까지 계정별 파일을 가리킨다. 해당 계정 workload Plan·Apply에는 AMI와 실제 공개키 파일이 필요하다. 문서가 입력을 자동으로 채우거나 AWS 값을 조회하지 않는다.

ALB certificate_arn은 빈 문자열이지만 현재 HTTP 배포의 차단 사유가 아니다. 이 키는 model의 공통 객체 타입에 아직 남아 있으므로 설정에서 임의로 삭제하면 타입 입력이 달라질 수 있다. 현재 실행기와 ALB 모듈은 ACM ARN을 검사하지 않고, workload는 그 값을 ALB 모듈에 전달하지 않는다.

| 변경 종류 | 확인할 단계 |
| --- | --- |
| Bastion 사양·AMI·공개키 | account1 bastion의 PlanCreate 검토. 교체가 필요한 계획은 현재 보호 검사에서 거부 |
| 사양·같은 AZ의 데이터 디스크 용량 | 해당 계정 workload. 파일시스템 확장은 별도 |
| 서버 계정·AZ·역할·VPC·송신 방식 | 관련 foundation → connectivity → workload, 데이터 이전 검토 |
| 관리자 IP·서비스 연결·포트 | 규칙 양끝 계정 workload. 프로그램 포트도 별도 조정 |
| ALB 경로·대상 역할·활성화 | ALB 계정 workload. 역할 집합이 바뀌면 foundation도 확인 |
| backend 버킷·prefix | 상태 위치와 이관 검토. 값을 바꿔도 기존 상태가 자동 이전되지 않음 |

Bastion 전용 키페어 이름은 Account 1의 key_pair_name에 -bastion을 붙인 aws-infra-account1-bastion이다. 서비스 키페어와 구분하며, Bastion을 삭제해도 서비스 키페어는 삭제하지 않는다. 팀원 키 준비·기존 서버 등록 경로는 [계정별 SSH 키 문서](../scripts/account-keys.ps1.md)에 있다. 콘솔 SSH 접두사 목록 규칙은 traffic JSON 항목이 아니라 [workload 선언](../terraform/stacks/workload.md#콘솔-ssh-규칙의-범위)이 관리한다.

## mysql-3 증설

기본 topology.tfvars.json과 로컬 profiles/current/topology.tfvars.json의 nodes.mysql-3를 함께 추가했다. account4, role=mysql, az=a, subnet_tier=private, t3a.small, root_gib=20, public_ip=false이며 data_disks.data는 gp3 100GiB·/dev/sdf다. mysql-1(account3 A)·mysql-2(account5 C)의 설정은 유지했다.

foundation은 노드 역할 집합에서 account4/mysql SG를 추가하고, workload의 local.nodes와 compute의 for_each가 새 EC2·데이터 볼륨·연결을 생성한다. 기존 mysql_replication·spark_mysql·game_mysql·admin_nodes·forward_proxy를 새 SG까지 확장하므로 traffic에 새 연결이나 외부 허용을 추가하지 않았다. MYSQL 통신 스택의 멤버 포트는 3306이며 Router의 loopback 6446·6447을 원격 SG에 열지 않는다.

2026-10-10 실제 반영은 current 프로필과 기존 aws-infra-v2 원격 상태를 사용했다. [검증 결과](../verification.md#2026-10-10-mysql-3-증설과-실제-aws-검증)에 EC2·EBS·SG와 계정별 적용 수를 기록했다. 이전에 만든 다른 프로필은 자동 갱신되지 않는다. alb.enabled=true를 유지한 account1의 전체 Plan은 현재 사라진 ALB를 다시 만들 수 있으므로 MySQL 증설 계획과 구분해 검토한다.


| consumer_kafka | consumer → kafka | 9092 |


## 평탄화 Consumer 변경 연결

flatten-1은 account2 Private A의 t3a.medium·OS 20GiB·공인 IP 및 별도 데이터 디스크 없음으로 정의한다. role=consumer를 유지하고 Kafka·Spark 그룹에 넣지 않는다. traffic의 consumer_kafka는 consumer→Kafka TCP 9092, forward_proxy는 consumer→Bastion TCP 3128, SSH 연결은 Bastion→consumer TCP 22를 허용한다. 역할별 흐름은 송신·수신 보안그룹 규칙으로 펼쳐진다. Consumer 프로그램 배포와 Kafka의 OS 방화벽 허용은 별도 확인 대상이다. foundation의 account2_private, workload의 account2_three_nodes·flatten.tftest.hcl·console-ssh.tftest.hcl과 fixtures.json의 consumer SG가 관련 검사 위치다. 이번 문서 작업은 테스트 실행 결과를 새로 주장하지 않는다.
