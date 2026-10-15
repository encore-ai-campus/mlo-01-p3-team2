# Platform 라우팅 문서 검증 기록

[탐색 시작점](../ROUTING-README.md) · [실행 안내](../../README.md) · 로컬 작업 규칙: AGENTS.md(Git 제외)

## 2026-10-15 수정 코드와 라우팅 문서 재대조

Git HEAD ba6f151a494f604d2d3dc70d443b52a0a2a19cfd → WORKTREE와 미추적 소스를 기준으로 기존 문서 변경을 유지하며 대조했다. MongoDB에 추가된 데이터 디렉터리 소유권 작업을 [작업 지도](roles/mongodb/tasks/main.yml.md)·[역할 안내](roles/mongodb/README.md)·탐색 시작점에 반영했다. 작업 지도 17개의 이름·행 번호를 원본과 맞췄으며 포맷·마운트·재귀 소유권 변경을 하지 않는 경계도 명시했다.

[방화벽 템플릿](roles/firewall/templates/infra-fw.nft.j2.md)의 누락된 Front·peer·edge 출력식과 Backend 8000의 신규 연결 허용 의미를 보완했다. 이전 edge와 현재 Front의 분기, Nginx의 조건부 308/404 응답을 구분하고 [역할 지도](roles/README.md)의 edge 적용 대상에 두 Front 그룹을 반영했다. 기본 인벤토리·프록시 Vault 전달·MySQL 조회 playbook·모니터링 줄바꿈 변경은 기존 대응 설명을 유지했다.

Python 구조는 routing-doc-sync 번들 AST 분석기로 조사했다. 두 프로젝트의 라우팅 문서 177개에 있는 인식 가능한 Python 참조 39개를 검사했으며 확정 불일치와 분석 진단은 0개다. 상태 needs_review와 role_status=not_verified는 유지한다. 파일·시그니처 일치가 역할 의미나 비Python 코드의 실행 성공을 증명하지는 않는다. 보고서와 정적 검사 결과는 infra/.local/routing-doc-sync-20261015/에 로컬 보관한다.

라우팅 문서의 상대 링크·제목 및 HTML 앵커, MongoDB 작업 표, 비Markdown 파일의 변경 전후 해시를 확인했다. 이번에는 문서만 변경했으며 AWS API·배포·원격 접속·Ansible 실행·Terraform 테스트는 수행하지 않았다. 아래 날짜별 실행 결과는 당시 이력으로 보존한다.

## 2026-10-14 수정 코드 라우팅 동기화

Git HEAD → WORKTREE와 미추적 check-mysql.yml을 기준으로 대조했다. [MySQL 조회 안내](check-mysql.yml.md)를 추가하고 탐색 시작점·MySQL 역할·검증 지도에서 연결했다. Vault root 비밀번호의 환경 변수 전달, no_log, SQL 반환 코드 검사와 멤버 상태 조회를 설명한다. --check에서도 실제 읽기 전용 조회가 실행되며 이 playbook 자체는 멤버 수·모든 노드 ONLINE·Primary 수를 단언하지 않는 점을 구분했다.

