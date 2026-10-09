# Platform 라우팅 문서 검증 기록

[탐색 시작점](ROUTING-README.md) · [실행 안내](../../README.md) · [작업 규칙](../../AGENTS.md)

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
    '--output', (Join-Path ([System.IO.Path]::GetTempPath()) 'platform-routing-check.json')
)
Get-ChildItem -LiteralPath 'C:/third_project/platform/docs/platform-routing' -Recurse -Filter '*.md' |
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
| setup-proxy.sh | [파일별 문서](setup-proxy.sh.md)에 옵션·오류 처리, 실행 경로 고정, 대상 확인, 6단계 명령·limit·태그와 원본 행을 추가했다. |
| bootstrap-proxy.yml | [파일별 문서](bootstrap-proxy.yml.md)에 필수 입력, 최초 설치 생략 조건, 13개 작업 위치, 설정 적용 블록의 rescue 범위와 서비스 상태 선택을 반영했다. |

[통합 탐색 지도](ROUTING-README.md)에 별도 프록시 준비 흐름을 연결하고 site.yml의 서비스 설치 흐름과 구분했다. Squid의 deny all 검사는 주설정 파일의 해당 행 개수만 확인하며, 전체 접근 규칙 순서까지 검증하는 것으로 설명하지 않는다.

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
