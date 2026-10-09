# 문서 대조 기준과 검증 범위

[탐색 시작점](ROUTING-README.md) · [적용 규칙](../../AGENTS.md)

## 작업 기준

- 확인일: 2026-10-09.
- 프로젝트: C:/third_project/aws-infra.
- 작업 시작 브랜치: dev.
- 작업 시작 HEAD: 6b6793a51e2c56a69f40dcd8a4f0bedfa011f7f3.
- 기준: HEAD → WORKTREE. HEAD만이 아니라 시작 시 이미 존재하던 미커밋 코드·설정도 조사했다.
- 이번 문서 위치: docs/infra-routing. 이번 작업에서는 이 폴더 안의 문서만 작성·수정한다.

작업 시작 시 .gitignore, AGENTS.md, 루트 README, 보안그룹 문서가 수정 상태였고 예전 비용·설치 문서는 삭제 상태였다. docs/costs와 infra는 untracked였다. 기존 staged 변경은 없었다. 따라서 분석기의 added/changed는 이번 문서 작업에서 발생한 변경과 동일하지 않다.

문서 최초 작성 도중 별도 편집으로 AGENTS.md의 경로와 새 시작 파일명이 ROUTING-README.md로 바뀐 것을 확인했다. AGENTS.md를 다시 읽고 새 이름에 맞춰 하위 링크를 조정했다. 이후 사용자의 오타 수정 요청에 따라 AGENTS.md의 프로젝트 루트 기준 경로, 상위 저장소 기준 경로와 탐색 절차의 라우팅 경로를 바로잡았다.

## 사용한 스킬

사용자가 지정한 routing-doc-sync의 SKILL.md와 references/report-contract.md를 읽고 scripts/routing_doc_sync.py를 Python 3.12.10으로 실행했다. 스킬 위치는 다음과 같다.

```text
C:/Users/Playdata/Documents/Codex/2026-10-09/skills-llm-2/outputs/routing-doc-sync
```

이 스킬은 Python 파일의 AST를 분석한다. 이 프로젝트의 PowerShell·Terraform·JSON·Bash를 분석했다고 보고하지 않는다. 해당 파일은 직접 대조하고 새 문서의 상대 링크는 별도로 확인한다.

## 검사 구분

| 범위 | 사용 근거 | 판정의 한계 |
| --- | --- | --- |
| Python 파일·함수·시그니처 | inventory, changes, documents.checks, coverage, diagnostics | 구조 일치만 확인. 역할 의미는 not_verified |
| PowerShell 옵션·함수·처리 순서 | 실제 .ps1 파일 | Python 스킬의 자동 검증 대상 아님 |
| Terraform 모듈·자원·상태 출력 | 실제 .tf 및 .tftest.hcl | 이번 문서 작업에서 validate/test/plan/apply를 실행한 것은 아님 |
| 현재 배치·포트·빈 입력 | 실제 config JSON | AWS에 적용된 값인지 검증하지 않음 |
| 새 문서 상대 링크 | 문서 위치 기준으로 파일·폴더·Markdown 앵커 대조 | 실제 AWS 동작과 무관 |

Python 현황 분석 대상은 infra/tests/test_runner.py 한 파일이다. 그 함수는 run, calls, count_apply 세 개이며 파싱 오류는 없다. 시그니처는 [Python 구조 문서](tests/test_runner.py.md)에 기록했다.

## 최종 확인 결과

| 검사 | 결과 |
| --- | --- |
| 새 문서 | 14개 |
| 상대 링크·Markdown 앵커 | 131개 대조, 누락 0개 |
| 현재 infra의 .tf/.ps1/.sh/.py/.json/.pub 파일 연결 | 36개 모두 새 문서에서 원본으로 연결됨. .local·.terraform 등 생성물 제외 |
| Python 현황 대조, base NONE | structural_match. 파일 참조 1개와 함수 시그니처 3개 일치, mismatch 0개 |
| Python HEAD 변경 대조 | 시그니처 불일치 0개. 기존 untracked 함수 3개의 역할 검토로 needs_review |
| 루트 README·현재 라우팅 시작점·Python 문서 통합 대조 | 14개 참조 중 루트 README의 비Python 표기 9건이 missing_symbol. diagnostics 오류 없음 |
| 기존 파일 해시 비교 | 시작 시 존재한 57개 중 코드·설정 등 56개 동일. 별도 편집된 AGENTS.md 1개만 달라 재확인 |