기존 수정인 [기본 인벤토리](ansible.cfg.md), [Vault 옵션을 전달하는 프록시 실행기](scripts/setup-proxy.sh.md), [Backend 8000 방화벽](roles/firewall/templates/infra-fw.nft.j2.md)도 소스와 대응 문서를 대조했다. 모니터링 셸 3개는 Git 차이에 로직 변경이 없고 작업 파일 LF·eol=lf 속성을 확인해 [역할 안내](roles/monitoring/README.md#구현-조건)에 연결했다.

routing-doc-sync의 Python 분석 결과에서 Spark 연동 파일은 바이트 차이가 있으나 구조 변경은 없다. 새 Python 함수 7개는 인프라 전원 테스트에 속하며 [인프라 검증 기록](../../../../aws-infra/docs/infra-routing/verification.md#2026-10-14-수정-코드와-라우팅-문서-동기화)에 분석 결과·한계를 남겼다. Ansible 파일명을 Python 심볼로 오인한 참조는 원본 링크로 정리했다.

이번에는 라우팅 문서만 변경하고 로컬 참조·코드 해시를 검사했다. 원격 인증·클러스터 정상 여부, Ansible 실행과 기존 회귀 테스트를 새로 통과했다고 기록하지 않는다. 아래 날짜별 실행 기록은 보존한다.

## 2026-10-13 기본 인벤토리와 모니터링 셸 줄바꿈 수정

[ansible.cfg](../../ansible.cfg)의 기본 인벤토리를 inventory/hosts.current.yml로 변경했다. 로컬 파일에는 mysql-1·mysql-2·mysql-3와 game_frontend의 front-a, ad_frontend의 front-b가 등록되어 있다. 다른 프로필·팀 접속용·수동 인벤토리는 `-i`로 선택하며, 새 체크아웃에 생성 파일이 없으면 먼저 Inventory를 실행한다. README·설정·인벤토리·MySQL 역할 안내도 이 기준으로 맞췄다.

모니터링의 archive.sh·collector.sh·resource.sh를 LF로 정규화하고 루트 `.gitattributes`에 `roles/monitoring/files/*.sh`의 LF 유지 규칙을 추가했다. Windows 체크아웃의 CRLF가 서버에 그대로 복사되어 발생하던 Bash 오류를 방지한다. 셸 로직과 수집·보관 정책은 변경하지 않았다.

WSL의 기존 Ansible 14.4.0 환경에서 `ANSIBLE_CONFIG`를 지정하고 다음을 확인했다.

- `-i` 없는 대상 목록 조회에서 MySQL 3대와 HTTPS 대상 Front 2대를 선택한다.
- [site.yml](../../site.yml), [edge.yml](../../edge.yml), [prepare-proxy.yml](../../prepare-proxy.yml), [bootstrap-proxy.yml](../../bootstrap-proxy.yml)의 `--syntax-check`가 모두 통과한다.
- 모니터링 셸 3개와 scripts의 셸 3개가 `bash -n`을 통과한다. resource.sh는 로컬 읽기 전용 실행으로 리소스 한 줄 출력도 확인했다.
- `git ls-files --eol`에서 모니터링 셸 3개의 작업 파일이 LF이며 `text eol=lf` 규칙을 적용받는다.

인벤토리 등록·로컬 문법 검사 결과이며 실제 EC2 접속·설치·인증서 발급·DB 복제는 이번 수정에서 검증하지 않았다. 아래 2026-10-10의 인벤토리 불일치와 Inventory 실패 내용은 당시 이력이며 현재 로컬 파일의 상태를 설명하지 않는다.

## 2026-10-10 MySQL 프로필과 로컬 인벤토리 불일치

기본 및 `profiles/current` 토폴로지에는 mysql-1(account3), mysql-2(account5), mysql-3(account4)가 정의되어 서비스 EC2는 총 17대다. 선택 Bastion은 별도다. 이는 EC2 프로필 설정 수이며 MySQL 설치·Cluster 가입 완료를 뜻하지 않는다. [인프라 구성 문서](../../../../aws-infra/docs/infra-routing/config/README.md#mysql-3-증설)와 [플랫폼 실행 안내](../../README.md)를 따른다.

인프라의 적용 기록은 기존 서비스 EC2 16대에 account4의 mysql-3를 추가해 17대로 확장한 것으로 설명한다. 따라서 기록상 mysql-3는 최초 16대 일괄 생성에 포함된 노드가 아니라 후속 증설분이다. 이는 저장된 적용 기록에 근거하며 실제 EC2의 생성 시각을 새로 조회한 결과는 아니다.

로컬 `inventory/hosts.current.yml`은 갱신 전 파일로 mysql-1·mysql-2만 포함하고 mysql-3는 빠져 있다. 읽기 전용 `deploy.ps1 -Action Inventory` 갱신은 Terraform 상태 출력 조회 후 AWS 인스턴스 상태 검사에서 `kafka-1`이 실행 중이 아니라는 이유로 중단됐다. 따라서 이번 실행은 인벤토리를 갱신하지 않았다. 전체 Inventory 단계가 성공하고 생성된 파일의 mysql 그룹에 세 노드가 포함된 것을 확인하기 전에는 MySQL Cluster Ansible 작업을 실행하지 않는다. 상세 실행·조건은 [배포 절차](../../../../aws-infra/docs/deployment-runbook.md#6-현재-ec2-주소로-인벤토리-생성)를 참조한다.

이번 확인은 프로필·기존 인벤토리·Inventory 실패 출력을 대조한 정적 문서 갱신이다. EC2를 생성·수정·삭제하거나 Apply 및 Ansible을 실행하지 않았고, MySQL 설치·Cluster 구성·자동 Primary 선출·Router 연결도 확인하지 않았다. 아래의 이전 라우팅 동기화 기록은 mysql-3 프로필 반영 전 상태를 기록한 이력으로 보존한다.

`routing-doc-sync`로 HEAD → WORKTREE의 Platform 라우팅 Markdown 139개를 재검사했다. Python 문서 참조 7개 중 file_match 4개와 symbol_match 2개, ambiguous 1개이며 확정 mismatch와 diagnostics는 0개다. 분석기 결과는 needs_review(exit 3), role_status=not_verified로, 모호한 참조 검토와 역할 의미·비Python 파일 동작 검증은 별도 범위다.

## 2026-10-10 README와 관련 안내의 라우팅 기준 동기화

현재 양쪽 라우팅 문서를 근거로 [플랫폼 README](../../README.md)와 [인프라 README](../../../../aws-infra/README.md), 배포·보안·설계·검증 안내를 갱신했다. 현재 서비스 서버는 Consumer를 포함해 16대와 선택 Bastion 1대다. 인프라의 MySQL 두 대는 플랫폼 Cluster의 전체 그룹 3~9대 조건을 충족하지 않으므로 세 번째 서버·통신·인벤토리를 먼저 준비해야 한다.

MySQL 설치 후 game·Spark·선택 backend에 로컬 Router를 구성하는 명령, 앱의 127.0.0.1:6446(RW)·6447(RO), Spark JDBC 실행 노드별 Router 조건을 반영했다. 과거 ReplicaSet·Standalone·Router 패키지 시험은 현재 Cluster·Router bootstrap과 실제 장애 전환의 검증 결과로 사용하지 않는다. NAT 0개와 Squid·APT·다운로드 준비, 서비스 설치·앱 배포의 구분도 관련 안내에 맞췄다.

작업 중 추가된 [팀 접속 스크립트 문서](scripts/setup-team-access.sh.md)를 시작 지도와 README에 연결했다. 준비된 Endpoint·IAM·SG·서버 키·현재 사용자 인증을 요구하며 프로젝트 SSH 설정과 별도 접속용 인벤토리를 만드는 범위다. 이번 문서 작업에서 스크립트를 작성하거나 실제 Endpoint·EC2 접속을 실행하지 않았다.

양쪽 Markdown 183개의 상대 링크·제목 앵커 검사에서 누락 0개, routing-doc-sync의 Python 문서 참조 28개에서 mismatch=0·diagnostics=0을 확인했다. 스킬 판정 needs_review·role_status=not_verified는 유지하며 비Python 실행과 역할 의미는 검사 범위 밖이다. 문서 변경분의 공백 검사도 통과했다. 이번 검사는 문서 연결·정적 참조 확인이며 원격 설치·복제·장애 전환 시험은 수행하지 않았다.

기존 문서 이동·코드·설정·스테이징을 보존했고 이번 수정은 양쪽 Markdown 30개다. 작업 중 비Markdown 파일과 index의 변화도 관찰했으나 소스 수정·스테이징·커밋 명령을 실행하거나 기존 변경을 되돌리지 않았다. 자세한 기준·범위와 보고서 위치는 [인프라의 동일 작업 기록](../../../../aws-infra/docs/infra-routing/verification.md#2026-10-10-readme와-관련-안내의-라우팅-기준-동기화)에 있다. 아래 이력은 당시의 결과로 유지한다.

## 2026-10-10 하위 폴더 지도와 이동 경로 검증

현재 시작점은 docs/ROUTING-README.md, 파일별 설명은 docs/platform-routing/이다. 작업 시작 전에 진행된 문서 이동을 유지하고 원본 파일 링크·역할별 탐색 시작점·인프라 문서 연결을 새 위치로 맞췄다. scripts/README.md를 추가해 컨트롤 노드의 프록시 준비와 배스천 패키지 설치를 구분했다. README와 AGENTS의 문서 시작 경로도 갱신했다.

HEAD 3274dee0ac642345c3e8b4094a2a372b1a45b4d4 → WORKTREE 기준으로 routing-doc-sync를 실행했다. 최종 전체 라우팅 문서 151개 모두 도달 가능하며 플랫폼 코드·설정 110개는 파일별 대응 문서가 있다. 양쪽 라우팅·관련 안내의 로컬 링크 1,212개와 제목 앵커 50개에서 누락·깨진 연결은 없다. Python 참조는 file_match 7개와 signature_match 15개, mismatch·diagnostics는 0개다. tests/spark_integration.py는 parse_status=ok이고 선언 심볼은 0개다.

전체 스킬 판정은 needs_review, 역할 의미는 not_verified다. PowerShell·Terraform·Ansible·Bash·Jinja 동작과 외부 버전의 최신성은 Python AST로 검증되지 않는다. 이번에는 문서 경로·파일 대응·Python 구조만 정적으로 확인했으며 원격 서버에 적용하지 않았다. 아래 기록은 각 당시의 검사 범위·결과로 보존한다.

작업 중 인프라 compute/main.tf의 보호 값 변경이 관찰돼 관련 문서를 현재 값에 맞췄다. 이번 작업에서 실행 코드·설정을 수정한 것은 아니다. 기존 문서 이동과 설계 변경을 보존하고 Git index를 변경하지 않았다. 자세한 비교 기준·검사 자료는 [인프라 검증 기록](../../../../aws-infra/docs/infra-routing/verification.md)에 있다.

## 2026-10-10 양쪽 프로젝트 변경 코드 재대조

사용자 요청에 따라 platform과 aws-infra의 라우팅 문서 148개를 함께 조사했다. 비교 기준은 HEAD e7c0f7533bfe68649035db3a15395d80b3d2e489 → WORKTREE, 브랜치는 infra;#5다. 아래 2026-10-09 생성 기록과 기존 동기화 기록은 당시의 범위·수치·실행 여부를 보존한다.

Spark의 기본 변수·Worker unit·데몬 환경·작업 설정·검증 파일 문서는 이미 최신 선언과 맞았다. 이번에는 통합 지도·Spark 역할·검증 안내에 AWS traffic과 포트 범위 테스트의 연결을 추가하고, site.yml의 zookeeper와 spark 태그를 구분했다. ZooKeeper만 실행한 경우 Spark unit을 배포하지 않는다는 현재 실행 경로와 서비스 active 이후 Master·Worker 등록 및 PySpark 제출 검사가 이어진다는 의미를 보완했다. 수정한 platform 라우팅 문서는 이 기록을 포함해 6개다.

Worker RPC는 7100, Master UI는 8080, 작업의 Driver는 7078–7094, BlockManager는 7079–7095다. 작업의 spark.port.maxRetries=16과 Master·Worker 데몬의 0을 구분한다. AWS 쪽 model → workload 범위 병합 → security-rules와 해당 테스트 세 파일을 연결했다. 기본 traffic과 NewProfile로 이미 만든 복사본은 별개이므로 포트 변경 시 선택한 구성도 대조한다.

| 검사 | 이번 결과 | 한계 |
| --- | --- | --- |
| routing-doc-sync 재검사 | 양쪽 전체 Python 참조 22개, mismatch 0, diagnostics 0 | needs_review, role_status=not_verified. Python 역할 의미·비Python 형식은 자동 검증하지 않음 |
| Python 코드 | platform의 변경 Python 심볼 0개. spark_integration.py는 structural_changed=false | Python 파일 문서는 기존 AST 참조가 맞아 다시 작성하지 않음 |
| 로컬 Markdown 연결 | 문서 148개, 파일 링크·제목 앵커 1,054개, 오류 0 | 외부 주소와 배포처 버전·해시는 조회하지 않음 |
| 파일별 정적 대조 | YAML·CFG·systemd 선언 위치 535개, Jinja 출력식 목록 25개 문서, 차이 0 | Bash 단계는 코드와 수동 대조. Ansible 실행·템플릿 렌더링·원격 서비스 성공을 증명하지 않음 |
| 범위 보존 | platform의 코드·설정과 기존 index 유지 | 라우팅 Markdown만 보완하고 README의 과거 서버 실험 결과는 갱신하지 않음 |
| 공백 검사 | git diff --check와 git diff --cached --check 통과 | 줄바꿈 변환 경고는 오류로 기록하지 않으며 관련 설정은 변경하지 않음 |

보고서는 aws-infra/infra/.local/routing-doc-sync/20261010-a49b2e0d/에 보관한다. AWS·Terraform 적용, SSH·Ansible 실행, 실제 Spark 설치·클러스터 검증은 수행하지 않았다. 사용자에게서 앞서 받은 ZooKeeper 성공을 새 Spark 설치 성공으로 기록하지 않는다. aws-infra compute 파일은 조사 중 시작 해시와 차이가 있었으나 이번 작업에서 해당 소스를 수정하지 않았고 현재 값에 맞춰 안내만 보완했다. 기존 변경이 섞여 있으므로 새로 스테이징하거나 커밋하지 않고 기존 index를 보존한다.

## 대상과 비교 기준

- 확인일: 2026-10-09, Asia/Seoul.
- Git 최상위: C:/third_project. 분석기의 --repo는 이 경로를 사용한다.
- 문서 대상: platform 하위의 Git 추적 및 무시되지 않은 파일 중 코드·설정 106개.
- 비교 기준: HEAD e7c0f7533bfe68649035db3a15395d80b3d2e489 → WORKTREE. 작업 시작 브랜치: infra;#5.
- 소스 상대경로를 그대로 유지하고 .md를 덧붙여 platform/docs/platform-routing에 배치했다.
- 기존 docs/platform의 설계·계획, AGENTS.md와 README.md는 코드별 문서 대응 대상에서 제외했다. 운영자별 hosts.yml·vault.yml·.vault*도 제외했다.

작업 시작 시 aws-infra의 코드·문서 및 platform/AGENTS.md에 기존 변경이 있었다. 기존 변경은 수정하거나 되돌리지 않았다. 이번 변경은 platform 라우팅 문서와 platform/README.md의 탐색 링크에 한정한다.

## 검사 방법과 깊이

| 대상 | 근거 | 검사 범위 | 한계 |
| --- | --- | --- | --- |
| tests/spark_integration.py | routing-doc-sync의 inventory, changes, documents.checks, diagnostics | 파일 존재·Python 구문·선언 목록 | 선언 0개이므로 함수·시그니처 일치 검사 대상이 없음 |
| Spark infra-check.py.j2 | 스킬의 decode_python·SymbolCollector·scope_facts를 재사용한 보조 AST JSON | 템플릿 원문의 정적 파싱·선언·호출·assert | 기본 스킬 inventory 밖이며 Jinja 렌더링·Spark 실행은 검사하지 않음 |
| Ansible YAML·변수·Jinja·셸·CFG | 실제 작업 파일 대조와 작업 이름·변수·명시 참조의 정적 추출 | 경로·역할별 연결·선언값·검증 작업 위치 | YAML 파서·ansible-playbook·셸 실행·배포처 조회는 수행하지 않음 |
| 새 라우팅 문서·platform README | 코드/문서 1:1 대응, 모든 로컬 Markdown 링크, 시작 문서에서 문서 연결 도달, 소스 SHA-256 | 누락·깨진 상대경로·고립 문서·검증 중 소스 변경 | 자유로운 역할 설명의 의미를 기계적으로 증명하지 않음 |

Python 클래스·함수·시그니처를 원본 본문에서 직접 추출하지 않았다. 대상 모듈은 import하거나 실행하지 않았다. 보조 AST 조사는 환경변수 키, import, 호출 표기, assert 조건과 짧은 문자열 상수만 출력했다. 원문 전체를 출력하지 않았다.

## Python 구조 결과

tests/spark_integration.py는 parse_status=ok이며 클래스·함수·메서드가 없다. 최상위 실행 코드의 import와 호출 단서, 환경변수 7개, assert 3개를 대응 문서에 기록했다. HEAD와 작업 파일의 바이트 해시는 다르지만 structural_changed=false이고 platform 내 변경 심볼은 없다. Git 변경 목록에는 이 파일이 표시되지 않았으므로 바이트 차이를 이번 작업의 코드 수정으로 보고하지 않는다.

infra-check.py.j2도 보조 AST에서 파싱 가능하며 선언 0개와 assert 3개를 확인했다. Jinja 출력식이 Python AST에서 파싱 가능하더라도 렌더링 결과의 유효성이나 실행 성공은 보장하지 않는다.

스킬의 role_status=not_verified는 역할 설명의 의미를 자동 검증하지 않는다는 고정 한계다. 구조 결과가 일치하더라도 전체 동작·역할 의미가 검증됐다고 해석하지 않는다.

## 경로 안내의 기존 불일치

platform/README.md의 설계 링크는 실제 docs/platform/infra-automation-design.md를 향하도록 수정하고 새 라우팅 진입 링크를 추가했다.

platform/AGENTS.md에는 적용 디렉터리가 aws-infra라고 쓰인 부분과 docs/infra-routing, 중복 platform 접두사 등 서로 다른 경로 안내가 남아 있다. 이 파일은 사용자의 기존 변경이 있어 수정하지 않았다. 이번 라우팅 문서의 대상과 위치는 사용자 요청의 platform 및 docs/platform-routing을 기준으로 확정했다. 이 기존 안내 불일치는 새 라우팅 문서의 파일 대응·링크 오류와 구분한다.

## 2026-10-09 문서 생성 시 검사 결과

- 코드·설정 파일별 대응: 106 / 106.
- 라우팅 Markdown 수: 122.
- 시작 문서에서 도달 가능한 라우팅 Markdown: 122 / 122.
- 로컬 Markdown 링크 검사: 720.
- 깨진 링크·누락·고립 문서·소스 해시 변경: 0.
- routing-doc-sync 구조 결과: needs_review.
- routing-doc-sync 종료 코드: 3.
- Python 참조 검사: {'file_match': 2}.
- routing-doc-sync 확정 불일치: 0.
- routing-doc-sync diagnostics: 0.
- Python 참조 없는 문서 (자동 심볼 검사 범위 밖): 121.
- 미분류 인라인 코드: 0.
- 역할 의미 자동 검사: not_verified (스킬 범위 밖).

전체 문서 분석의 needs_review(종료 코드 3)는 Python 참조가 없는 문서 121개가 no_supported_references로 남기 때문이다. 해당 파일 형식의 자동 심볼 검사를 수행하지 못한 상태로 유지하며 성공으로 바꾸지 않는다. Python 파일 문서만 지정한 별도 검사에서는 structural_match(종료 코드 0), file_match 2개, diagnostics 0개였다. 함수·시그니처 검사 대상은 없었다. 비Python 파일의 경로·선언·연결은 별도 정적 대조 범위로 보고한다.

## 재검사

PowerShell에서 저장소 루트를 --repo에 지정하고 모든 라우팅 Markdown을 --docs로 전달한다. 아래 명령은 임시 JSON 보고서를 만들며 종료 코드와 diagnostics, documents.checks를 함께 확인한다.

```powershell
# 문서 경로마다 --docs를 전달해 기본 Python 분석기를 재실행한다.
$routingArgs = @(
    'C:/Users/Playdata/.agents/skills/routing-doc-sync/scripts/routing_doc_sync.py',
    '--repo', 'C:/third_project', '--base', 'HEAD', '--target', 'WORKTREE',
    '--docs', 'C:/third_project/aws-platform/platform/docs/ROUTING-README.md',
    '--output', (Join-Path ([System.IO.Path]::GetTempPath()) 'platform-routing-check.json')
)
Get-ChildItem -LiteralPath 'C:/third_project/aws-platform/platform/docs/platform-routing' -Recurse -Filter '*.md' |
    Sort-Object FullName | ForEach-Object { $routingArgs += @('--docs', $_.FullName) }
python @routingArgs
```

기본 스킬은 비Python 링크·파일의 심볼을 검사하지 않는다. 코드·설정 파일을 추가·이동·삭제할 때는 대응 파일 문서와 역할 README를 갱신하고 로컬 Markdown 링크·파일 대응을 별도로 확인한다. infra-check.py.j2는 보조 AST 또는 실제 Jinja 렌더링 검사가 필요하다.

## 이번 작업에서 실행하지 않은 검증

Ansible 설치·syntax-check·playbook 실행, Jinja 렌더링, SSH·방화벽·DB·클러스터·Spark 제출·모니터링 수집을 수행하지 않았다. 원격 서버 검증 결과와 README의 기존 실험 기록을 갱신하지 않았다. 저장소 버전·URL·해시의 외부 최신성, MongoDB 커널 호환성에 관한 외부 주장은 검증하지 않았다.

## 2026-10-10 프록시 연동 변경 상태

아래는 프록시 구현 당시 남긴 상태 기록이다. 이번 변경분 문서 동기화 결과는 다음 절에 별도로 기록한다.

- prepare-proxy.yml과 공통 프록시 변수, site.yml 환경변수 연결, 배스천 방화벽의 VPC CIDR/TCP 3128 규칙을 작성했다.
- AWS DescribeInstances를 읽기 전용으로 호출해 5개 계정의 실행 중 EC2 16대를 확인하고 Git 제외 대상인 로컬 hosts.yml을 작성했다. 실제 IP와 개인 키 값은 문서에 수록하지 않는다.
- 변경 전 routing-doc-sync: diagnostics 0, checked_references 2, mismatches 0. 비Python 문서와 범위 밖 기존 변경 때문에 needs_review를 유지한다.
- 코드 최초 작성 후 git diff --check는 통과했고 hosts.yml의 Git 제외도 확인했다. 이후 문서 갱신과 check 모드 조건 보완에 대한 최종 검사는 아직 수행하지 않았다.
- WSL 임시 가상환경에 ansible 14.4.0/ansible-core 2.21.5 설치가 완료됐으나 후속 WSL 호출에서 가상환경 실행 파일을 찾지 못했다. 따라서 Ansible 문법·환경변수 상속·템플릿 렌더링 검사가 통과했다고 보고하지 않는다.
- 사용자가 직접 검증하기로 요청하여 추가 실행을 중단했다. EC2의 APT·방화벽·서비스는 적용하지 않았다. 최종 문서 검사와 Ansible 검증이 남아 있어 이번 변경을 자동 스테이징하거나 커밋하지 않았다.

사용자 실행 순서는 README의 "배스천 프록시로 설치 준비"를 따른다. 문법 검사와 SSH 확인 → 배스천·account4 준비 → 배스천 방화벽 → account4 proxy_verify 순으로 진행하고 각 단계의 결과를 확인한다.

## 2026-10-10 구성별 실행 스크립트 추가

이 항목은 이후 사용자가 제공한 결과와 새 스크립트의 검사 범위를 구분한다.

- 사용자가 제공한 로그에서 기존 site.yml 문법 검사, bastion-01·spark-3 SSH ping, 두 서버 prepare-proxy의 failed=0/unreachable=0, 배스천 방화벽 적용의 failed=0/unreachable=0을 확인했다. 이어진 proxy_verify 완료는 사용자의 완료 응답 기준이며 상세 로그는 받지 않았다.
- 이번에는 setup-proxy.sh와 bootstrap-proxy.yml, Windows deploy.ps1 연결을 추가했다. 위 기존 명령의 성공을 새 자동 실행 전체의 검증 결과로 간주하지 않는다.
- Windows PowerShell 파서로 deploy.ps1·infra.ps1·infra-common.ps1 세 파일의 문법을 확인했다.
- 임시 구성에서 NewProfile, 기존 구성 덮어쓰기 차단, 선택한 topology 변경 시 fingerprint 변경, 구성별 로컬 Plan 경로 분리를 확인했다.
- 실제 AWS 호출 대신 만든 응답으로 인벤토리 생성을 검사했다. 서비스가 없는 계정, account1으로 옮긴 노드의 키, mongo→mongodb 매핑, 배스천·대상 키 분리, 현재 공인 IP와 CIDR 반영, 중지된 서버 거부를 확인했다.
- 새 파일별 문서 세 개의 로컬 링크 15개, 변경분 git diff --check, Bash 파일의 LF와 Git eol=lf 속성, 구성·생성 인벤토리의 Git 제외를 확인했다.
- Git Bash -n 시도는 종료 코드 1과 빈 진단으로 끝나 문법 통과를 확인하지 못했다. 새 Bash·Ansible 실행 및 Terraform/AWS/SSH 원격 적용은 사용자 검증 대상으로 남긴다.
- routing-doc-sync는 Python 구조 참조를 검사한다. Bash·PowerShell·Ansible은 자동 심볼 검사 대상 밖이므로 needs_review를 실제 실행 성공으로 바꾸지 않는다.

실제 적용 검증이 남아 있어 새 변경을 자동 스테이징하거나 커밋하지 않았다. 기존 스테이징 상태는 유지했다.

## 2026-10-10 변경분 라우팅 문서 동기화

비교 기준은 HEAD e7c0f7533bfe68649035db3a15395d80b3d2e489 → WORKTREE다. 이전에 생성·스테이징된 라우팅 문서 122개를 다시 작성하지 않고, 아래 코드·설정 변경과 직접 연결된 문서 8개만 보완했다. 작업 시작 때 존재하던 README·라우팅 문서 수정 내용도 보존했다.

| 코드·설정 변경 | 문서 반영 |
| --- | --- |
| prepare-proxy.yml 추가 | 준비 작업의 행·순서, 입력 검사, 지원 OS, URI 정규화, check 모드, proxy/proxy_verify 범위 |
| inventory/group_vars/all/proxy.yml 추가 | 기본 포트·VPC CIDR·검사 URL, 프록시 환경 분기와 전체 호스트 ip 의존성 |
| site.yml 수정 | 정적 import와 내부 활성 조건 구분, 모든 play의 원격 environment 선언, 관련 문서 연결 |
| roles/firewall/templates/infra-fw.nft.j2 수정 | 활성 배스천의 CIDR → TCP 프록시 포트 조건과 변수·접속 검사 문서 연결 |

파일별 문서 4개, 통합·인벤토리·방화벽 안내 3개와 이 검증 기록을 갱신했다. 코드·설정, 실제 hosts.yml·Secret, 다른 역할의 문서는 수정하지 않았다. Squid 설치·AWS 보안그룹·환경변수의 실제 런타임 병합은 이 문서 작업의 검증 대상에서 제외했다.

- 이번에 갱신한 관련 문서: 8개.
- 현재 코드·설정 파일별 대응: 108 / 108.
- 시작 문서에서 도달 가능한 라우팅 Markdown: 124 / 124.
- 로컬 Markdown 링크: 관련 문서 78개, 전체 라우팅·README 744개를 검사했다.
- 누락·깨진 링크·고립 문서·잘못된 작업 행·소스 해시 변경·Git 인덱스 변경: 0개.
- routing-doc-sync: needs_review, 종료 코드 3, checked_references=0, mismatches=0, diagnostics=0.
- 관련 문서 8개는 모두 비Python 참조 문서다. no_supported_references=8이며 기본 스킬은 해당 형식의 심볼을 검사하지 않는다.
- platform 내 변경 Python 심볼: 0개. tests/spark_integration.py의 바이트 차이는 structural_changed=false다. 변경되지 않은 Python 파일 문서는 갱신하지 않았다.

needs_review는 비Python 자동 심볼 검사가 지원되지 않는 범위를 유지한 결과다. 해당 파일의 선언·조건·문서 연결은 정적 대조와 경로 검사로 확인했으며 Ansible 실행·Jinja 렌더링·서비스 동작 성공으로 보고하지 않는다.

이번 요청은 문서 동기화이므로 Ansible 문법 검사·check 모드·템플릿 렌더링·원격 실행은 수행하지 않았다. 이전 기록의 Ansible 검증 제한은 그대로 남는다. 변경 문서에는 작업 시작 전부터 미스테이징된 내용이 섞여 있어 이번 동기화에서는 기존 Git 인덱스를 유지하고 새로 스테이징하거나 커밋하지 않는다.

## 2026-10-10 구성별 프록시 준비 문서 동기화

스킬의 비교 기준은 HEAD e7c0f7533bfe68649035db3a15395d80b3d2e489 → WORKTREE다. 같은 HEAD를 사용하므로 이전 프록시 변경도 Git 변경 목록에 남아 있다. 이번 문서 보완은 위 동기화 이후 추가된 실행 파일 두 개와 직접 연결된 범위에 한정했다. 작업 시작 시 이미 있던 파일별 문서와 통합 안내를 보존하며 코드 위치·조건·복구 범위를 추가했다.

| 추가된 코드 | 문서 반영 |
| --- | --- |
| setup-proxy.sh | [파일별 문서](scripts/setup-proxy.sh.md)에 옵션·오류 처리, 실행 경로 고정, 대상 확인, 6단계 명령·limit·태그와 원본 행을 추가했다. |
| bootstrap-proxy.yml | [파일별 문서](bootstrap-proxy.yml.md)에 필수 입력, 최초 설치 생략 조건, 13개 작업 위치, 설정 적용 블록의 rescue 범위와 서비스 상태 선택을 반영했다. |

[통합 탐색 지도](../ROUTING-README.md)에 별도 프록시 준비 흐름을 연결하고 site.yml의 서비스 설치 흐름과 구분했다. Squid의 deny all 검사는 주설정 파일의 해당 행 개수만 확인하며, 전체 접근 규칙 순서까지 검증하는 것으로 설명하지 않는다.

- 이번에 갱신한 문서: 파일별 문서 2개, 통합 지도와 이 검증 기록을 합쳐 4개.
- 코드·설정 파일별 대응: 110 / 110.
- 시작 문서에서 도달 가능한 라우팅 Markdown: 126 / 126.
- 로컬 Markdown 링크: 관련 문서 61개, 전체 라우팅·README 775개를 검사했다.
- 새 작업·단계 표의 원본 행 참조: 30개를 코드 위치와 대조했다.
- 누락·깨진 파일 링크·고립 문서·잘못된 행 참조·소스 해시 변경·Git 인덱스 변경: 0개.
- 작업 시작 시점과 비교한 문서 변경은 위 4개뿐이며 다른 platform 파일의 해시는 유지했다. 변경분 공백 검사도 통과했다.
- routing-doc-sync 변경 전·후: needs_review, 종료 코드 3, checked_references=0, mismatches=0, diagnostics=0.
- 관련 문서 4개는 no_supported_references다. Bash·Ansible은 Python AST 분석기의 자동 심볼 검사 범위 밖이며 역할 의미는 not_verified로 남는다.
- platform의 Python 변경 심볼: 0개. tests/spark_integration.py는 structural_changed=false로 이전 기록과 동일하며 해당 문서는 다시 수정하지 않았다.

코드·설정 파일을 실행하지 않는 정적 문서 대조를 수행했다. Bash·Ansible 문법 검사와 EC2 적용은 이번 요청에서 실행하지 않았으며 앞선 구현 기록의 미검증 상태도 유지했다. 작업 시작 전부터 존재하던 문서 변경과 스테이징 상태를 보존하기 위해 이번에는 추가 스테이징이나 커밋을 하지 않았다.


## 2026-10-10 MySQL InnoDB Cluster 전환

비교 기준은 작업 시작 HEAD 3274dee0ac642345c3e8b4094a2a372b1a45b4d4 → WORKTREE다. 기존 라우팅 문서의 docs/ 이동과 다른 작업의 변경은 유지하고, MySQL·로컬 Router 및 연결된 문서만 갱신했다. 이전 ReplicaSet·Standalone 서버 실험은 과거 검증으로 유지한다.

- MySQL: 전체 mysql 그룹 3~9대, 단일 Primary, MYSQL 통신 스택, 인스턴스 사전 구성, Cluster 생성·신규 clone·기존 멤버 증분 재가입, 실제 Primary의 계정 적용.
- 보호: 기존 ReplicaSet·관리되지 않는 GR·예상 밖 멤버·정족수 상실·ERROR 상태 중단, 신규 후보 업무 데이터의 기본 clone 거부, GTID 초기화 제거, 중지된 기존 데이터 보호, 가입된 Cluster의 설정/설정 포함 변경 시 중단.
- Router: game·Spark·선택 backend의 기존 서버, 기본 127.0.0.1:6446(RW)/6447(RO), 출처 IP별 전용 계정, bootstrap 해시·keyring·systemd·실제 Primary 접속 검사.
- Spark 연동: MYSQL_PORT 기본 6446. JDBC를 실행하는 모든 Spark 노드에 Router가 필요하다.

| 로컬 검사 | 결과와 범위 |
| --- | --- |
| MySQL·Router 템플릿 렌더링 | 가짜 Secret/IP로 렌더링 성공, SQL·설정 조건 확인 |
| AdminAPI 모의 검사 | 실제 렌더링된 JavaScript를 실행한 27개 시나리오 통과 |
| Ansible 인벤토리·재실행 보호 | ansible_connection=local의 실제 assert 검사 11개 통과 |
| site.yml 문법 | 기존 WSL Ansible core 2.21.5 환경에서 hosts.example.yml 대상 --syntax-check 통과 |
| 라우팅 대응 | MySQL·backend 및 새 공유 설정·검증 코드의 소스 28개에 대응 문서 존재 |
| Markdown·원본 행 | 로컬 링크와 변경 작업 표의 현재 원본 행을 대조 |
| routing-doc-sync | 최종 needs_review(종료 코드 3), 확정 mismatch=0·diagnostics=0. Python 자동 검사와 YAML/Jinja/JS 수동 대조를 구분 |

Python AST inventory에서 tests/spark_integration.py와 tests/validate_mysql_cluster.py는 parse_status=ok, symbols=[]다. 두 파일은 함수·클래스 없는 최상위 실행 코드이며 원본을 import해 구조를 조사하지 않았다. Jinja 입력식은 Python 심볼로 오인하지 않도록 Jinja 코드 블록으로 표기했다. 역할 의미는 분석기의 role_status=not_verified로 남으며 템플릿·모의·로컬 Ansible 검사로 별도 확인한 범위만 기록한다. Git 전체 분석에는 다른 작업의 aws-infra Python 변경도 포함되지만 이번 플랫폼 문서의 동기화 대상은 아니다.

문법 검사에서 예시 인벤토리에 없는 mongodb·spark·backend 그룹 경고가 출력되었다. 해당 그룹을 원격 실행하거나 설치한 것은 아니다. 실제 요구 버전 ansible==14.4.0의 설치 여부와 실제 MySQL Shell·Router 바이너리 동작은 이번 로컬 검사로 확인하지 않았다.

현재 생성 인벤토리의 MySQL 2대는 Cluster 준비 조건을 충족하지 않는다. 세 번째 MySQL 서버·AWS 통신 규칙·인벤토리 재생성은 별도 준비가 필요하다. EC2 설정 적용, 실제 복제, Primary 중단·자동 선출·Router 재접속·쓰기·복귀는 실행하지 않았다. 기존 ReplicaSet 데이터 이전·전체 중단 복구·관리 계정 비밀번호 변경·가입 후 설정의 순차 유지보수도 별도 운영 절차다. 이번 작업에서 aws-infra 파일을 수정하지 않았으며 작업 도중 관찰한 다른 작업의 인프라 변경을 보존했다.

기존 문서 이동·수정과 이번 문서 변경이 섞여 있어 변경 전체를 독립적으로 스테이징할 수 없다. AGENTS.md의 구분 가능한 변경만 스테이징하는 규칙에 따라 기존 Git 인덱스를 유지하고 커밋하지 않았다.

재현 실행기는 [validate_mysql_cluster.py](tests/validate_mysql_cluster.py.md), 세부 모의 시나리오는 [mysql_cluster.test.cjs](tests/mysql_cluster.test.cjs.md)에서 찾는다.

## 2026-10-10 Cluster 사전 구성 관리 계정 수정

사용자가 제공한 세 노드의 MySQL Shell 8.4.10 진단 로그에서 checkInstanceConfiguration이 root@localhost의 원격 접속 제한으로 거부되는 것을 확인했다. 진단 playbook은 failed_when=false이므로 PLAY RECAP의 failed=0과 달리 각 명령의 command_rc=1이었다. 이는 설치 또는 사전 검사 성공 결과가 아니다.

configure-instance.js.j2의 사전 구성 접속을 root 로컬 소켓에서 기존 failover 관리 계정·해당 노드 사설 IP·mysql_port로 변경하고 scheme=mysql을 명시했다. 관리 계정 생성용 root 소켓 접속과 기존 IP별 계정 출처 제한은 유지한다. 설정이 이미 정상인 경우 재구성을 생략하며, 부족한 경우 같은 접속 정보로 configureInstance(restart=true)를 호출한다.

- 회귀 재현: 모의 checkInstanceConfiguration에 root 접속 거부를 추가한 뒤 기존 템플릿에서 동일한 오류로 실패하는 것을 확인했다.
- 수정 후 검증: MySQL·Router 템플릿 렌더링과 SQL·설정 조건, AdminAPI 모의 시나리오 27개, localhost Ansible 인벤토리·재실행 보호 검사 11개, site.yml 문법 검사가 통과했다.
- 보강한 모의 검사: 관리 계정·가짜 Vault 비밀번호·classic 프로토콜·사설 IP·포트·socket 미사용, 검사와 재구성 사이의 접속 정보 동일성, restart=true를 확인한다.
- 문서 반영: MySQL 역할 지도, 사전 구성 작업 문서, configure-instance 템플릿 문서, AdminAPI 모의 검사 문서와 이 기록을 갱신했다.
- routing-doc-sync: 관련 역할·작업·템플릿·검사 문서와 Python 실행기 문서를 대조해 지원되는 Python 파일 참조 2개 일치, mismatch=0, diagnostics=0을 확인했다. 결과는 needs_review(종료 코드 3), role_status=not_verified다. Jinja·JavaScript·YAML과 역할 의미는 자동 심볼 검사 범위 밖이므로 입력식·접속 흐름 수동 대조와 위 로컬 실행 결과로 확인한 범위만 기록한다.

기준 HEAD는 3274dee0ac642345c3e8b4094a2a372b1a45b4d4다. 기존 변경과 Git 인덱스를 보존했다. 이번 수정 대상은 작업 시작 때부터 미추적 파일이어서 기존 내용과 이번 수정만 독립적으로 스테이징할 수 없으므로 추가 스테이징·커밋을 하지 않았다.

검증은 WSL의 기존 가상환경에서 python tests/validate_mysql_cluster.py로 수행했다. 예시 인벤토리에 없는 mongodb·spark·backend 그룹 경고가 있었으며 해당 서버를 원격 실행한 것은 아니다. EC2 설정 적용·실제 AdminAPI 재실행·Cluster 생성·복제·자동 장애 전환은 이번 수정 작업에서 실행하지 않았다. 사용자 설치 로그의 실패 원인 수정과 실제 재배포 성공 여부를 구분한다.

## 2026-10-11 애플리케이션 통신 방화벽

roles/firewall/vars/main.yml에 game·ad 수신 역할을 추가하고 MySQL·MongoDB·Kafka의 from 출처를 인프라 SG 관계와 맞췄다. from/self의 기존 SSH 22 제외 방식과 established,related 응답 허용은 유지한다. 포트 범위는 AWS SG의 8000·9092·27017·3306 규칙이 제한한다.

기존 WSL Ansible Python 환경에서 YAML을 읽고 Jinja StrictUndefined로 역할 템플릿 9종을 렌더링했다. 기본/current traffic 일치, 필요한 출처 IP의 수신 허용 67건, 응답 상태 허용과 Spark에 불필요한 kafka 출처가 없는 것을 확인했다. ALB의 동적 IP와 proxy·SSH 경로는 이 67건의 대상이 아니다. nft 명령의 커널 적용 검사나 원격 방화벽 적용을 수행한 결과는 아니다.

인프라의 관련 Terraform 모의 테스트 13건도 통과했다. [인프라 검증 기록](../../../../aws-infra/docs/infra-routing/verification.md#2026-10-11-애플리케이션-통신-규칙)에서 범위를 확인한다. AWS 적용·원격 Ansible·실제 API 및 DB 데이터 송수신은 실행하지 않았다. YAML·Jinja는 routing-doc-sync Python AST 자동 대조 범위 밖이므로 변수 표와 렌더링 결과를 직접 대조했다.

## 2026-10-11 edge HTTPS 실제 구축

[인프라 실제 구축 기록](../../../../aws-infra/docs/infra-routing/verification.md#2026-10-11-edge-https-실제-구축)의 edge-1에서 edge.yml을 실행해 ok=85, changed=29, unreachable=0, failed=0을 확인했다. Ubuntu 24.04 패키지 미러를 HTTPS로 준비한 뒤 common·firewall·edge 순으로 설치했다.

Nginx·Certbot 5.8.0·IP 인증서·갱신 타이머와 reload 훅을 구성했다. 외부 HTTPS 신뢰 검증·IP SAN·HTTP 404·비허용 출처 403과 renew --dry-run이 통과했다. 현재 허용 사용자 CIDR은 211.117.107.63/32이며 서버 주소는 https://54.116.158.93 이다. 인증서 만료는 2026-10-18 04:26:06 UTC다. 미래의 실제 자동 갱신 결과까지 확인한 것은 아니다.

edge_frontend_upstreams는 비어 있으므로 설치 확인 페이지만 제공한다. Front A/B 애플리케이션 배포와 least_conn 실제 분산은 남아 있다. 부트캠프 접속 IP 변경 시 인프라 game_client_cidrs와 인벤토리 edge_https_allowed_cidrs를 함께 갱신한 뒤 firewall·edge 역할을 재실행한다.

로컬 YAML/Jinja, Ubuntu 미러 6종, Nginx HTTP/HTTPS/least_conn 3상태, NFT CIDR 제한, Certbot 발급·갱신 인수와 edge.yml/site.yml 문법 검사를 통과했다. routing-doc-sync의 Python AST 범위 밖인 YAML·Jinja의 의미는 이 검사와 실제 실행으로 확인한 부분만 기록한다.

최종 전체 삭제 회귀 검사 17개가 통과했다. 실제 AWS 삭제는 실행하지 않았다. 관련 변경 문서 31개의 로컬 파일 링크 423개에서 누락 경로가 없었다. 전체 문서를 대상으로 한 routing-doc-sync는 README의 셸 명령과 YAML 이름 등을 Python 경로·심볼로 해석해 9개 mismatch를 출력했다. 실제 Python 실행 파일 경로와 해당 비-Python 문맥을 따로 확인했으며 이 결과를 자동 검증 통과로 표시하지 않는다. Terraform·YAML 의미는 별도 검사 범위다.


## 2026-10-15 Kafka·MySQL의 Backend 8000 연결 제거 검증

기본·current에서 kafka_game/kafka_ad/mysql_game/mysql_ad를 제거했다. Backend 8000은 해당 Front와 상대 Backend만 허용한다. 광고→MongoDB 27017, 게임·광고→Kafka 9092·MySQL 3306, 기존 Front 7개 공인 IP 제한을 유지했다. OS 방화벽의 Kafka·MySQL API 출처도 제거했다.

- Terraform fmt -check 및 validate 통과.
- mock AWS provider와 원격 상태 override를 사용한 edge/application-flows/school-access/workload 테스트: 20 passed, 0 failed. Backend 수신 집합, Account 3~5의 8000 송신 부재, 서비스별 포트와 SG 대상, 기존 SSH·Front 정책을 검사했다.
- 로컬 WSL Python으로 두 JSON 파싱·삭제 대상 부재·유지할 포트와 7개 IP 일치, 방화벽 YAML 로딩·게임/광고 Jinja 렌더링을 통과했다. 각 Backend API 출처는 해당 Front·상대 Backend 두 종류이고 Kafka·MySQL IP는 포함하지 않는다. established,related 응답 규칙과 DB·Kafka·MongoDB 수신 허용을 확인했다.
- 검증 스크립트: aws-infra/infra/.local/verify-backend-ports.py (로컬 진단 파일).
- AWS 조회·실제 Plan/Apply·SSH·원격 Ansible·네트워크 접속 테스트는 하지 않았다. OS의 nft 명령을 통한 규칙 로딩 검사는 하지 않았다. 운영 자원은 변경하지 않았다.

## 2026-10-15 게임·광고 Backend OS 방화벽 실제 적용

사용자 승인 후 기존 EC2를 유지하고 firewall 역할만 game-server(10.10.10.152), ad-server(10.10.10.20)에 순차 적용했다. AWS 조회로 확인한 Bastion 공인 IP 54.117.44.140을 hosts.current.yml의 public_ip/ansible_host에 반영했다. 방화벽에 필요하지 않은 Vault 로딩을 피하도록 접속 변수와 game/ad/game_frontend/ad_frontend/bastion 그룹만 담은 별도 로컬 인벤토리를 사용했다.

- 실행 기록: aws-infra/infra/.local/backend-firewall-20261015/apply.log. 실행 플레이북과 인벤토리 및 적용 전 규칙 백업도 같은 디렉터리에 보관했다.
- Ansible 문법 검사 통과. 실제 실행은 두 서버 모두 ok=32, changed=5, unreachable=0, failed=0이었다.
- 두 서버에서 후보 및 영구 규칙의 nft -c 문법 검사와 실제 nft -f 적용, 연결 초기화 후 새 SSH 재접속을 통과했다. 부팅용 infra-firewall.service enabled, 복구 타이머 비활성도 검증했다. 실제 재부팅 시험은 하지 않았다.
- 게임 Backend의 TCP 8000 허용 출처는 게임 Front 10.10.0.242와 광고 Backend 10.10.10.20이다.
- 광고 Backend의 TCP 8000 허용 출처는 광고 Front 10.10.0.181과 게임 Backend 10.10.10.152이다.
- 두 서버의 SSH 22 출처는 Bastion 10.10.0.152이고, established,related 응답 허용은 유지된다. 실제 테이블에서 Kafka·MySQL 출처의 8000 허용이 제거된 것을 확인했다.
- 서버 삭제·교체·재부팅, 데이터 삭제·초기화, Terraform Apply는 수행하지 않았다. DB·Kafka·MongoDB 실제 데이터 송수신 시험은 이번 검증에 포함하지 않는다.
- Ansible의 Python 자동 탐색 경고와 reset_connection의 when 미지원 경고가 있었다. 적용 대상 두 서버 모두 새 연결 및 후속 검증이 성공했다.


## 2026-10-15 MySQL Router 실행 경로 통합 — 코드·로컬 검증만

사용자는 광고 전용 플레이북 대신 기존 MySQL Router 실행에서 광고·게임·Spark·MySQL을 모두 처리하도록 요청했고, 실제 EC2 설치 없이 코드 통합과 검증만 선택했다. 작업 시작 시 ad-router.yml과 광고 전용 준비 파일은 이미 작업본에 없었다. 전용 플레이북은 다시 만들지 않았다.

site.yml의 mysql_router/backend 태그는 MySQL 전체 그룹의 계정 준비와 game:ad:spark:mysql:backend Router 설치 play를 선택한다. Router 대상 그룹과 전체 MySQL 설치의 dev 계정 출처에도 ad/mysql을 포함했다. 준비 단계는 단일 ONLINE Primary를 확인하고 Router 대상의 없는 dev 계정을 추가하며 기존 dev 계정을 보존한다. Router 메타데이터 계정·해시 처리는 router-accounts.yml에 모아 전체 MySQL 설치와 단독 Router 실행이 재사용한다. MySQL 일부만 선택하거나 준비 play를 제외하면 설치 전에 중단한다.

- 기존 validate_mysql_cluster.py: AdminAPI 모의 시나리오 27개, 템플릿·SQL/config 불변 조건, Ansible 입력·구성 경계, site.yml 문법 검사 통과.
- 신규 validate_router_scope.py: 8개 고유 호스트 집합·현재 Primary 선택, 메타데이터 계정 해시 재사용, Primary 없음/다중 Primary/OFFLINE/부분 MySQL 제한 거부, ad-only 설치 전 중단, 기존 dev 계정 보존과 신규 계정 생성, 태그 실행의 저장소·패키지 작업 포함 확인 통과. 가짜 CLI·임시 인벤토리·로컬 역할 사본을 사용했다. 사본의 해시 파일 소유권만 현재 사용자로 바꿔 sudo 없이 검사했다.
- 원격 SSH·AWS 조회·서비스 재시작·패키지 설치·DB 계정 변경·애플리케이션 설정 변경은 이번 작업에서 실행하지 않았다. 이전 실제 EC2 조회·광고 설치 기록을 이번 통합 코드의 원격 적용 결과로 취급하지 않는다.

배포 준비가 된 운영자는 platform 디렉터리의 기존 WSL 가상환경에서 ansible-playbook -i inventory/hosts.current.yml site.yml --tags mysql_router --ask-vault-pass를 실행한다. 기본 실행은 --limit을 생략한다. 일부 대상만 선택하려면 MySQL 전체 그룹도 포함한다(예: --limit 'mysql:ad'). 실제 장애 전환과 애플리케이션의 재접속 처리는 별도 검증 범위다.

라우팅 후속 확인: routing-doc-sync의 인식된 참조 2건(file_match·signature_match), 불일치 0건·diagnostics 0건. 결과는 needs_review / role_status=not_verified이며 YAML/Jinja 의미까지 자동 검증한 결과가 아니다. 새 Python 실행 함수 선언은 AST JSON으로 대조했고 변경 문서의 로컬 링크 210개에서 누락 경로가 없었다.
