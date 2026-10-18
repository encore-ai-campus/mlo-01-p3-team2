# 문서 대조 기준과 검증 범위

[탐색 시작점](ROUTING-README.md) · 로컬 적용 규칙: AGENTS.md(Git 제외)

## 2026-10-15 수정 코드와 문서 재대조

Git HEAD ba6f151a494f604d2d3dc70d443b52a0a2a19cfd → WORKTREE 및 미추적 소스를 기준으로 양쪽 라우팅 문서 177개를 재대조했다. 전원 실행기·Python 모의 테스트·계정 재배치·Kafka→Backend 8000·데이터 EBS lifecycle·삭제 허용 목록·Vault 옵션 전달은 기존 문서에 반영되어 있어 내용을 유지했다. 이번 추가 수정은 [플랫폼 검증 기록](../../../aws-platform/platform/docs/platform-routing/verification.md#2026-10-15-수정-코드와-라우팅-문서-재대조)의 MongoDB 데이터 디렉터리 소유권, 방화벽 출력식·분기 설명과 edge 역할 대상이다.

routing-doc-sync 번들 AST 분석기의 인식 가능한 Python 참조는 39개이며 확정 불일치·분석 진단은 0개다. needs_review·role_status=not_verified를 유지하며 비Python 동작을 AST 검증 결과로 간주하지 않는다. 신규 전원 테스트 함수는 기존 문서의 시그니처와 대조하고, 구조 변경이 없는 Python 파일도 보고서에 남긴다.

보고서는 infra/.local/routing-doc-sync-20261015/before.json과 final.json, 링크·MongoDB 작업 표 및 소스 보존 확인은 checks.json에 보관한다. 문서 경로·앵커와 비Markdown 파일 해시를 확인했으며 기존 코드와 Git index는 수정하지 않았다. AWS API 호출, 전원 변경, Plan·Apply, Ansible 실행, 서비스 연결 검증은 하지 않았다. 아래 기록의 테스트·배포 결과는 각 날짜의 이력이다.

## 2026-10-14 Kafka·Consumer 계정 재배치 — 로컬 검증

사용자 요청에 따라 기본 topology와 profiles/current의 kafka-1을 account4, flatten-1을 account1로 변경했다. ad-server는 account1에 유지했다. 두 topology JSON의 전체 내용이 일치하며 총 18대, 계정별 6 / 2 / 3 / 4 / 3대(Bastion 포함)다. 사양·디스크·AZ·역할과 traffic 연결 선언은 유지했다.

- foundation Terraform 모의 테스트 3개, workload 모의 테스트 32개가 통과했다. 계정별 배치·Consumer Kafka/MongoDB/프록시 연결·SSH 정책·account4 Kafka의 자체 broker/controller 통신을 검사했다.
- current 프로필의 foundation·workload에서 backend 없이 terraform validate가 통과했다. 수정한 Terraform 테스트의 fmt 검사도 통과했다.
- fixture의 consumer SG를 account1로 옮기고 account2의 consumer 및 account3의 kafka SG를 제거해 오래된 참조가 테스트에서 드러나도록 했다. 기존 서버 수·통신·SSH 테스트를 새 배치에 맞췄다.
- 처음에는 샌드박스에서 provider 프로세스가 응답하지 않아 실행 환경을 바꿨다. 최종 테스트는 AWS provider와 원격 상태 모두 모의 처리했으며 실제 AWS Plan·Apply·자원 생성은 실행하지 않았다.
- 사용자 범위 조정 전에 EC2 조회만 수행했고 다섯 계정 모두 실행 중·중지 상태의 인스턴스가 없었다. Ansible 코드·인벤토리 변경과 원격 설치는 이번 작업에서 제외했다. 실서비스 접속·클러스터 동작은 검증하지 않았다.

실행 로그는 infra/.local/account-rebalance-20261014/의 foundation-test.log, workload-test.log, foundation-validate.log, workload-validate.log에 보관한다. 아래 이전 검증 기록은 당시 입력의 결과다.

## 2026-10-14 수정 코드와 라우팅 문서 동기화

비교 기준은 Git HEAD → WORKTREE이며 신규 미추적 소스도 포함했다. routing-doc-sync 스킬의 번들 AST 분석기로 두 프로젝트의 Python 구조와 라우팅 Markdown을 대조했다. 보고서는 infra/.local/routing-doc-sync-20261014/before.json과 final.json에 로컬 보관한다. 대상 Python을 import하거나 원본 본문을 읽어 선언을 추출하지 않았다.

| 코드 변경 | 연결 문서·반영 내용 |
| --- | --- |
| 전체 EC2 전원 실행기·계정별 작업자 | [power-all.ps1](scripts/power-all.ps1.md) · [infra-power.ps1](scripts/lib/infra-power.ps1.md). 구성·출력·소유자·태그·권한 검사, 전체 Check 이후 병렬 Change, 전환 대기·부분 실패 경계 |
| 신규 Python 모의 전원 테스트 2개 | [전원 테스트 구조](tests/power-tests.md). AST로 추출한 함수 7개의 파일·정확한 인자·기본값과 호출 보조 근거 |
| 데이터 EBS lifecycle | [compute](terraform/README.md#compute) · [workload](terraform/stacks/workload.md#변경-시-경계) · [bastion](terraform/stacks/bastion.md). 현재 prevent_destroy=false로 설명을 맞춤 |
| Backend API 수신 필터 | [통신 설정](config/README.md#애플리케이션-통신-확장) · [workload](terraform/stacks/workload.md) · [통신 테스트](tests/README.md). 현재 Backend 8000은 해당 Front·상대 Backend만 허용하며 Kafka·MySQL 출처는 제거 |
| 삭제 허용 목록·PowerShell 회귀 검사 | [삭제 경계](scripts/lib/infra-destroy.ps1.md#삭제-계획의-경계) · [삭제 테스트](tests/destroy-tests.md). Front 두 역할의 정확한 송신 규칙 주소·기존 거부 조건 대조 |
| Vault 입력 전달 | [deploy.ps1](scripts/deploy.ps1.md#프록시-실행) · [프록시 스크립트](../../../aws-platform/platform/docs/platform-routing/scripts/setup-proxy.sh.md). 기존 문서에 AskVaultPass 전달과 암호 저장 없음이 반영되어 있음을 확인 |

첫 전체 문서 검사에서 나온 6개 불일치는 Terraform 주소와 Ansible 파일명을 Python 심볼로 해석한 경우였다. Terraform 주소는 HCL 블록으로, Ansible 파일명은 원본 링크로 명시했다. 새 테스트 함수 7개는 모두 signature_match이고 확정된 구조 불일치와 분석 진단은 0건이다.

분석기의 최종 상태는 needs_review이며 role_status는 not_verified다. 자유 형식 설명·지원 밖 표기와 함수 역할의 의미를 자동 증명하지 못하는 한계를 유지한다. Python 역할은 모듈 docstring·import·호출 이름을 보조 근거로 검토했으며 PowerShell·Terraform·JSON·Bash·YAML은 실제 변경 파일과 기존 문서를 수동 대조했다. Python 분석 결과로 이 언어들의 동작을 검증했다고 판정하지 않는다.

이번 작업은 라우팅 Markdown만 수정했다. 변경 문서의 상대 링크·앵커와 코드 파일 해시를 검사하며, 실행기 테스트·Terraform test·Ansible playbook·AWS 전원 및 배포는 재실행하지 않았다. 아래 날짜별 테스트 통과·실제 AWS 조회 기록은 당시 결과로 보존한다.

## 2026-10-10 광고 서버 AZ A 배치 설정

사용자 요청으로 기본 topology와 로컬 profiles/current의 nodes.ad-server.az를 c에서 a로 변경했다. account1·role=ad·private·t3a.large·OS 20GiB·별도 데이터 디스크 없음은 유지한다. 선언상 Bastion 포함 AZ별 대수는 A 13대·C 5대다. 기존 클러스터의 A 2대·C 1대 배치는 그대로다.

이 기록은 설정 변경이며 실제 AWS 이전 완료를 뜻하지 않는다. compute의 subnet_id가 private_a를 선택하게 되므로 실제 계획에서 EC2 교체 범위를 확인해야 한다. 광고 서버 루트 디스크는 delete_on_termination=true이므로 앱·설정·데이터 보존 후 이전한다. account1 workload의 일반 Plan에는 수동 삭제한 ALB 재생성이 포함될 수 있다. Terraform Apply와 생성 인벤토리 갱신은 아직 수행하지 않았다. 현재 인벤토리를 원하는 AZ에 맞춰 수동 변경하지 않는다.

두 JSON은 ad-server의 az 외 의미상 변경이 없음을 검사했다. Python AST 기반 routing-doc-sync는 실제 Git 최상위 C:/third_project를 기준으로 실행하며 JSON·Terraform 동작과 AWS 상태는 분석 대상이 아니다.

account1 workload Plan을 시도했으나 샌드박스의 STS 네트워크 연결 실패로 중단됐다. 네트워크 접근을 위한 추가 실행 승인은 사용자가 거절했으므로 재실행하지 않았다. 저장된 새 Terraform 계획은 없으며 실제 교체·삭제·ALB 생성은 실행하지 않았다. 라우팅 대조는 참조 불일치 0, needs_review/role not_verified로 기존 Python 변경 검토가 남아 있다. AWS 계획 검증이 완료되지 않아 이번 변경의 자동 스테이징과 커밋은 수행하지 않았다.

## 2026-10-10 mysql-3 증설과 실제 AWS 검증

사용자 승인 범위는 기본 topology와 로컬 profiles/current에 mysql-3를 추가하고 account4 foundation·다섯 workload의 MySQL 변경을 반영한 뒤 관련 문서를 갱신하는 작업이다. 비교 기준 HEAD는 3274dee0ac642345c3e8b4094a2a372b1a45b4d4이며 시작 시 존재하던 문서 개편·flatten-1·통신 설정·삭제 기능 변경은 보존했다. 이번 작업은 current 프로필과 기존 aws-infra-v2 상태 경로를 사용했다.

| 대상 | 최초 전체 Plan | 실제 Apply | 검토한 범위 |
| --- | --- | --- | --- |
| account4 foundation | 1 추가, 변경·삭제 0 | 1 추가, 변경·삭제 0 | 기존 VPC·서브넷 유지, mysql SG만 생성 |
| account1 workload | 7 추가, 변경·삭제 0 | 3 추가, 변경·삭제 0 | MySQL SG 규칙 3개만 별도 제한 계획으로 적용. ALB 관련 4개 생성 제외 |
| account2 workload | 1 추가, 변경·삭제 0 | 1 추가, 변경·삭제 0 | Spark → 새 MySQL SG egress |
| account3 workload | 3 추가, 변경·삭제 0 | 3 추가, 변경·삭제 0 | Spark → 새 MySQL 및 MySQL 멤버 입출력 |
| account4 workload | 17 추가, 변경·삭제 0 | 17 추가, 변경·삭제 0 | mysql-3 EC2·데이터 EBS·연결 3개와 SG 규칙 14개 |
| account5 workload | 2 추가, 변경·삭제 0 | 2 추가, 변경·삭제 0 | 기존 MySQL과 새 MySQL의 입출력 |

account4 foundation의 새 SG는 aws-infra-account4-mysql(sg-0e2c89a2d778c1960)이다. 기존 VPC vpc-09666b7b72132ae38과 Private A subnet-06c482871395a1d55를 사용했다. 기존 Peering·CIDR·AZ 배치는 수정하지 않았다. 기존 traffic의 MySQL·Spark·game·SSH·Proxy 관계를 model이 새 SG로 확장하므로 이번에 traffic이나 Terraform 생성 코드를 변경하지 않았다.

| mysql-3 항목 | 실제 AWS 조회 결과 |
| --- | --- |
| 계정 / 사양 | account4(688567306400) / t3a.small |
| EC2 | i-08021a300ea08a530, running |
| AZ / 서브넷 | ap-northeast-2a, 논리 A / Private A |
| 주소 | 사설 10.40.10.155, 공인 IPv4 없음 |
| OS EBS | vol-00bfb1fc1d79e7267, gp3 20GiB, 암호화·연결 확인 |
| 데이터 EBS | vol-08cfe8ff4429480d7, gp3 100GiB, 암호화·연결 확인 |

다섯 workload의 신규 자원 26개 중 23개는 보안규칙이다. AWS describe-security-group-rules로 계정별 3 / 1 / 3 / 14 / 2개 규칙의 실제 존재와 ingress/egress·TCP 포트·소스 SG/접두사 목록을 저장 계획과 대조했다. 기존 서비스 EC2는 계정별 4 / 3 / 4 / 2 / 3대, 총 16대의 같은 ID가 남아 있고 새 mysql-3를 더하면 17대다. 저장 계획에서 기존 서버·디스크의 변경·삭제가 없음을 확인했다. 모든 서비스의 데이터 내용이나 복제 상태를 검사했다는 뜻은 아니다.

account1의 최초 전체 Plan은 현재 AWS에서 사라진 ALB·HTTP listener·static/ad rule 4개도 다시 만들려고 했다. 사용자가 비용 증가를 원하지 않아 복원을 보류했다. 이번에만 같은 backend와 선택한 입력으로 MySQL 규칙 3개에 -target을 지정한 별도 저장 계획을 준비했다. 코드·설정 fingerprint, backend bucket/key, 계획 해시와 허용 자원 목록을 확인한 뒤 적용했다. 사용한 부분 계획과 원래 7개 전체 계획은 적용 후 제거했다. 이 예외 적용은 일반 실행기에 부분 배포 기능을 추가한 것이 아니다.

실제 ELB 조회에서 aws-infra-account1 ALB가 없는 것을 확인했다. alb.enabled=true 설정은 유지되므로 이후 일반 account1 workload Plan은 다시 ALB 생성을 제안할 수 있다. ALB가 없는 동안 기존 ALB URL을 통한 웹 접속은 불가하다. 재생성한다면 새 기본 DNS를 Output으로 확인하고 Django 허용 호스트·직접 적은 URL을 갱신한다. 서버 장애 자동 복구나 ALB 자동 생성 예약을 구성한 것은 아니다.

두 topology에서 mysql-3를 제거하면 추가 전 JSON과 의미상 동일함을 확인했고 model 계산으로 MySQL 세 노드·account4의 kafka/mysql/spark 역할·관련 flow 확장을 확인했다. 라우팅 문서와 현재 수량·계정별 EBS·유휴 비용을 대조했다. 비용표는 ALB 포함 선언 시나리오와 실제 ALB 미생성 조건을 구분하며 과거 16·17대 계산은 당시 기록으로 보존한다.

이번에 하지 않은 검증은 MySQL 설치·Cluster 가입·자동 Primary 선출·Router 연결·실제 서비스 TCP 통신·OS 방화벽·데이터 EBS 포맷/마운트·Ansible 실행이다. Inventory와 Proxy도 아직 재실행하지 않았다. 세 MySQL의 배치는 A 두 대·C 한 대이므로 A 전체 장애에는 정족수가 유지되지 않는다. 모의 테스트의 account4 fixture와 두 노드 기대값은 아직 이전 입력 기준이며 이번에 수정하거나 전체 테스트를 재실행하지 않았다.

문서 변경 18개의 로컬 링크·제목 앵커 354개는 오류 0개였다. 두 topology의 MySQL 3대·서비스 계정별 4/3/4/3/3대·Bastion 포함 18대·EBS 4,260GiB를 계산해 문서와 대조했고 유휴 요금표도 Decimal로 검산했다. routing-doc-sync의 변경 전후 비교에서 참조 2개, mismatch=0, diagnostics=0이다. 최종 structural_status=needs_review·role_status=not_verified·도구 판정 exit_code=3이며 Python AST 범위 밖의 Terraform·JSON 역할 의미는 수동 대조했다. 이를 전체 자동 검증 통과로 기록하지 않는다.

로컬 감사 자료는 Git에서 제외되는 infra/.local/mysql3-workload/에 plan-review.json, apply-results.json, account1-mysql-only-review.json, account1-mysql-only-apply-result.json, aws-verification.json, document-verification.json과 로그로 보관했다. foundation 결과는 해당 프로필의 account4/foundation 로컬 경로에 있다. routing-doc-sync 보고서는 infra/.local/mysql3-workload-routing-before.json·mysql3-workload-routing-after.json이다. 모의 테스트 기대값의 남은 차이와 기존 혼합 변경 때문에 이번에 스테이징·커밋은 진행하지 않았다. 아래 기존 검증 기록은 각 당시 작업의 결과이며 이번에 재실행한 결과로 해석하지 않는다.

## 2026-10-10 README와 관련 안내의 라우팅 기준 동기화

사용자 요청에 따라 [인프라 README](../../README.md)와 [플랫폼 README](../../../aws-platform/platform/README.md), 연결된 배포·보안·설계·설치·검증 안내를 갱신했다. 본문 내용의 근거는 현재 양쪽 라우팅 문서이며, 실행 코드 본문을 읽어 새 동작을 추정하거나 AWS 배포 상태를 조회하지 않았다. Python 문서 참조의 구조 검사에는 routing-doc-sync의 AST 보고서를 사용했다.

- 서비스 EC2 16대·선택 Bastion 1대, account2의 평탄화 Consumer와 프록시·Kafka 통신 설명을 맞췄다. 인프라 MySQL 2대와 플랫폼 InnoDB Cluster 3~9대의 조건 차이를 명시하고, 세 번째 서버·통신·인벤토리 준비 전에는 MySQL 역할을 실행하지 않도록 안내했다.
- game·Spark·선택 backend의 로컬 Router 설치 순서와 loopback RW 6446·RO 6447을 반영했다. 이전 ReplicaSet·Standalone 서버 시험은 새 Cluster·Router의 원격 검증 결과로 바꾸지 않았다.
- 현재 데이터 EBS 보호 true와 전체 삭제의 Plan/Apply·단일 Destroy를 구분했다. DeleteDataVolumes는 삭제 선택이며, Destroy와 DisableDataVolumeProtection을 함께 지정했을 때만 일시 해제·원본 복원한다.
- Terraform 생성·Proxy 준비·플랫폼 서비스 설치·별도 앱 배포의 경계를 맞췄다. 준비된 Endpoint를 사용하는 팀 접속 스크립트도 안내하되 Endpoint·IAM·SG·키 등록을 생성하는 기능으로 설명하지 않았다.
- 시작 검사의 잘못된 파일 링크·제목 앵커는 17개였다. 이번 작업에서 16개를 수정했고 나머지 1개는 작업 중 이미 갱신된 상태를 보존했다. 최종 양쪽 Markdown 183개에서 상대 링크·제목 앵커 누락은 0개다. 외부 URL·가격·배포처 버전은 조회하지 않았다.

비교 기준은 HEAD 3274dee0ac642345c3e8b4094a2a372b1a45b4d4 → WORKTREE다. Python 대응 문서 4개의 참조 28개는 일치하며 mismatch=0, diagnostics=0이다. 스킬 판정은 needs_review, role_status=not_verified로 유지한다. 이 결과는 PowerShell·Terraform·Ansible·Bash의 실행이나 역할 의미·서비스 동작 검증이 아니다. 문서 변경분의 git diff --check도 통과했다.

이번 수정 대상은 Markdown 30개이며 AWS·Terraform·SSH·Ansible 실행, 코드·설정 변경, 스테이징·커밋 명령은 수행하지 않았다. 시작 시 저장한 비Markdown 파일 192개 중 flatten.tftest.hcl과 Git index가 작업 중 달라진 것을 관찰했다. 이 변화의 원인은 조사하지 않았고 현재 내용을 덮어쓰거나 되돌리지 않았다. HEAD는 동일하다. 과거 시험·비용 계산은 당시 가정과 결과로 보존한다.

시작 사본, 링크 검사, AST 보고서와 범위 기록은 infra/.local/readme-doc-sync-20261010/의 baseline.json, links-before.json, links-after.json, routing-reference-check.json, scope-after.json에 보관한다. 아래 기록은 각 당시 작업의 범위이며 이번에 재실행한 시험으로 해석하지 않는다.

## 2026-10-10 복원·운영 절차 분리

사용자 요청에 따라 scripts.md의 S3 설정·AMI·접속 IP·배스천 전원·SSH 키 전환·전체 삭제 절차 6개를 [복원·운영 문서](../operations-recovery.md)로 옮겼다. 명령 설명·비용별 배포는 scripts.md에 남기고, deployment-runbook.md의 관련 단계와 장애 표에서 새 문서의 해당 제목으로 이동하도록 연결했다. 새 문서에는 원인 확인 뒤 배포 단계로 돌아오는 링크와 SSH·프록시·Vault·ZooKeeper·PowerShell/WSL·Terraform 장애 안내를 추가했다.

- 이동 대상에 있던 PowerShell 명령 블록 10개가 새 문서에 그대로 남아 있고 scripts.md의 이전 10~15절은 제거됐다.
- Windows PowerShell 5.1 파서로 변경 문서의 예제 블록 53개를 검사해 구문 오류 0개를 확인했다. 명령을 실행한 검사는 아니다.
- 변경 문서의 상대 파일 링크·제목 앵커를 검사하고 이동된 절을 가리키던 참조를 새 경로로 수정했다. 이미 이름이 바뀐 안내 파일은 현재 파일로 연결했다.
- routing-doc-sync의 파일·Python 선언 참조 21개에서 mismatch=0, diagnostics=0을 확인했다. 전체 상태는 needs_review, 역할 의미는 not_verified다. 비Python 파일명·설정 키를 Python 선언으로 오인하던 표기는 강조 표기로 정리했다. 비Python 실행 동작은 AST 검사 범위 밖이다.
- 시작 사본의 기존 변경을 보존했고 이번 작업에서 수정한 파일은 Markdown 10개다. 작업 중 compute/main.tf의 해시 변경이 관찰됐으며 최종 조회한 prevent_destroy 값은 true다. 해당 소스를 수정한 명령은 이번 작업에서 실행하지 않았고 변경 원인은 확인하지 않았다. 다른 파일의 해시와 Git index는 시작 기준과 동일하다. AWS·Terraform·SSH·Ansible 원격 명령은 실행하지 않았다. 기존 변경이 섞인 문서가 있어 추가 스테이징·커밋은 하지 않았다.

비교 기준은 HEAD 3274dee0ac642345c3e8b4094a2a372b1a45b4d4 → WORKTREE다. 사전·사후 AST 보고서, 시작 사본·해시, 링크·명령 보존 검사와 PowerShell 파서 결과는 infra/.local/diagnostics/operations-docs-20261010/에 남겼다. 이전 실행 기록은 아래에 당시 결과로 보존한다.

## 2026-10-10 단일 호출 전체 삭제 구현

사용자가 승인한 삭제 실행기·명령 안내·삭제 라우팅·모의 테스트 범위에 Destroy 동작을 추가했다. 실행기는 새 ID로 Plan → 기존 검사 → Apply → 결과 검증을 이어 수행하고 전체 호출 동안 실행 잠금을 유지한다. DisableDataVolumeProtection은 Destroy에서만 허용하며, 데이터 EBS 보호를 해제할 때 원본 바이트·해시를 먼저 저장한다. 첫 삭제 전에 원본 사본을 검사하고 종료 시 복원한다. 복원 후 Verify는 별도의 보호 해제 전 fingerprint를 사용하며 저장 Plan의 fingerprint는 바꾸지 않는다.

- 신규 단일 삭제 테스트: Windows PowerShell 5.1·PowerShell 7 각각 12개 시나리오 통과. 정상 12단계 순서, 같은 실행 ID, BOM/CRLF 복원, 이후 Status/Verify, Plan·Apply 실패 중단, 입력 거부, 기존 false 유지, 지원하지 않는 선언과 외부 수정·사본 변조의 실패를 검사했다.
- 기존 전체 삭제 테스트: Windows PowerShell 5.1에서 17개 시나리오 통과. 이 시험이 가정하는 보호 초기값 true는 격리 사본에서만 설정했다. 서비스 콘솔 SSH 삭제 경계 16개도 통과했다.
- PowerShell 5.1·7에서 현재 삭제 실행기를 파싱하여 오류가 없음을 확인했다. routing-doc-sync는 대상 테스트 사본과 직접 관련 문서만 대조했으며 최종 Python 참조 20개 일치, mismatch=0, diagnostics=0이다. 전체 결과는 needs_review, role_status=not_verified, 종료 코드 3이다. 비Python 동작과 실제 서비스·권한·provider 실행은 이 AST 검사 범위 밖이다.
- 작업 시작 시 compute/main.tf의 보호 값은 이미 false였으며 이 파일의 바이트는 보존했다. 위의 이전 true 기록은 당시 상태다. 실제 AWS 조회·Plan/Apply·원격 설치나 삭제는 실행하지 않았다.
- 작업 중 실행 안내가 infra/scripts/README.md에서 infra/scripts/scripts.md로 이동했다. 이동된 파일에 이번 명령 설명이 유지됨을 확인하고 삭제 문서의 링크만 새 경로로 맞췄다. 다른 영역의 문서 이동을 되돌리거나 조사하지 않았다.

실행 방법은 [명령 안내](../operations-recovery.md#6-전체-인프라-삭제), 구현 흐름은 [삭제 실행기 문서](scripts/destroy-all.ps1.md), 모의 시험 선언은 [삭제 테스트 문서](tests/destroy-tests.md)에 있다. 이번 기준 사본·사전/사후 AST 보고서·최종 점검은 infra/.local/diagnostics/destroy-once-20261010/에 보관한다. 기존 문서 변경과 동시 이동은 이번 코드 변경으로 취급하지 않으며 추가 스테이징·커밋은 하지 않는다.

## 2026-10-10 compute 변경에 한정한 문서 반영

이번 요청의 비교 기준은 HEAD 3274dee0ac642345c3e8b4094a2a372b1a45b4d4 → WORKTREE다. Git 변경 목록에서 실행 코드의 변경은 compute/main.tf의 데이터 EBS 보호가 prevent_destroy=false에서 true로 바뀐 한 곳이다. 이 소스와 직접 대응하는 모듈·workload·배포·전체 삭제 문서만 대조했다. 다른 소스나 폴더는 스캔하지 않았다.

- [compute 모듈](terraform/README.md#compute)에 현재 삭제 보호와 DeleteDataVolumes의 차이를 보완했다. 데이터 볼륨의 삭제·교체 Plan은 보호 때문에 실패할 수 있으며, 전체 삭제 옵션은 이 보호를 해제하지 않는다.
- workload·deploy·destroy-all 문서의 현재 설명은 이미 true 설정과 일치해 추가 수정하지 않았다. 이전 검증 기록은 당시 결과로 보존하고, 아래의 과거 false 설명과 최신 설정을 구분했다.
- routing-doc-sync는 대상 소스 1개와 관련 문서 4개의 사본만 넣은 Git 저장소 밖 임시 폴더에서 실행했다. --base NONE으로 제한된 사본을 대조하므로 저장소 전체의 Python 파일을 조사하지 않는다. 이번 대상은 Terraform이며 스킬의 Python AST 검사 범위 밖이다. 사전·사후 보고서는 모두 checked_references=0, mismatch=0, diagnostics=0, needs_review, role_status=not_verified, 종료 코드 3이다. 이 결과를 Terraform 구조·역할·실행의 검증 성공으로 해석하지 않는다.
- Terraform 동작 설명은 해당 소스의 Git 차이와 관련 문서를 수동 대조했다. AWS 조회·Terraform Plan/Apply·원격 Ansible·서비스 검증은 실행하지 않았다. 코드·설정·키·Vault는 수정하지 않았다.

이번 점검의 시작 사본·사전/사후 보고서·변경 범위 점검은 infra/.local/diagnostics/compute-doc-sync-358ffadd/의 baseline.json, pre.json, post.json, final-audit.json에 보관한다. 아래의 전체 문서 스캔 수치와 다른 영역 점검은 이전 작업 기록이며 이번 요청에서 재실행한 검사가 아니다.

## 2026-10-10 하위 폴더 지도와 문서 이동 반영

비교 기준은 HEAD 3274dee0ac642345c3e8b4094a2a372b1a45b4d4 → WORKTREE다. 작업 시작 전에 플랫폼 문서가 이미 이동된 상태였으며, 삭제된 이전 경로를 복원하지 않고 현재 [플랫폼 시작 문서](../../../aws-platform/platform/docs/ROUTING-README.md)와 docs/platform-routing 하위 설명을 기준으로 연결했다. 기존 설계 문서의 변경 내용은 유지하고 라우팅 링크만 수정했다.

- 인프라 scripts·scripts/lib와 플랫폼 scripts에 하위 폴더 지도를 추가했다. 양쪽 시작 문서에 폴더별 책임·탐색 경로를 연결하고 README·플랫폼 AGENTS의 시작 경로를 맞췄다.
- 이동 전 위치를 가리키던 로컬 링크 292개를 확인하고 현재 위치로 수정했다. 과거 실험·실행 결과는 새 검증 결과로 바꾸지 않았다.
- 최종 라우팅 문서는 151개이며 시작 문서에서 전부 도달 가능하다. 플랫폼 코드·설정의 파일별 대응은 110/110이다. 생성 인벤토리·실제 Vault·개인키는 문서화 대상에서 제외한다.
- 전체 검사 범위의 로컬 링크 1,212개와 Markdown 제목 앵커 50개를 검사했다. 깨진 링크·잘못된 앵커·고립 문서·플랫폼 대응 누락은 0개다.
- routing-doc-sync 최종 검사: 파일 참조 7개, 선언 시그니처 15개 일치; mismatch=0, diagnostics=0. 전체 상태는 needs_review, role_status=not_verified, 종료 코드 3이다. 비Python 문서의 자동 심볼·역할 의미 검사가 지원되지 않는 한계를 유지한다.
- Terraform 주소를 Python 선언으로 오인하던 인라인 표기는 HCL 코드 블록 또는 강조 표기로 정리했다. Python 구조는 스킬 inventory와 documents.checks로 조사했으며 프로젝트 Python 파일을 import·실행하지 않았다.
- 작업 중 compute/main.tf의 prevent_destroy가 false에서 true로 바뀐 것을 해시·Git 차이로 관찰했다. 이번 문서 작업은 소스를 수정하지 않았으며 변경 원인은 확인하지 않았다. 현재 true 값을 기준으로 모듈·배포·삭제 문서와 관련 실행 안내의 설명만 맞췄다. 아래 과거 기록의 false는 당시 값이다.
- 시작 시점과 비교해 다른 비Markdown 파일의 해시와 Git index는 동일하다. 변경분 공백 검사도 통과했다. AWS 조회·Terraform Plan/Apply·원격 Ansible·서비스 검증은 실행하지 않았다.

분석 자료는 infra/.local/diagnostics/routing-refresh/에 pre.json, post.json, baseline.json, final-audit.json으로 남겼다. 기존 문서 이동·설계 변경과 이번 변경이 섞여 있으므로 추가 스테이징·커밋 없이 기존 index를 유지했다.

## 2026-10-10 양쪽 프로젝트 변경 코드 재대조

사용자 요청에 따라 aws-infra/docs/infra-routing와 platform/docs/platform-routing의 현재 문서 148개를 함께 조사했다. 비교 기준은 HEAD e7c0f7533bfe68649035db3a15395d80b3d2e489 → WORKTREE이며 브랜치는 infra;#5다. 아래 이전 기록의 수치·미실행 항목은 각 당시 시점의 기록으로 보존한다.

이번 aws-infra 보완은 통합 지도, config, deploy, Terraform 모듈·workload, 테스트 지도와 이 기록에 한정한다. 이미 반영된 Spark 설정을 다시 작성하지 않고 누락된 model/security-rules/workload 포트 범위 테스트 세 파일을 연결했다. 9개 run의 입력·범위·규칙 키·병합 검사와 실제 실행 결과를 구분하고, 존재하지 않았던 tests/README.md의 Spark 포트 범위 앵커를 추가했다. 플랫폼의 설정·원격 검증 문서에도 양방향 탐색 링크를 연결했다.

현재 Spark 구현에는 Worker RPC 7100 고정, Master UI 8080 조회, Driver 7078–7094·BlockManager 7079–7095 범위와 작업의 재시도 16회, 데몬의 재시도 0회가 이미 선언돼 있다. 아래 ZooKeeper 수정 당시의 "후속 Spark 설정"은 당시 남아 있던 작업이며 현재 코드의 미구현 목록으로 읽지 않는다. 이 문서 동기화에서는 AWS 규칙 적용이나 Spark 설치 완료를 확인하지 않았다.

deploy.ps1 문서의 데이터 EBS 설명은 실행기가 보호 값을 변경하지 않는다는 동작과 현재 compute의 prevent_destroy=false를 구분하도록 수정했다. 조사 중 compute/main.tf의 해시가 시작 사본과 달라진 것을 확인했지만 이번 작업에서 소스 수정 명령은 실행하지 않았다. 변경 원인은 확인하지 못했으며 현재 파일의 false 값을 기준으로 문서만 맞췄다. 나머지 비라우팅 파일 196개와 기존 Git index는 시작 시점과 비교해 동일함을 확인했다.

| 검사 | 이번 결과 | 범위·한계 |
| --- | --- | --- |
| routing-doc-sync | Python 참조 22개, mismatch 0, diagnostics 0 | needs_review, role_status=not_verified. 비Python 선언과 역할 의미·런타임은 자동 검사 밖 |
| Python 신규 선언 | 추가된 12개 심볼은 기존 전체 삭제 테스트 문서에 선언 참조가 있음 | AST 보고서만 사용하며 대상 코드를 import하거나 실행하지 않음 |
| 로컬 Markdown 연결 | 양쪽 문서 148개의 파일 링크·제목 앵커 1,054개, 오류 0 | 외부 URL의 유효성은 조회하지 않음 |
| 플랫폼 파일별 문서 | YAML·CFG·systemd 선언 위치 535개, Jinja 출력식 목록 25개 문서 대조, 차이 0 | 이름·위치·출력식의 정적 비교. Bash 단계는 코드와 수동 대조하며 렌더링·실행하지 않음 |
| 변경 범위 | 양쪽 라우팅 Markdown 13개 보완, 기존 스테이징 유지 | 코드·설정·운영 인벤토리·Vault·키는 수정하지 않음 |
| 공백 검사 | git diff --check와 git diff --cached --check 통과 | 기존 줄바꿈 변환 경고는 공백 오류와 구분하며 저장소 정책은 변경하지 않음 |

점검 사본·AST 보고서·로컬 연결 및 범위 보고서는 infra/.local/routing-doc-sync/20261010-a49b2e0d/에 보관한다. 이전 Terraform 모의 테스트 성공을 이번 재실행 결과로 바꾸지 않았다. 기존 workload 테스트의 노드 수·SG ID 기대값 차이와 실제 배포 검증은 이번 문서 작업으로 해결한 것으로 기록하지 않는다. 기존 변경이 섞인 문서와 미검증 실행 범위를 보존하기 위해 추가 스테이징·커밋은 하지 않는다.

## 2026-10-10 실제 변경과 라우팅 문서 동기화

사용자 요청에 따라 docs/infra-routing의 문서 21개를 현재 작업 파일과 대조했다. 비교 기준은 브랜치 infra;#5의 HEAD e7c0f7533bfe68649035db3a15395d80b3d2e489 → WORKTREE다. 신규 파일도 포함하며 이미 존재한 코드·설정·문서 변경과 스테이징을 보존한다. 이번 동기화의 수정 대상은 이 폴더의 Markdown뿐이다.

실제 변경 및 문서 차이는 다음과 같다.

- [서비스 콘솔 SSH](terraform/stacks/workload.md#콘솔-ssh-및-학원-ssh-규칙의-범위): 리전별 EC2 Instance Connect 관리형 IPv4 접두사 목록을 조회하고 서비스 SG에 TCP 22를 허용한다. 계정별 3 / 2 / 4 / 2 / 3개, 총 14개 SG가 대상이다. 기존 Bastion 규칙의 대상·주소는 유지한다. 이 경로와 [별도 모의 테스트](tests/README.md)를 탐색 목록에도 반영했다.
- [compute 모듈](terraform/README.md#compute): 작업 시작 시 데이터 EBS의 prevent_destroy가 이미 false였다. true로 설명하던 모듈·workload 문서와 무조건 보호 해제가 필요하다고 설명하던 전체 삭제·Bastion 문서를 현재 값과 조건에 맞췄다. 이번 작업은 보호 설정을 변경하지 않았다.
- [계정별 SSH 키](scripts/account-keys.ps1.md): Write-KeyText·Get-KeyTag 함수의 위치를 추가하고 Protect-KeyFile이 기존 소유자를 확인한 뒤 ACL을 설정한다는 설명을 보완했다. 개인키·공개키 파일명 세 개가 Python 함수로 오인되던 Markdown 표기도 정리했다.
- [테스트 지도](tests/README.md): 통과한 서비스 콘솔 SSH 검사와 기존 workload 테스트의 미해결 기대값 차이를 구분했다. 광고 서버 이동 당시의 미실행 기록을 최근의 별도 테스트 성공과 혼동하지 않도록 설명을 갱신했다.

| 검사 | 결과 | 한계 |
| --- | --- | --- |
| routing-doc-sync Python AST | 문서 참조 20개 일치, mismatch 0, diagnostics 0. 추가된 Python 심볼 12개 모두 선언 참조가 있음 | 최종 상태 needs_review, role_status=not_verified. 신규 심볼의 역할과 런타임 동작은 AST가 검증하지 않음 |
| PowerShell 선언 | 실행 코드 6개를 Parser로 읽어 구문 오류 0 확인. 문서의 함수 이름과 대조 | 실행하지 않은 정적 검사이며 AWS·Terraform·SSH 동작 검증 아님 |
| Terraform·JSON·Bash | Git 차이와 실제 선언·설정·설치 범위를 문서와 대조 | Python AST 자동 검사 대상이 아니며 실제 배포 상태를 조회하지 않음 |
| 문서 연결 | 라우팅 문서 21개의 상대 링크·제목 앵커 243개 확인, 누락 0. 대상 소스·설정 58개 모두 문서에서 연결됨 | 경로·앵커 존재 검사이며 역할 설명이나 실제 서비스 성공을 증명하지 않음 |
| 범위 보존 | 시작 시 기록한 소스·설정·외부 안내 69개 해시와 Git index 동일. git diff --check 통과. 변경은 이 폴더의 Markdown 8개에 한정 | 이미 존재한 수정·추가 파일은 이번 문서 변경으로 취급하지 않음 |

분석 자료는 infra/.local/infra-routing-sync-20261010/의 baseline.json, routing-before.json, routing-after.json, links-after.json, scope-after.json에 보관한다. 분석기의 --repo는 실제 Git 최상위 C:/third_project로 지정하고 --docs는 Markdown 파일마다 반복한다. 디렉터리를 --docs로 전달한 최초 호출은 read_error였으며, 파일 목록을 전달해 다시 분석했다. Git 범위에 포함된 platform Python 코드는 이번 문서 수정 대상이 아니다.

서비스 콘솔 SSH 구현 때 Terraform 1.16.5·AWS provider 6.68.0으로 workload validate와 해당 파일의 모의 테스트 5개를 통과했고 변경한 Terraform 파일의 fmt -check도 통과했다. 이번 문서 동기화에서 이를 새로 실행한 결과로 기록하지 않는다. 실제 AWS Plan·Apply·SSH 접속·Squid 설치는 이번에 실행하지 않았다.

기존 workload.tftest.hcl에는 Account 1의 Bastion 포함 노드 기대값과 다른 계정의 bare SG ID 기대값이 남아 현재 구현과 불일치한다. 코드 수정은 이번 요청 범위에 포함되지 않는다. 이 미해결 상태와 기존 변경이 섞여 있으므로 자동 스테이징·커밋을 추가하지 않고 기존 index를 유지한다.

아래 기록의 “현재”와 검사 수치는 각 당시 시점의 값이다. 데이터 EBS의 false 기록과 보호가 유지된다는 설명도 각각 당시 설정을 뜻한다. 최신 작업 파일의 값과 검사 범위는 이 문서 상단의 2026-10-14 기록과 compute 모듈 문서를 기준으로 확인한다.

## 2026-10-09~10 전체 삭제 기능 구현 당시 기록

사용자가 요청한 전체 삭제 실행기를 추가했다. [destroy-all.ps1](scripts/destroy-all.ps1.md)은 모든 삭제 Plan을 준비하고 검토한 실행 ID로 Bastion → workload 5개 → connectivity → foundation 5개를 순차 적용한다. [infra-destroy.ps1](scripts/lib/infra-destroy.ps1.md)에 범위·태그·계획·상태·결과 검사를 두고, 기존 실행기와 fingerprint에 연결했다. 실제 명령은 [실행 README 15절](../operations-recovery.md#6-전체-인프라-삭제)에 있다.

데이터 EBS의 prevent_destroy는 사용자가 수동으로 false로 변경한다. 이번 구현은 원본 compute/main.tf·topology·traffic·backend·키를 수정하거나 보호 해제용 override를 만들지 않는다. 전체 삭제는 데이터 EBS를 포함하며 S3 상태 버킷·이력과 상태 밖 수동 자원은 유지한다. Plan·Apply·Status·Verify 외에 부분 삭제나 AWS 직접 삭제 API는 추가하지 않았다.

| 검사 | 결과 | 한계 |
| --- | --- | --- |
| 전체 삭제 모의 테스트 | Windows PowerShell 5.1·PowerShell 7 각각 17개 시나리오 통과 | 가짜 AWS/Terraform CLI로 검증. 실제 AWS/provider 실행 결과 아님 |
| 기존 실행기 모의 테스트 | 기존 8개 시나리오 재실행 통과 | 기존 workload Terraform 모의 테스트의 알려진 불일치는 별개이며 이번에 수정하지 않음 |
| Python AST | 기존·신규 테스트 문서의 참조 18개 일치, mismatch 0, diagnostics 0 | 새 심볼은 needs_review, role_status=not_verified. AST는 함수 역할이나 런타임 성공을 판정하지 않음 |
| PowerShell 구문 | 실행기·공통 함수 4개를 PowerShell 5.1·7에서 파싱하여 오류 0 | AWS와 Terraform을 실행한 검사는 아님 |
| 문서 링크 | 라우팅 문서와 실행·테스트 README 23개에서 상대 링크·앵커 250개 확인, 누락 0 | 문서의 경로 연결만 검사 |
| 변경 범위 | 작업 시작 시 저장한 해시와 대조하여 compute·설정·키 9개와 Git index가 동일함을 확인. git diff --check 통과 | 이미 존재한 사용자 변경과 숨김 Terraform lock 파일은 이번 변경으로 취급하지 않음 |

새 모의 테스트는 준비 단계에서 Apply를 호출하지 않는지, 모든 상태·계획·공개키를 첫 삭제 전에 대조하는지, 잘못된 계정·접근 거부·계획 변조·다른 자원·생성/수정 계획을 거부하는지 검사했다. 순서 고정, 중간 실패 시 중단, 새 Plan으로 남은 단계 재개, 미생성 Bastion 생략, 상태·AWS ID 잔존 시 완료 거부와 읽기 전용 재검증도 통과했다. 테스트 사본에서만 prevent_destroy를 바꾸며 원본 보호 값은 유지했다.

모의 검증 자료는 infra/.local/tests/destroy-13a63e41a0394a1480d6af62139a3eac(5.1), destroy-b7c7024064654294963f3f2dfe02ca73(7), runner-67891a39에 있다. Python 구조 보고서는 infra/.local/destroy-routing-before.json과 destroy-routing-after.json이다. 비Python 실행 코드와 라우팅 문서는 직접 대조한다.

기존 Bastion 변경과 이번 실행기 변경이 같은 파일에 섞여 있고, 앞서 기록한 workload Terraform 테스트 불일치도 남아 있다. 기존 스테이징을 유지하며 이번에는 스테이징·커밋을 추가로 수행하지 않았다. 계정 설정이나 다른 기능을 문서에 맞추기 위해 수정하지 않았다.

실제 AWS Plan·Apply·삭제는 실행하지 않았다. 마지막 결과 확인은 빈 Terraform 상태와 계획에 기록한 주요 자원의 ID 조회에 한정된다. 개별 라우팅·SG 규칙·리스너는 독립 조회하지 않고 상태와 상위 자원 제거를 확인한다. 기존 수동 자원 때문에 삭제가 막히면 오류로 중단한다. 같은 PC의 전체 삭제 프로세스 잠금과 상태별 S3 잠금을 사용하지만 팀원 PC의 모든 작업을 잠그는 기능은 아니다.

이하 문서 동기화 기록은 전체 삭제 구현 전의 이력이다. 전체 삭제 지원 여부와 이번 검증 결과는 위 내용을 기준으로 한다.

## 2026-10-09 구현 전 작업 파일과의 추가 동기화

사용자 요청에 따라 docs/infra-routing의 미반영 부분만 보완했다. 시작 브랜치는 infra;#5, HEAD는 e7c0f7533bfe68649035db3a15395d80b3d2e489이며 비교 기준은 HEAD → WORKTREE다. 기존 수정·untracked 문서와 config 문서의 staged 변경을 보존한다. 코드·설정·실행 README·AWS 자원은 수정하지 않는다.

현재 코드 대조에서 확인한 내용은 다음과 같다.

- workload는 role != bastion으로 서비스 EC2만 선택한다. 계정별 4 / 2 / 4 / 2 / 3대, 총 15대다. 광고 서버의 Account 1 Private C 배치와 기존 HTTP ALB 전달 설명은 유지했다.
- [Bastion stack](terraform/stacks/bastion.md)은 EC2·삭제 시 함께 제거되는 OS 디스크·전용 키페어를 별도 상태로 관리한다. 자동 공인 IP를 사용하며 EIP는 없다. foundation SG와 workload의 SSH·Proxy 규칙은 유지한다.
- [실행기](scripts/infra.ps1.md)·[관리 스크립트](scripts/bastion.ps1.md)·[공통 함수](scripts/lib/infra-common.ps1.md)에 bastion 단계, 생성/삭제 저장 계획 구분, 전용 자원 범위·태그·중복 검사를 반영했다. 상태 경로는 서비스 11개와 선택 Bastion 1개로 분리한다.
- workload의 다른 계정 SG 참조는 소유 계정 ID/SG ID 형식이다. Account 1 Bastion SG에는 콘솔용 EC2 Instance Connect 접두사 목록 TCP 22 규칙이 별도 자원으로 선언되어 있다. 코드 선언 대조이며 실제 AWS 적용 상태를 새로 확인한 것은 아니다.
- 다섯 계정의 AMI·계정별 공개키 경로와 관리자·사용자 CIDR 입력이 채워진 현재 설정을 반영했다. 구체적인 접속 IP는 문서에 기재하지 않는다.
- [setup-proxy.sh](../../../aws-platform/platform/docs/platform-routing/scripts/install-squid.sh.md)는 수동 Squid 패키지 설치만 수행한다. Proxy ACL·클라이언트 설정·실제 송신 검증이나 Terraform의 자동 설치 기능으로 기록하지 않는다.

## 이번 검사 결과와 한계

| 검사 | 결과 | 한계 |
| --- | --- | --- |
| Python AST | test_runner.py 구조 문서의 파일 참조 1개와 함수 선언 3개 일치. structural_match, mismatch 0, diagnostics 0 | role_status=not_verified. 함수 의미·실제 테스트 성공을 증명하지 않음 |
| 전체 라우팅 문서의 AST 입력 | Python 참조 6개 일치. account-keys 문서의 account2.pem·account5.pem·account5.pub 세 표기가 missing_symbol로 분류됨 | 비Python 파일명을 Python 심볼로 인식한 결과. 실제 공개키/개인키 안내를 잘못된 Python 선언으로 취급하지 않으며 올바른 표기는 유지 |
| PowerShell·Terraform·JSON·Bash | 실제 원본의 입력·선택 조건·자원·출력·계획 보호·설치 범위를 문서와 직접 대조 | Python AST 자동 검사 범위 밖. 이번에는 실행기·Terraform 테스트·Plan·Apply·AWS 조회·Squid 설치를 실행하지 않음 |
| 문서 링크 | 새 Bastion·Proxy 문서를 포함한 18개 Markdown의 상대 경로·제목 앵커 검사 | 파일과 앵커 존재 확인이며 기능 동작 검증 아님 |
| 변경 범위 | 시작 시 코드·설정·외부 문서의 해시 및 Git index를 기록해 종료 시 대조 | 기존 사용자 변경은 이번 구현 결과로 취급하지 않음 |

분석 보고서는 infra/.local/routing-sync-pre.json, routing-sync-post.json 및 routing-sync-python-post.json에 보관한다. 전체 문서 분석의 비Python 심볼 판정과 Python 전용 구조 검사 결과를 구분한다. Python 선언이 이미 일치하므로 해당 구조 문서를 불필요하게 다시 작성하지 않았다.

## 남겨 둔 조건

- [기존 workload 모의 테스트](tests/README.md#현재-입력과-모의-테스트의-범위)는 Account 1에 Bastion 포함 5대와 다른 계정의 bare SG ID를 기대하여 현재 구현과 불일치한다. 이번에는 차이만 기록하고 테스트 코드를 수정하지 않았다.
- 당시에는 전체 인프라 삭제 실행기가 없고 Delete 계획이 bastion 단계에만 허용됐다. 위 구현으로 전체 삭제 실행기가 추가됐으며 원본 서비스 데이터 EBS의 prevent_destroy는 계속 유지한다.
- 루트 README·infra/README.md 등 라우팅 폴더 밖에 있는 이전 배치·Bastion·HTTPS 설명은 이번 수정 범위 밖이다.
- 실제 AWS 생성·삭제, 접속·서비스·Proxy·데이터 보존 검증은 이번 문서 동기화에서 수행하지 않았다. 이 조건들이 남아 있어 자동 스테이징·커밋은 하지 않으며 기존 index를 유지한다.

## 이전 작업의 검증 기록

아래 기록의 “현재”와 검사 수치는 각 이전 작업 시점의 값이다. Bastion 포함 workload·빈 관리자 CIDR 등의 설명은 위 추가 동기화로 갱신됐으며 현재 구현 설명으로 사용하지 않는다. 과거 결과와 오류·승인 기록은 보존한다.

<details>
<summary>이전 광고 서버 이동·문서 대조 기록 보기</summary>


[탐색 시작점](ROUTING-README.md) · 로컬 적용 규칙: AGENTS.md(Git 제외)

## 광고 서버 account1 이동 후 추가 검증

2026-10-09 광고 서버 이동 작업에서는 topology·traffic JSON, model·workload·alb의 main.tf 등 요청된 코드·설정 5개와 이번 변경에 관련된 라우팅 문서만 수정했다. 아래 기존 문서 작업 기록의 수정 범위·미실행 표시는 당시 기록이다.

- 서버 배치: account1 Private C의 ad-server, 계정별 5 / 2 / 4 / 2 / 3대, 전체 16대. ad의 사양·디스크·공인 IP 설정은 수정 전과 동일하다.
- 연결: alb_ad의 TCP 8000, ad 대상 그룹·EC2 연결, 우선순위 20의 /ads/* 규칙. 기존 /static/* 규칙과 game 기본 대상은 유지한다.
- JSON을 작업 시작 시점과 구조적으로 비교해 광고 서버의 account, 광고용 ALB 항목 세 개, ad 포트와 alb_ad 연결 외의 값이 같음을 확인했다.
- 변경한 Terraform 3개 파일의 fmt -check와 workload의 validate가 통과했다. validate는 처음 샌드박스에서 provider 응답 오류가 발생했고, 승인된 샌드박스 밖 재실행에서 통과했다.
- routing-doc-sync 분석기로 기존 Python 구조 문서의 참조를 재검사했다. Python 구조 검사는 Terraform·JSON의 동작 검증이 아니며, 이번 비Python 변경은 해당 원본과 라우팅 문서를 별도로 대조했다.
- 최초에는 테스트 파일을 유지했으나 사용자 추가 승인 후 fixtures.json 및 foundation/workload 테스트 파일을 변경된 배치에 맞췄다. account1에 ad SG와 광고 노드를 포함하고 account2에서는 제외했다. workload에는 ALB→ad:8000 양방향 SG 참조 검사를 추가하고 닫힌 기본값 검사에서만 CIDR을 비웠다. 자세한 내용은 [테스트 지도](tests/README.md#현재-입력과-모의-테스트의-범위)에 기록했다.
- 테스트 파일 두 개의 fmt -check와 fixture JSON의 계정별 역할 대조는 통과했다. workload 모의 테스트는 샌드박스 밖 실행 권한 요청이 거절되어 시작하지 못했다. foundation 모의 테스트도 이번에 실행하지 않았으므로 실행 통과 여부는 미확인이다.
- 실제 AWS Plan·Apply, 서버 이동·삭제, Django 실행과 /ads/·헬스 체크 /의 응답 검증은 수행하지 않았다. Django 앱 소스가 없어 URL·ALLOWED_HOSTS 설정도 확인하지 못했다.
- 모의 테스트 실행 검증이 남아 있어 자동 스테이징·커밋은 하지 않았다.

## 현재 대조 기준

- 확인일: 2026-10-09.
- 프로젝트 루트: C:/third_project/aws-infra.
- Git 최상위 경로: C:/third_project. 스킬의 --repo는 이 경로를 사용한다.
- 작업 시작 브랜치: infra;#5.
- 작업 시작 HEAD: e7c0f7533bfe68649035db3a15395d80b3d2e489.
- 비교 기준: HEAD → WORKTREE. 현재 작업 파일과 시작 시 이미 존재한 미커밋 변경을 대조했다.
- 수정 범위: docs/infra-routing 안의 Markdown 문서. 코드·설정·외부 문서·Git index는 수정하지 않는다.

작업 시작 시 HTTP 전환 코드, S3·AMI·사용자 CIDR 설정, 실행 README, 기존 라우팅 문서 변경이 이미 있었다. bastion.ps1과 대응 문서는 untracked였고 config/README.md 및 실행 README에는 staged 변경도 있었다. 이번 작업은 이 기존 상태를 유지하며 문서를 보완한다. 사용자의 추가 요청에 따라 구체적인 접속 IP 값은 문서에서 제외한다.

## 스킬 사용과 Python 검사

사용자가 요청한 구조 대조에는 설치된 routing-doc-sync를 사용했다. SKILL.md와 references/report-contract.md를 읽고 Python 3.12.10으로 분석기를 실행했다. 실제 설치 경로는 C:/Users/Playdata/.agents/skills/routing-doc-sync다.

분석기는 프로젝트 Python 코드를 import하거나 실행하지 않고 AST를 읽는다. 처음에 프로젝트 하위 폴더를 --repo로 지정한 실행은 Git 최상위 경로가 아니라는 execution_error로 중단됐다. 이후 C:/third_project를 지정해 정상 분석했다.

정상 분석의 inventory에는 aws-infra/infra/tests/test_runner.py와 platform/tests/spark_integration.py 두 파일이 포함됐다. 이 문서 작업에서 함수 선언과 문서를 대조한 대상은 [test_runner.py 구조 문서](tests/test_runner.py.md)의 실행기 테스트 한 파일이다. platform의 문서는 대조 대상이 아니다.

수정 전 Python 문서의 정규 참조 세 개는 Git 기준 aws-infra/ 접두사가 없어 missing_file이었다. 원본 파일의 상대 링크는 맞았으며 함수 선언도 실제로 존재했다. 정규 참조만 Git 기준으로 수정했고, Python 코드는 변경하지 않았다.

최종 결과는 파일 참조 1개 file_match, 함수 run·calls·count_apply의 선언 참조 3개 signature_match다. 구조 일치는 확인했으나 role_status는 not_verified이며 함수 역할의 의미나 실제 테스트 성공을 증명하지 않는다.

실행기 테스트의 현재 SHA-256은 baa9b9fb9f589784454a72e32f0d340f7771de6d723e255b54ad53d6d68c39b0이다. HEAD 비교에서 이 파일의 바이트 해시 차이는 있지만 structural_changed=false이고 변경 심볼은 없다.

## 검사별 근거와 결과

| 검사 | 근거·결과 | 한계 |
| --- | --- | --- |
| Python 파일·함수·시그니처 | 최종 structural_match, 검사 참조 4개, mismatch 0개, diagnostics 0개 | 대상 함수의 의미·런타임 동작은 not_verified |
| PowerShell 구조 | 실행기·공통 함수·Bastion 스크립트 원본의 매개변수·함수·처리 순서 대조 | Python AST 스킬의 검사 대상이 아님 |
| Terraform 구조 | model·ALB·workload와 대응 문서의 입력·자원·출력·참조 대조 | Terraform validate/test/plan/apply 미실행 |
| 설정 | backend·topology·traffic의 현재 JSON 값 대조 | 문서가 AWS 계정이나 자원 상태를 조회하지 않음 |
| 문서 연결 | Markdown 문서 15개, 상대 링크·앵커 최종 수는 아래 기록 | 파일 존재·Markdown 제목 앵커 검사이며 실제 서비스 동작 검증 아님 |
| 원본 파일 연결 | 생성물·lock 파일을 제외한 .tf/.ps1/.sh/.py/.json/.pub/.hcl 40개, 문서에서 연결되지 않은 파일 0개 | 개별 파일마다 별도 Markdown을 만들지는 않으며 모듈 목록 방식도 유지 |
| 범위 보존 | 시작 시 기록한 코드·설정·외부 README 등 47개 파일 해시 동일, 기존 index 동일 | 현재 문서 폴더 밖의 오래된 설명은 수정하지 않음 |

최종 상대 링크·Markdown 앵커는 153개를 대조했고 누락은 0개다. 링크 검사는 실제 AWS 동작이나 파일 역할 설명의 의미를 보증하지 않는다.

## 이번에 보완한 문서

- [Terraform 모듈 지도](terraform/README.md): ALB 입력에서 인증서 제거, HTTP 80 기본 전달, 같은 리스너의 정적 파일 규칙, 현재 노드별 enabled 제외 기능 미구현.
- [workload 구조](terraform/stacks/workload.md): 외부 HTTP 80과 내부 Front 80·game 8000, Bastion SSH 22, 인터넷 HTTPS egress의 구분.
- [실행기 구조](scripts/infra.ps1.md): ACM 필수 검사 제거와 유지되는 AMI·공개키 검사.
- [설정 지도](config/README.md): 사용자 CIDR의 역할, Bastion 생성 대상과 빈 관리자 CIDR, S3·AMI 준비 상태, 공통 타입에만 남은 certificate_arn. 구체적인 접속 IP 값은 제외.
- [bootstrap 경계](bootstrap/README.md): Front 정적 파일·Nginx 배포 미구현과 기존 Bastion 전원 스크립트의 범위.
- [배스천 전원 제어](scripts/bastion.ps1.md): 현재 SSH 준비 상태와 과거 모의 검증 기록의 한계.
- [Python 구조](tests/test_runner.py.md): Git 기준 정규 참조 경로와 현재 AST 분석 결과.
- [테스트 지도](tests/README.md): 현재 사용자 CIDR 입력과 닫힌 기본값을 기대하는 workload 테스트의 차이.

## 남아 있는 코드·검증 조건

| 위치·항목 | 현재 확인한 상태 | 이번 문서 작업의 처리 |
| --- | --- | --- |
| workload 모의 테스트 account1_default_closed | 현재 traffic을 읽지만 public_ingress=0을 기대. 현재 사용자 CIDR 입력으로는 HTTP 규칙이 생성돼 가정 불일치 | 테스트 코드는 유지하고 차이를 기록. 실패를 실제 실행으로 확인한 것은 아님 |
| model·workload의 Bastion 포함 | 현재 nodes에 bastion이 있고 노드별 enabled 제외 필터가 없음 | 생성 대상임을 명시. 선택 생성·제외 기능을 구현했다고 기록하지 않음 |
| Bastion SSH | 현재 admin_public_cidrs=[] | 외부 SSH 허용 규칙이 없음을 기록. 관리자 IP는 변경하지 않음 |
| HTTP ALB 서비스 준비 | 정적 파일 배포·Nginx·Django 설치·실행 자동화 없음 | ALB 대상 등록과 프로그램 설치·healthy 상태를 구분 |
| 기존 Bastion 모의 검증 기록 | 기존 문서에 PowerShell 5.1/7.6 모의 사례·로컬 TCP 사례가 기재돼 있으나 검증용 파일이 보관돼 있지 않음 | 기존 기록을 유지하며 이번 재실행·독립 검증 결과와 구분 |
| infra/README.md 및 infra/scripts/README.md | HTTP 전환 전 HTTPS·ACM 필수 설명과 일부 과거 빈 입력 설명이 남음 | 요청한 문서 폴더 밖이므로 수정하지 않음 |
| 프로젝트 README 등 과거 설계 문서 | Mermaid 수량·옛 경로·설치기와 stack의 버전 조건 차이가 남음 | 현재 코드 탐색은 이 폴더 문서로 안내하며 프로젝트 전체 동기화 완료로 판정하지 않음 |

이 조건들이 남아 있어 자동 스테이징·커밋은 진행하지 않는다. 실제 AWS 배포·SSH·Proxy·프로그램 설치·성능·DB 보존 검증을 이번 문서 검사에서 실행한 것으로 기록하지 않는다.

## 이전 기록과 이번 결과의 구분

이 문서의 최초 작성 기록은 dev 브랜치의 6b6793a51e2c56a69f40dcd8a4f0bedfa011f7f3를 기준으로 했다. 당시 새 문서 14개와 상대 링크 131개를 기록했고 Python 파일도 untracked로 조사했다. 그 수치와 needs_review는 당시 기준의 기록이며, 현재 기준의 결과는 위 표를 따른다. 과거 루트 README를 Python 문서 검사에 함께 넣어 비Python 표기가 missing_symbol로 분류된 기록도 실제 Python 선언 오류와 구분한다.

## 재현 명령

다음 명령은 C:/third_project/aws-infra에서 실행해도 된다. Git 최상위 경로와 저장소 기준 문서 경로를 명시하며, 보고서만 임시 폴더에 저장한다. 다른 PC에서는 스킬 설치 경로를 해당 위치로 바꾼다.

```powershell
# Git 최상위 경로와 검사할 Python 구조 문서를 지정한다.
$routingSkill = 'C:\Users\Playdata\.agents\skills\routing-doc-sync'
$routingRepo = (git rev-parse --show-toplevel).Trim()
$routingDocument = 'aws-infra/docs/infra-routing/tests/test_runner.py.md'
$routingReport = Join-Path $env:TEMP 'infra-routing-python-head.json'

# 프로젝트를 실행하지 않고 HEAD와 현재 선언·문서만 분석한다.
python "$routingSkill\scripts\routing_doc_sync.py" --repo $routingRepo --docs $routingDocument --base HEAD --target WORKTREE --output $routingReport
```

변경 이력을 제외하고 현재 선언만 확인하려면 --base HEAD를 --base NONE으로 바꾼다. 코드나 문서가 바뀌면 보고서를 다시 생성한다. PowerShell·Terraform·JSON·Bash는 별도 원본 대조와 문서 링크 검사 대상이며 위 Python 명령 하나로 검증되지 않는다.

</details>

## 2026-10-10 구성별 배포 실행기

deploy.ps1, infra.ps1의 ConfigurationDirectory와 공통 경로·fingerprint 처리를 추가했다. 시작 브랜치는 infra;#5, HEAD는 e7c0f7533bfe68649035db3a15395d80b3d2e489이며 이전 Terraform·스크립트·문서 변경과 스테이징 상태를 보존했다.

PowerShell 문법 세 파일, 임시 NewProfile 생성·덮어쓰기 차단, 구성 해시 변경, 구성별 Plan 경로 분리를 로컬에서 확인했다. 가짜 AWS·Terraform 출력으로 빈 계정, 계정 이동에 따른 키 선택, 역할 그룹 매핑, 현재 주소, 프록시 CIDR, 중지 서버 거부를 확인했다. 개인키를 읽거나 실제 AWS·SSH·Terraform 배포를 실행하지 않았다.

변경분의 git diff --check, 새 파일 문서 세 개의 로컬 링크 15개, 구성과 인벤토리의 Git 제외, 두 Bash 파일의 LF 속성을 확인했다. Git Bash 문법 검사 시도는 종료 코드 1과 빈 진단으로 끝나 통과 여부를 확인하지 못했다. 새 Ansible playbook·WSL 연결·실제 프로필 배포는 사용자 검증이 필요하다.

Python용 routing-doc-sync로 PowerShell·Bash·YAML의 실제 실행을 검증할 수 없다. 구조 참조의 needs_review와 역할 의미 not_verified를 유지하며 실제 실행 통과로 해석하지 않는다. 위 미검증 범위 때문에 이번 변경을 자동 스테이징하거나 커밋하지 않았다.

## 2026-10-10 deploy.ps1의 Windows PowerShell 5.1 인코딩 수정

이전 로컬 파서 검사는 PowerShell 7.6.5에서 수행했다. 이후 사용자가 Windows PowerShell에서 NewProfile을 실행할 때 문자열 종료와 닫는 중괄호 오류를 보고했다.

Windows PowerShell 5.1.26100.9444의 ParseFile로 원본 deploy.ps1에서 동일한 오류 4개(212·210·207·200행)를 재현했다. deploy.ps1에 UTF-8 BOM이 없었으며 함께 사용하는 infra.ps1·infra-common.ps1·infra-destroy.ps1에는 이미 BOM이 있었다.

deploy.ps1에 EF BB BF 세 바이트만 추가했다. 디코딩한 전체 소스 내용은 수정 전과 같음을 확인했다. 이후 Windows PowerShell 5.1 파서에서 deploy.ps1·infra.ps1·infra-common.ps1 세 파일 모두 오류 0개를 확인했다.

임시 폴더를 대상으로 한 NewProfile 실행 시도는 검사 환경의 AuthorizationManager check failed로 차단되어 실제 실행 통과로 기록하지 않는다. 실행 정책을 변경하지 않았고 실제 사용자 current 구성도 생성하지 않았다. AWS·Terraform·SSH·Ansible은 실행하지 않았다.

## 2026-10-10 deploy.ps1의 WSL 실행 경로 선택 수정

Windows PowerShell 5.1.26100.9444에서 Get-Command wsl이 System32와 WindowsApps의 실행 파일 두 개를 반환하는 것을 확인했다. 기존 코드가 두 Source를 배열로 받아 호출 연산자에 전달하면 사용자가 보고한 CommandNotFoundException이 재현됐다. 이 오류는 WSL과 Ansible 실행 전에 발생한다.

Invoke-DeploymentProxy에서 검색 결과의 첫 실행 파일 하나만 선택하도록 수정했다. 같은 PowerShell 5.1에서 문법 오류 0개, UTF-8 BOM 유지, 실제 선택 경로가 System32의 단일 문자열임을 확인했다. 원본 함수에 WSL 호출 대역을 연결해 후보가 한 개·두 개인 경우 모두 경로 변환 두 번과 프록시 Bash 호출 한 번으로 이어지고, 배포판·가상환경·인벤토리·Limit 인수가 유지되는 것을 확인했다.

실제 WSL·AWS·Terraform·SSH·Ansible 실행은 하지 않았다. 이 기록은 경로 선택 오류의 로컬 재현·수정 확인이며 원격 프록시 준비 완료를 의미하지 않는다. 기존 미검증 변경과 같은 파일에 섞여 있어 자동 스테이징·커밋은 진행하지 않았다.

## 2026-10-10 ZooKeeper 통신 포트 누락 수정

사용자가 실행한 서비스 설치에서 MySQL 2대·MongoDB 3대·Kafka 3대는 failed=0, Spark 노드 3대는 ZooKeeper Mode 검사에서 failed=1이었다. 추가 조회에서 세 ZooKeeper 모두 요청을 처리하지 않는다는 응답을 반환했고, Spark 노드 사이의 TCP 3888 연결 여섯 개가 모두 timeout 종료 코드 124였다. 실제 AWS 보안그룹·라우팅 상태는 이 로컬 작업에서 직접 조회하지 않았다.

기본 infra/config/traffic.tfvars.json과 사용 중인 profiles/current/traffic.tfvars.json에 ZooKeeper 포트가 없음을 확인하고 zookeeper_client=2181, zookeeper_peer=2888, zookeeper_election=3888을 추가했다. 각 연결의 sources와 targets는 모두 spark만 지정한다. OS 방화벽의 기존 Spark 노드 간 허용 설정은 변경하지 않았다.

두 JSON에 대해 Windows PowerShell 5.1.26100.9444의 Assert-InfraConfiguration과 연결의 포트 키 존재 검사를 통과했다. Ansible ZooKeeper defaults의 세 포트와 일치하며, 새 포트·연결 각각 세 항목을 제거하면 수정 전 JSON과 의미상 동일함을 비교했다. 현재 topology의 Spark 계정은 account2·account3·account4다. model/workload의 역할별 SG 연결 계산상 계정당 ingress 9개·egress 9개, 총 54개 규칙 추가가 예상되지만 이는 실제 Terraform Plan 결과가 아니다.

AWS Plan·Apply와 원격 ZooKeeper 재검증은 사용자 실행 단계로 남긴다. 이번 수정은 ZooKeeper 통신 복구 범위이며 Spark 설치 완료를 뜻하지 않는다. 후속 Spark 설정에는 Worker RPC 포트 고정, Driver·BlockManager 포트와 현재 허용값의 일치, Master UI 8080 조회 허용을 별도로 맞춰야 한다. 기존 변경과 섞인 파일이며 AWS 적용 결과가 없으므로 자동 스테이징·커밋은 하지 않았다.

## 2026-10-10 전체 삭제의 서비스 콘솔 SSH 허용 목록 보완

사용자가 전체 삭제를 준비하는 과정에서 **aws_vpc_security_group_ingress_rule.service_console_ssh["ad"]**를 단계 밖 자원으로 거부하는 오류를 보고했다. workload/main.tf에는 해당 역할별 자원이 있지만 Assert-InfraDeletePlan의 workload 허용 목록에는 기존 Bastion 콘솔 SSH 주소만 있었다.

infra-destroy.ps1의 workload 주소 패턴에 정확한 service_console_ssh 이름과 문자열 역할 키 형식만 추가했다. 단계 순서·태그·계정·delete/no-op·데이터 EBS 동의·저장 계획 해시 검사는 유지한다. 소스 변경으로 기존 실패 실행 ID를 재사용하지 않고 새 Plan을 생성해야 한다.

별도 test_destroy_console_ssh.ps1에서 실제 오류 주소를 포함한 현재 서비스 역할 7개와 기존 Bastion 주소를 허용하고, 비슷한 자원 이름·잘못된 키·추가 주소·관련 없는 자원·다른 단계·계정 태그 불일치·수정·import를 거부하는 16개 검사를 Windows PowerShell 5.1에서 통과했다. AWS·Terraform 실행 파일은 호출하지 않았다. 기존 전체 삭제 모의 테스트 17개를 이번에 재실행한 결과로 취급하지 않는다.

관련 라우팅 문서와 테스트 탐색 링크를 갱신했다. Python AST 분석기의 역할 의미 not_verified와 비Python 검사 한계를 유지하며 PowerShell 실행 검사와 구분한다. 실제 사용자 삭제 Plan·Apply·AWS 삭제 완료는 아직 확인하지 않았고, 기존 Git 스테이징 상태를 보존했다.


## 2026-10-11 스테이징 범위 문서 대조

기존 스테이징 13개 파일(Consumer·비용·보안규칙·Terraform 모의 검사·팀 접속 스크립트·common sudo 수정)을 보존하고 광고 서버 AZ A 변경과 직접 관련된 안내·라우팅 문서만 추가했다. MySQL-3 증설과 Consumer OS 방화벽 등 기존 비스테이징 소스는 포함하지 않는다. 따라서 스테이징 topology는 서비스 EC2 16대·선택 Bastion 포함 17대, A 12대·C 5대·MySQL 2대이며 작업 파일의 3노드 MySQL 구성과 다르다. 이 스테이징만으로 InnoDB Cluster 구축 준비가 완료됐다고 판단하지 않는다. 기존 AWS 검증 기록은 당시 이력으로 보존하며 사용자의 전체 자원 삭제 확인은 사용자 진술로 구분한다. 문서 이동 중인 관련 경로는 스테이징에 존재하는 신규·기존 문서를 연결해 미선택 문서 이동을 섞지 않는다. AWS 생성·삭제·원격 Ansible·커밋은 실행하지 않았다.


스테이징 snapshot을 별도 폴더에 복사해 routing-doc-sync를 실행했다. 전체 영향 문서의 자동 검사에서 비용 수식·EC2 유형·JSON 키·YAML/PowerShell 파일명을 Python 심볼로 해석한 38개 missing_symbol이 나왔으며, 모두 Python 선언이 아닌 표기여서 Python 불일치로 확정하지 않는다. 실제 Python 참조와 비Python 링크·설정은 별도로 대조한다. 전체 스킬 결과를 성공으로 표현하지 않는다.

## 2026-10-11 애플리케이션 통신 규칙

비교 기준은 ca25963a8a9facea03b29ead07308ab95721b0dc와 작업 파일이다. 현재 저장소 위치는 C:/third-project/aws다. 기본 traffic과 로컬 current 프로필에 Front→게임·광고, 게임↔광고, Consumer·광고→MongoDB, 광고→MySQL, MySQL→Kafka·게임·광고 10종류를 추가했다. 새 역할·계정 SG 연결은 28쌍이고 기존 연결 삭제는 0개다. 외부 CIDR·공개 포트·ALB 배치는 변경하지 않았다.

- Terraform validate: 통과.
- application-flows.tftest.hcl: 계정별 5건 통과.
- flatten.tftest.hcl: 4건 통과. MongoDB 3대 송신을 포함해 Consumer egress 기대값을 7개로 변경.
- workload spark-ports.tftest.hcl: 4건 통과.
- fixtures.json: 누락돼 있던 account4/mysql 모의 SG 추가.
- 기본/current 설정 일치, 기존 연결 보존, git diff --check 확인.
- 플랫폼 firewall: 역할 템플릿 9종과 출처 검사 67건 통과.

13개 Terraform 검사는 모의 AWS provider와 고정 원격 상태를 사용했다. 실제 AWS Plan·Apply, 원격 Ansible, 서비스 데이터 송수신, 전체 Terraform 테스트는 실행하지 않았다. 이번 변경의 통과 결과를 이전 배포·클러스터 장애 검증에 확대하지 않는다.

routing-doc-sync 스킬로 관련 문서를 읽기 전용 분석했다. 이번 JSON·Terraform·YAML 관계는 Python AST 자동 참조 검사의 지원 범위 밖이므로 관계 목록·포트·테스트 선언·문서 링크는 직접 대조한다. 과거 검증 기록은 당시의 결과로 유지한다.

문서 최종 대조에서 수정 문서 11개의 로컬 파일 링크 240개에 누락 경로가 없고, 보안그룹 연결 표 33개와 방화벽 역할 표 8개가 코드와 일치함을 확인했다. routing-doc-sync는 관련 라우팅 문서 3개에서 diagnostics 0·mismatch 0을 반환했지만 지원 참조가 없어 checked_references=0, structural_status=needs_review, role_status=not_verified였다. 이는 자동 검증 완료가 아니며 위 직접 대조와 로컬 실행 결과로 검증 범위를 한정한다.

## 2026-10-11 ALB 비활성화

사용자 요청에 따라 기본 및 profiles/current의 topology.alb.enabled=false와 traffic의 alb_front·alb_game·alb_ad 제거만 설정에 반영했다. 시작 HEAD는 ca25963a8a9facea03b29ead07308ab95721b0dc이며, 앞선 애플리케이션 연결·방화벽 작업의 스테이징 16개 파일과 별도 aws-infra-test/ 폴더를 유지했다. 이번 비교는 그 작업 파일 상태를 기준으로 한다. current 프로필은 Git 제외 대상이다.

- 설정 객체 대조: ALB 활성화 값과 연결 3개 이외의 노드·EIP 입력·디스크·CIDR·포트·서비스 연결은 동일하다. 현재 연결은 30개이며 보안그룹 문서 표의 출발지·목적지·포트와 모두 일치한다.
- Terraform workload validate 통과. 모의 테스트는 workload 8개, application-flows 5개, flatten 4개, spark-ports 4개, foundation 3개로 총 24개 통과했다. AWS provider 및 원격 상태는 모의 처리했다.
- ALB SG가 남은 foundation 출력과 SG를 제거한 출력 모두 검사했다. ALB 모듈·DNS·연결 없음, 기존 Front·게임·광고 서버와 Front→게임·광고 8000 유지, 명시적으로 다시 활성화한 프로필을 확인했다. 기존 테스트의 Bastion 분리·mysql-3·계정 간 SG 참조 기대값도 현재 구현에 맞췄다.
- 관련 문서 9개의 로컬 파일 링크 201개를 확인해 누락 경로가 없었다. 이 검사는 앵커 존재 여부나 원격 사이트 내용을 확인하지 않는다.

기존 ALB 자원은 account1 workload에서 먼저 정리하고, 참조가 사라진 뒤 foundation의 ALB SG를 정리하도록 [배포 절차](../deployment-runbook.md#alb-비활성화-적용-순서)에 기록했다. 실제 AWS Plan·Apply·삭제·SSH·Ansible을 실행하지 않았다. Front 외부 웹 인바운드, Nginx·인증서·HTTPS는 후속 작업이다.

routing-doc-sync의 Python AST 자동 분석은 이번 JSON·Terraform 참조를 지원하지 않는다. 설정·보안그룹 표와 모의 테스트로 해당 범위를 별도 확인하며 자동 심볼 검증 성공으로 해석하지 않는다.

추가 문서 요청에 따라 운영·요구사항·설치·비용 안내까지 관련 문서 21개를 동기화했고 로컬 파일 링크 449개에서 누락 경로가 없었다. 과거 실행·가격 계산은 당시 기록으로 유지했으며 새로운 가격 조회나 비용 재계산은 하지 않았다. routing-doc-sync 자동 검사는 Python 참조가 없는 JSON·Terraform 영역에서 needs_review / not_verified이며 별도 설정 대조와 위 모의 테스트가 검증 근거다.

## 2026-10-11 진입용 edge-1 생성 설정

직전 ALB 비활성화·애플리케이션 연결 작업의 스테이징 32개 파일을 유지한 상태에서 시작했다. HEAD는 ca25963a8a9facea03b29ead07308ab95721b0dc다. 별도 aws-infra-test/는 수정하거나 스테이징하지 않는다.

기본 및 current 설정에 edge-1(account1 Public A, role=edge, t3a.small, OS gp3 20GiB, EIP, 별도 데이터 디스크 없음)을 추가했다. edge_front TCP 80과 기존 admin_nodes·forward_proxy의 edge 확장으로 Front·SSH·다운로드 경로만 준비한다. 기존 모든 노드 객체와 MySQL 3대, 나머지 연결·CIDR·포트·인터넷 송신 설정이 시작 상태와 같음을 객체 대조로 확인했다. 서비스 EC2 18대, Bastion 포함 19대, 전체 EBS 4,280GiB이며 workload EIP는 3개다. 전용 SG를 포함해 총 18개, connections는 31개다.

workload validate 통과. edge 1개·application-flows 5개·flatten 4개·spark-ports 4개·workload 8개가 통과했다. 콘솔 SSH 최초 실행에서는 기존 account4 테스트의 mysql 역할 기대값 누락으로 1개가 실패했으며, 테스트 목록을 실제 선언인 kafka·mysql·spark로 보완한 뒤 콘솔 SSH 5개가 모두 통과했다. foundation 3개도 통과했다. 최종 확인한 고유 모의 테스트는 총 30개다. MySQL 서비스 설정과 실제 서버는 변경하지 않았다.

AWS provider·원격 상태는 모의 처리했다. 실제 AWS Plan·Apply·EC2 생성·인벤토리 생성·SSH·Ansible은 실행하지 않았다. 외부 80·443, Nginx·Certbot·least_conn과 원격 OS 방화벽은 후속 설정이다. EIP를 선언했다고 HTTPS가 동작하는 것은 아니다. 기존 ALB 정리가 남은 환경은 edge 없는 전환 입력으로 ALB 참조를 정리한 뒤 edge foundation→workload를 적용하도록 배포 절차에 기록했다.

보안그룹 표의 31개 연결과 포트를 설정에 대조했고 관련 문서 17개의 로컬 파일 링크 338개에 누락 경로가 없었다. 비용 문서는 새 수량과 과거 견적을 구분했으며 가격 조회·재계산은 하지 않았다. routing-doc-sync의 Python AST 분석이 지원하지 않는 Terraform·JSON 의미는 모의 검사와 설정 대조로 확인한다.

## 2026-10-11 edge HTTPS 실제 구축

시작 HEAD는 ca25963a8a9facea03b29ead07308ab95721b0dc이며 기존 스테이징 35개와 aws-infra-test/를 보존했다. 이번 실제 적용은 Account 1 foundation과 edge 단독 초기 구축이다. 다른 EC2·ALB의 생성이나 전체 삭제는 실행하지 않았다.

- foundation: 22 added, 0 changed, 0 destroyed. workload: 18 added, 0 changed, 0 destroyed.
- edge-1: i-0fc792099ad53451a, t3a.small, Ubuntu 24.04, root gp3 20GiB, Private IP 10.10.0.39, EIP 54.116.158.93.
- SG는 인터넷 ACME 80, 당시 허용 사용자 211.117.107.63/32의 443, 관리 SSH, 패키지·ACME용 HTTPS 송신과 지정한 내부 연결을 허용한다. Nginx HTTP는 인증 검증 경로 외 404, HTTPS는 허용 CIDR과 localhost만 수용한다.
- edge.yml 실제 실행: ok=85, changed=29, unreachable=0, failed=0. Certbot 5.8.0, Nginx, OS 방화벽, 설치 확인 페이지, 인증서 발급과 자동 갱신을 적용했다.
- 정식 인증서 IP SAN은 54.116.158.93, issuer는 Let's Encrypt YE2, 만료는 2026-10-18 04:26:06 UTC다. 외부 curl의 신뢰 검증을 켠 HTTPS 200, HTTP / 404, 비허용 출처의 Nginx 403을 확인했다.
- edge-certbot-renew.timer 활성·자동 시작을 확인했다. 최초 발급 사전 검증과 설치 후 renew --dry-run이 모두 성공했고 Nginx 검사·reload 훅도 성공했다. 실제 미래 갱신 결과까지 확인한 것은 아니다.
- Front upstream은 비어 있어 설치 확인 페이지만 제공한다. Front A/B 화면 배포, 게임·광고 API, least_conn 실제 분산은 아직 검증하지 않았다.

로컬 검증은 Terraform workload validate 및 고유 모의 테스트 28개, 실행기 기존 모의 검사 8개, edge 생성 계획 보호 7개, 삭제 표식·허용 주소 검사 6개가 통과했다. 플랫폼 YAML·Jinja 렌더링, Ubuntu 미러 URL 6종, Nginx 3상태, 방화벽 CIDR, 발급·갱신 인수와 edge.yml/site.yml 문법도 통과했다.

전체 삭제 회귀 검사에서 기존 테스트 fixture가 운영 prevent_destroy=false를 그대로 복사해 보호 거부 시나리오에 실패했다. 테스트 사본에만 시나리오별 보호값을 명시하도록 보완했으며 운영 compute/main.tf는 이번 작업에서 변경하지 않았다. 실제 AWS 삭제 검증과 모의 검사를 구분한다.

routing-doc-sync는 Python 파일·심볼 구조를 분석하며 Terraform·Ansible·Nginx의 의미 검증을 대신하지 않는다. 해당 범위의 근거는 위 모의 실행·렌더링·실제 서버 확인이다.

최종 전체 삭제 회귀 검사 17개가 통과했다. 실제 AWS 삭제는 실행하지 않았다. 관련 변경 문서 31개의 로컬 파일 링크 423개에서 누락 경로가 없었다. 전체 문서를 대상으로 한 routing-doc-sync는 README의 셸 명령과 YAML 이름 등을 Python 경로·심볼로 해석해 9개 mismatch를 출력했다. 실제 Python 실행 파일 경로와 해당 비-Python 문맥을 따로 확인했으며 이 결과를 자동 검증 통과로 표시하지 않는다. Terraform·YAML 의미는 별도 검사 범위다.

삭제 순서 보완 후 실제 edge workload의 새 Plan은 No changes였고 Apply는 0 added·0 changed·0 destroyed였다. 원격 상태에서 connectivity_ready의 edge_bootstrap_guard 의존성을 확인했다. 이 작업은 EC2·EIP를 교체하지 않았다.

## 2026-10-12 학원 IP 및 HTTP/SSH 정책 변경 검증

- 최종 학원 IP: 222.112.208.69/32. 기본/current/테스트 traffic에 반영했다.
- workload Terraform 모의 테스트: 기존 33개 + 테스트 구성 10개, 총 43개 통과.
- 각 계정의 Private 역할별 학원 SSH 22, Front HTTP 80 전체 공개, Bastion 콘솔 SSH 미생성, 전체 공개 SSH 미생성을 검사했다.
- 기존 웹 비공개 테스트는 public_http_cidrs=[]를 명시해 비공개 설정도 계속 검증한다. 초기 edge만 생성하는 모드와 서비스 간 통신 회귀도 통과했다.
- PowerShell 구문·CIDR 검사 및 잘못된 public_http_cidrs 거부 검사 통과.
- routing-doc-sync 실행: mismatch 0, structural_status=needs_review, role_status=not_verified. 이번 Terraform·PowerShell 변경은 Python AST 검사 범위 밖이므로 해당 문서와 소스를 직접 대조했다. 보고서의 Python 구조 변경은 없으며 기존 Python 파일의 바이트 차이는 이 작업에서 수정하지 않았다.
- AWS Apply·원격 Nginx 설정은 실행하지 않았다. 새 Plan과 검토가 필요하며 테스트 Front는 Inventory 갱신 후 Front 설정을 다시 적용해야 HTTP 허용 CIDR이 반영된다.


## 과거 기록: 2026-10-15 Front 80·443 모두 제한한 초기 로컬 검증

아래는 정책 확정 전의 실행 이력이다. 현재 정책은 HTTP 80 전체 IPv4 허용·HTTPS 443 지정 IP 허용이며 웹 규칙은 16개다. 아래 28개 규칙 검사 결과를 현재 정책의 검증 결과로 해석하지 않는다.

- 변경: 기본 및 current traffic의 public_http_cidrs를 222.112.208.66/32~222.112.208.72/32로 설정하고 workload/front_https_ingress가 해당 목록을 사용하도록 수정했다.
- 두 JSON 파싱과 7개 IP의 정확한 일치 검사를 통과했다. current의 기존 관리자 CIDR 등 나머지 설정은 유지했다. current는 Git 제외 로컬 프로필이므로 저장소의 테스트는 기본 파일을 사용하고 current 목록은 별도로 대조했다.
- terraform fmt -check: 변경한 main.tf 및 세 테스트 파일 통과.
- terraform validate: Success! The configuration is valid.
- terraform test: edge.tftest.hcl, school-access.tftest.hcl, workload.tftest.hcl의 15개 run 통과, 실패 0개. Windows에서는 -filter 인수에 tests\파일명.tftest.hcl을 사용했다.
- 검증 내용: Front 2개 × TCP 80·443 × 지정 IP 7개의 규칙 28개, 각 역할·포트의 정확한 CIDR 집합, 기존 Front 전체 송신·Backend 통신·SSH 정책, 빈 목록의 웹 수신 차단, 기존 ALB 선택 동작.
- AWS provider는 mock_provider로, foundation·connectivity 원격 상태는 override_data로 대체했다. 테스트의 command=apply는 모의 자원 평가이며 실제 AWS Apply가 아니다.
- 초기 validate에서 테스트용 로컬 compute 모듈 등록 누락을 발견했다. init -backend=false가 로컬 모듈을 등록한 뒤 registry 접근 제한으로 종료됐으나, 기존 설치 provider로 후속 validate와 모의 테스트는 성공했다. 원격 백엔드 초기화는 하지 않았다.
- 사용자 요청에 따라 실제 AWS Plan·Apply·조회·SSH·HTTP 요청은 하지 않았다. 운영 중인 AWS 자원의 변경 결과·드리프트·권한·할당량은 검증 범위 밖이며 로컬 성공이 실제 적용 성공을 보증하지 않는다.
- 80번 출처 제한은 Certbot HTTP-01 발급·갱신에 영향을 준다. 인증 방식 변경은 이번 범위에 포함하지 않았다. 실제 적용 시 새 Plan에서 기존 Front 전체 공개 수신 규칙 4개 제거와 IP별 규칙 28개 생성을 확인해야 한다.


## 2026-10-15 Kafka·MySQL의 Backend 8000 연결 제거 검증

기본·current에서 kafka_game/kafka_ad/mysql_game/mysql_ad를 제거했다. Backend 8000은 해당 Front와 상대 Backend만 허용한다. 광고→MongoDB 27017, 게임·광고→Kafka 9092·MySQL 3306, 기존 Front 7개 공인 IP 제한을 유지했다. OS 방화벽의 Kafka·MySQL API 출처도 제거했다.

- Terraform fmt -check 및 validate 통과.
- mock AWS provider와 원격 상태 override를 사용한 edge/application-flows/school-access/workload 테스트: 20 passed, 0 failed. Backend 수신 집합, Account 3~5의 8000 송신 부재, 서비스별 포트와 SG 대상, 기존 SSH·Front 정책을 검사했다.
- 로컬 WSL Python으로 두 JSON 파싱·삭제 대상 부재·유지할 포트와 7개 IP 일치, 방화벽 YAML 로딩·게임/광고 Jinja 렌더링을 통과했다. 각 Backend API 출처는 해당 Front·상대 Backend 두 종류이고 Kafka·MySQL IP는 포함하지 않는다. established,related 응답 규칙과 DB·Kafka·MongoDB 수신 허용을 확인했다.
- 검증 스크립트: aws-infra/infra/.local/verify-backend-ports.py (로컬 진단 파일).
- AWS 조회·실제 Plan/Apply·SSH·원격 Ansible·네트워크 접속 테스트는 하지 않았다. OS의 nft 명령을 통한 규칙 로딩 검사는 하지 않았다. 운영 자원은 변경하지 않았다.


## 2026-10-15 실행기 중복 처리 공통화

기능·명령어·대상·검사 시점을 유지하며 PowerShell 실행기 7개 파일을 정리했다. 환경 변수 보관·해제·복원 3곳은 Save-InfraEnvironment / Restore-InfraEnvironment, CLI stdout·stderr·종료 코드 수집 4곳은 Invoke-InfraCapturedCommand, 저장 계획 읽기 3곳은 Read-InfraTerraformPlan으로 모았다. 각 호출부의 환경 변수 목록·CLI 인수·제한 시간·DryRun/AbsentErrors 판정·오류 메시지는 유지한다. Plan 직후와 Apply 직전의 재검사는 캐시하거나 생략하지 않는다. 기존 작업 파일을 기준으로 수정했으며 이전부터 있던 Terraform·보안·플랫폼 변경은 이번 리팩토링 결과에 포함하지 않는다.

- 변경 전 test_runner.py 8개 통과. 변경 후에도 8개 통과.
- Windows PowerShell 5.1: test_destroy_all.py 17개, test_destroy_once.py 12개, test_power_all.py 13개, test_destroy_console_ssh.ps1 28개 검사 통과. 모두 모의 실행이며 실제 AWS 호출 없음.
- 신규 test_common.ps1: 예외 후 환경 복원, 네이티브 stdout·stderr·종료 코드·빈 출력, 저장 계획 재읽기·호출부 오류 메시지 검사를 PowerShell 5.1과 7에서 통과.
- 변경 직전 스크립트 사본과 현재 CLI 래퍼 4개를 PowerShell AST로 추출하여 성공·일반 오류·DryRunOperation·NoSuchKey 응답의 명령 인수와 반환값/오류 메시지를 비교했다. 두 셸에서 모두 일치했다. 전체 AWS 동작의 동등성을 증명하는 검사는 아니다.
- 최초 삭제 테스트 실행에서는 run.json의 File.Replace가 실패했다. 파일 교체 코드는 변경하지 않았으며, 두 삭제 테스트를 각각 단독 재실행했을 때 모두 통과했다. 최초 오류의 외부 원인은 확정하지 않았다.
- 변경/신규 PowerShell 8개 파일 구문 검사, 공통 함수 13개 선언과 라우팅 문서 표 대조, 관련 문서 11개의 로컬 링크 118개 존재 확인 통과.
- routing-doc-sync는 관련 라우팅 문서 10개를 지정해 재실행했다. 인식한 Python 참조 5개 중 불일치 0건, diagnostics 0건이며 결과는 needs_review / role_status=not_verified다. 이 스킬은 PowerShell 자동 분석을 지원하지 않으므로 PowerShell 선언과 호출부는 별도 구문 분석·코드 대조로 확인했다. 보고서는 infra/.local/refactor-routing-after.json에 저장했다.

실제 AWS 배포·삭제·전원 변경·SSH 키 등록 및 원격 Ansible은 실행하지 않았다. 실행 코드 fingerprint가 바뀌므로 기존 저장 계획은 재사용하지 않고 새 Plan을 생성해야 한다.


## 2026-10-15 Bastion Elastic IP 구성

Bastion 모듈에 aws_eip.this(domain=vpc)와 aws_eip_association.this를 추가하고 기존 aws_instance.this에 연결했다. 기존 EC2 생성 인수는 유지했다. instance.public_ip는 EIP를 반환하며 모듈 출력은 연결 완료에 의존한다. stack의 SSH 안내는 해당 출력, 내부 proxy_endpoint는 기존 사설 IP를 사용한다. Bastion 상태가 EIP를 소유하므로 Stop/Start에는 유지하고 Bastion Delete/전체 삭제에는 반환한다.

Assert-InfraBastionPlan과 Assert-InfraDeletePlan의 정확한 허용 주소에 EIP·연결 자원을 추가했다. 기존 EIP의 Project/Account/Stage 태그도 검사하고 생성 모드의 삭제·교체·import 거부는 유지했다. 전체 삭제의 기존 describe-addresses 검사로 EIP 할당 ID 잔존을 확인한다.

- Terraform fmt -check 및 bastion stack validate 통과. 로컬 AWS provider 6.68.0을 사용하고 init은 별도 TF_DATA_DIR에서 backend=false로 실행했다.
- Terraform 모의 테스트: Bastion 모듈 1개와 stack 1개 통과. AWS provider와 S3 원격 상태를 모의 처리했다. 모듈 검사는 .local/bastion-eip/module 사본에서 실행했다.
- test_bastion_eip.ps1: PowerShell 5.1·7 모두 통과. 생성·삭제 허용, 교체·다른 계정·유사 자원명 거부와 남은 EIP 탐지 확인.
- 기존 실행기 test_runner.py 8개와 콘솔 SSH 삭제 경계 28개 검사 통과. 전체 삭제/전원 테스트 전체를 이번에 재실행한 것은 아니다.
- 관련 문서 12개의 로컬 링크 247개 존재 확인, 변경 PowerShell 구문과 git diff --check 통과.
- routing-doc-sync를 관련 라우팅 문서 7개에 실행했다. diagnostics 0건·인식한 Python 참조 불일치 0건이며 needs_review / not_verified다. Terraform·PowerShell은 스킬 자동 분석 밖이므로 위 검사와 코드 대조를 근거로 삼는다. 보고서: infra/.local/bastion-eip/routing.json.

실제 AWS Plan·Apply·EIP 할당·연결은 실행하지 않았다. 기존 배포와 같은 구성 경로로 새 Bastion Plan을 만들고 EC2 교체나 다른 변경이 없는지 확인한 뒤 Apply해야 한다. 실제 서버가 EIP로 전환됐다는 기록이 아니다. 최초 연결 후 SSH 주소와 인벤토리를 갱신한다.

## 2026-10-15 Front HTTP 공개·HTTPS 제한 정책 확정

사용자가 HTTP 80 전체 IPv4 허용(인증서 검증용), HTTPS 443의 222.112.208.66~72 7개 /32 제한을 확정했다. 현재 workload 선언과 제공된 Account 1 Plan을 대조해 관련 안내·구성도·운영 문서를 수정했다. 웹 수신 규칙은 HTTP 2개 + HTTPS 14개 = 16개다. 허용 목록이 비어도 HTTP 2개는 유지하며 HTTPS 규칙만 생성하지 않는다.

사용자가 제공한 Plan은 16 add / 0 change / 16 destroy이며, 변경 대상은 모두 Account 1 SG 인바운드 규칙이다. 삭제는 기존 Front 규칙 4개, Kafka·MySQL→Backend 8000 규칙 10개, 집 IP SSH 규칙 2개다. EC2·EBS·EIP 변경은 출력에 없다. 이 기록은 제공된 Plan 검토이며 Apply 성공 기록이 아니다. 이번 문서 수정에서는 AWS 명령·배포·테스트를 실행하지 않았다. 이전 28개 웹 규칙 모의 테스트 기록은 정책 변경 전 이력으로 보존했다.

## 2026-10-18 게임 도메인 코드와 문서 동기화

게임 Front 도메인·IP 이동용 인증서·로컬 앱·WebSocket 경로를 코드에 반영했다. 템플릿 6개 검사, PowerShell 실제 Front 분기의 게임/광고/선택 Backend/잘못된 도메인 검사, edge.yml 문법 검사가 통과했다. 원격 재배포·nginx -t·인증서 재발급은 하지 않았다. 운영 상태는 별도 AWS 읽기 조회로 EC2 19대 stopped, 연결 EBS 4,280GiB, 기존 18대의 평일 08:30 시작·매일 22:00 중지 예약을 확인했다. 과거 검증 결과는 원래 날짜 기준으로 보존한다.