Python 구조 분석 대상의 SHA-256은 a4c2cb143f4bef47d65334d038ba68bad157d39b4b0b915c278e31d037bfc987이다. 보고서는 시스템 임시 폴더에 저장했으며 아래 명령으로 다시 생성할 수 있다. 문서 링크 검사는 파일 존재와 앵커를 확인한 것이고, 파일별 역할 설명의 의미를 자동 증명한 검사는 아니다.

문서 최초 작성 시 아래의 기존 문서 차이와 AGENTS.md 경로 표기 문제로 자동 스테이징·커밋을 진행하지 않았다. 후속 오타 수정에서 AGENTS.md 경로 문제는 해결했으며, 나머지 기존 문서 차이는 별도 항목으로 남아 있다. 새 문서 작성과 해당 문서의 링크·Python 선언 대조는 완료했다.

## 기존 문서에서 확인한 차이

| 위치 | 확인한 내용 | 이번 작업의 처리 |
| --- | --- | --- |
| 작업 시작 시 AGENTS.md의 루트 ROUTING-README.md | 파일이 없어 초기 스킬 실행에 read_error 발생 | 이후 변경된 안내에 맞춰 docs/infra-routing/ROUTING-README.md를 시작점으로 사용 |
| AGENTS.md의 경로 표기 — 수정 완료 | 프로젝트 기준의 중복 aws-infra 접두사와 상위 기준의 infra/-routing 오타 | 프로젝트 기준 ./README.md 및 ./docs/infra-routing/ROUTING-README.md로 수정. 상위 기준은 ./aws-infra/docs/infra-routing/ROUTING-README.md로 수정 |
| 루트 README를 Python 분석기에 입력 | EC2 사양 t3a.small/t3a.large 및 README.md 표기를 Python 심볼로 해석한 missing_symbol 9건 | 실제 Python 심볼 불일치와 구분. 스킬의 혼합 언어 문서 해석 한계로 기록 |
| 루트 README 구성 개요 Mermaid | MySQL 3대·게임 서버 2대 등 현재 배치표와 다른 표현이 남음 | 현재 값은 config 및 새 탐색 문서로 안내 |
| 루트 README의 시험용 test 경로 | 현 작업 파일에서 대응 경로를 찾지 못함 | 새 문서는 현재 infra 경로만 연결 |
| 설치 코드와 Terraform stack | 설치기는 Terraform >=1.6 허용, stack은 >=1.11 요구 | 설치기 문서에 두 조건을 구분 |
| 기존 설치 README | 과거 로그인 프로필·config/account1 경로 안내가 남음 | 새 문서는 topology의 계정별 프로필·현재 경로로 안내 |
| 기존 보안그룹 상세 문서 | 현재 Proxy 그림 외에 과거 배치·NAT 설계가 남음 | 새 문서의 통신 목록은 traffic JSON을 기준으로 작성 |

이 기존 차이들은 요청한 새 문서 폴더 밖에 있다. 프로젝트 전체 문서가 모두 동기화됐다고 판정하지 않는다.

## 다시 검사하는 명령

다음 명령은 프로젝트 루트에서 실행한다. 보고서는 임시 폴더에 저장하며 프로젝트 코드를 import하거나 실행하지 않는다. 다른 PC에서는 스킬 위치만 해당 설치 경로로 바꾼다.

```powershell
# Python 선언과 문서를 HEAD 변경 기준으로 비교한다.
$routingSkill = 'C:\Users\Playdata\.agents\skills\routing-doc-sync'
$routingReport = Join-Path $env:TEMP 'infra-routing-python-head.json'
python "$routingSkill\scripts\routing_doc_sync.py" --repo . --docs docs/infra-routing/tests/test_runner.py.md --base HEAD --target WORKTREE --output $routingReport
```

현재처럼 Python 코드가 HEAD 대비 추가 상태이면 참조가 맞아도 역할 검토 때문에 needs_review가 남을 수 있다. 변경 이력을 제외하고 현재 선언만 대조하려면 위 명령의 --base HEAD를 --base NONE으로 바꾼다. code/doc를 수정한 뒤에는 이전 보고서를 재사용하지 않고 다시 실행한다.

실제 배포·서비스 성능·DB 복구·SSH 접속·Bash 키 생성·Windows 도구 설치는 이번 문서 검사에서 실행하지 않았다.
