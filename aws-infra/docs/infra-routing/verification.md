# 문서 대조 기준과 검증 범위

[탐색 시작점](ROUTING-README.md) · [적용 규칙](../../AGENTS.md)

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

- [서비스 콘솔 SSH](terraform/stacks/workload.md#콘솔-ssh-규칙의-범위): 리전별 EC2 Instance Connect 관리형 IPv4 접두사 목록을 조회하고 서비스 SG에 TCP 22를 허용한다. 계정별 3 / 2 / 4 / 2 / 3개, 총 14개 SG가 대상이다. 기존 Bastion 규칙의 대상·주소는 유지한다. 이 경로와 [별도 모의 테스트](tests/README.md)를 탐색 목록에도 반영했다.
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

아래 기록의 “현재”와 검사 수치는 각 당시 시점의 값이다. 특히 데이터 EBS 보호가 유지된다는 과거 설명은 2026-10-10 작업 파일의 false 설정을 설명하지 않는다. 현재 구현은 위 기록과 영역별 문서를 기준으로 확인한다.

## 2026-10-09~10 전체 삭제 기능 구현 당시 기록

사용자가 요청한 전체 삭제 실행기를 추가했다. [destroy-all.ps1](scripts/destroy-all.ps1.md)은 모든 삭제 Plan을 준비하고 검토한 실행 ID로 Bastion → workload 5개 → connectivity → foundation 5개를 순차 적용한다. [infra-destroy.ps1](scripts/lib/infra-destroy.ps1.md)에 범위·태그·계획·상태·결과 검사를 두고, 기존 실행기와 fingerprint에 연결했다. 실제 명령은 [실행 README 15절](../../infra/scripts/README.md#15-전체-인프라-삭제)에 있다.

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
- [setup-proxy.sh](setup-proxy.sh.md)는 수동 Squid 패키지 설치만 수행한다. Proxy ACL·클라이언트 설정·실제 송신 검증이나 Terraform의 자동 설치 기능으로 기록하지 않는다.

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

- [기존 workload 모의 테스트](tests/README.md#현재-입력과-모의-테스트의-차이)는 Account 1에 Bastion 포함 5대와 다른 계정의 bare SG ID를 기대하여 현재 구현과 불일치한다. 이번에는 차이만 기록하고 테스트 코드를 수정하지 않았다.
- 당시에는 전체 인프라 삭제 실행기가 없고 Delete 계획이 bastion 단계에만 허용됐다. 위 구현으로 전체 삭제 실행기가 추가됐으며 원본 서비스 데이터 EBS의 prevent_destroy는 계속 유지한다.
- 루트 README·infra/README.md 등 라우팅 폴더 밖에 있는 이전 배치·Bastion·HTTPS 설명은 이번 수정 범위 밖이다.
- 실제 AWS 생성·삭제, 접속·서비스·Proxy·데이터 보존 검증은 이번 문서 동기화에서 수행하지 않았다. 이 조건들이 남아 있어 자동 스테이징·커밋은 하지 않으며 기존 index를 유지한다.

## 이전 작업의 검증 기록

아래 기록의 “현재”와 검사 수치는 각 이전 작업 시점의 값이다. Bastion 포함 workload·빈 관리자 CIDR 등의 설명은 위 추가 동기화로 갱신됐으며 현재 구현 설명으로 사용하지 않는다. 과거 결과와 오류·승인 기록은 보존한다.

<details>
<summary>이전 광고 서버 이동·문서 대조 기록 보기</summary>


[탐색 시작점](ROUTING-README.md) · [적용 규칙](../../AGENTS.md)

## 광고 서버 account1 이동 후 추가 검증

2026-10-09 광고 서버 이동 작업에서는 topology·traffic JSON, model·workload·alb의 main.tf 등 요청된 코드·설정 5개와 이번 변경에 관련된 라우팅 문서만 수정했다. 아래 기존 문서 작업 기록의 수정 범위·미실행 표시는 당시 기록이다.

- 서버 배치: account1 Private C의 ad-server, 계정별 5 / 2 / 4 / 2 / 3대, 전체 16대. ad의 사양·디스크·공인 IP 설정은 수정 전과 동일하다.
- 연결: alb_ad의 TCP 8000, ad 대상 그룹·EC2 연결, 우선순위 20의 /ads/* 규칙. 기존 /static/* 규칙과 game 기본 대상은 유지한다.
- JSON을 작업 시작 시점과 구조적으로 비교해 광고 서버의 account, 광고용 ALB 항목 세 개, ad 포트와 alb_ad 연결 외의 값이 같음을 확인했다.
- 변경한 Terraform 3개 파일의 fmt -check와 workload의 validate가 통과했다. validate는 처음 샌드박스에서 provider 응답 오류가 발생했고, 승인된 샌드박스 밖 재실행에서 통과했다.
- routing-doc-sync 분석기로 기존 Python 구조 문서의 참조를 재검사했다. Python 구조 검사는 Terraform·JSON의 동작 검증이 아니며, 이번 비Python 변경은 해당 원본과 라우팅 문서를 별도로 대조했다.
- 최초에는 테스트 파일을 유지했으나 사용자 추가 승인 후 fixtures.json 및 foundation/workload 테스트 파일을 변경된 배치에 맞췄다. account1에 ad SG와 광고 노드를 포함하고 account2에서는 제외했다. workload에는 ALB→ad:8000 양방향 SG 참조 검사를 추가하고 닫힌 기본값 검사에서만 CIDR을 비웠다. 자세한 내용은 [테스트 지도](tests/README.md#현재-입력과-모의-테스트의-차이)에 기록했다.
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

사용자가 전체 삭제를 준비하는 과정에서 `aws_vpc_security_group_ingress_rule.service_console_ssh["ad"]`를 단계 밖 자원으로 거부하는 오류를 보고했다. workload/main.tf에는 해당 역할별 자원이 있지만 Assert-InfraDeletePlan의 workload 허용 목록에는 기존 Bastion 콘솔 SSH 주소만 있었다.

infra-destroy.ps1의 workload 주소 패턴에 정확한 service_console_ssh 이름과 문자열 역할 키 형식만 추가했다. 단계 순서·태그·계정·delete/no-op·데이터 EBS 동의·저장 계획 해시 검사는 유지한다. 소스 변경으로 기존 실패 실행 ID를 재사용하지 않고 새 Plan을 생성해야 한다.

별도 test_destroy_console_ssh.ps1에서 실제 오류 주소를 포함한 현재 서비스 역할 7개와 기존 Bastion 주소를 허용하고, 비슷한 자원 이름·잘못된 키·추가 주소·관련 없는 자원·다른 단계·계정 태그 불일치·수정·import를 거부하는 16개 검사를 Windows PowerShell 5.1에서 통과했다. AWS·Terraform 실행 파일은 호출하지 않았다. 기존 전체 삭제 모의 테스트 17개를 이번에 재실행한 결과로 취급하지 않는다.

관련 라우팅 문서와 테스트 탐색 링크를 갱신했다. Python AST 분석기의 역할 의미 not_verified와 비Python 검사 한계를 유지하며 PowerShell 실행 검사와 구분한다. 실제 사용자 삭제 Plan·Apply·AWS 삭제 완료는 아직 확인하지 않았고, 기존 Git 스테이징 상태를 보존했다.
