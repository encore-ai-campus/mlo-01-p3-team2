# infra/scripts/infra.ps1

[탐색 시작점](../ROUTING-README.md) · [원본 실행기](../../../infra/scripts/infra.ps1) · [공통 함수](lib/infra-common.ps1.md)

## 역할과 입력

계정과 단계를 선택해 Terraform을 실행한다. 자원 정의는 Terraform stack에 두고, 이 파일은 설정 검사·프로필 확인·상태 분리·저장 계획 검사를 담당한다. 별도 함수 선언 없이 스크립트 본문이 순서대로 실행된다.

| 매개변수 | 허용 값·기본값 |
| --- | --- |
| Account | account1~account5 또는 shared. 기본 account1 |
| Stage | foundation / connectivity / workload. 필수 |
| Action | Validate / Test / Plan / Apply / Output. 필수 |
| PluginDirectory | 선택. init에 전달할 기존 provider 디렉터리 |

connectivity는 shared와만 조합한다. 나머지 단계는 account1~account5 중 하나를 지정한다. Profile·Node·all·Destroy·Stop·Start 옵션은 없다.

## 처리 순서

1. 같은 scripts 폴더의 lib/infra-common.ps1을 불러온다.
2. 스크립트 위치의 상위인 infra를 기준으로 config·terraform·.local 경로를 계산한다. 현재 터미널 위치에 의존하지 않는다.
3. 계정·단계 조합을 확인한다. Plan은 기존 saved.tfplan과 saved-plan.json을 먼저 제거해 실패한 새 계획 대신 옛 계획을 적용하지 않게 한다.
4. topology·traffic·backend JSON을 읽고 공통 설정을 검사한다. workload의 공개키 상대 경로는 infra 기준이다.
5. Plan·Apply·Output은 backend 설정을 검사한다. workload Plan·Apply는 AMI 형식·존재하는 공개키·해당 시 ACM ARN도 검사한다.
6. Apply는 저장 계획·대상 계정·단계·상태 경로·설정/코드/공개키 해시·계획 파일 해시를 대조한다.
7. 지정한 AWS/TF 프로세스 환경변수를 보관하고 격리한다. 온라인 동작에서는 대상 및 backend 프로필을 STS로 확인하고 상태 버킷의 버전 관리가 Enabled인지 확인한다.
8. Terraform init 후 선택한 Action을 수행한다. 종료 시 finally에서 보관한 환경변수를 복원한다.

## Action 분기

| Action | Terraform 동작 | 동작의 범위 |
| --- | --- | --- |
| Validate | init -backend=false → validate | 문법·구성 검사. 실제 AWS 검증 아님 |
| Test | init -backend=false → test | 해당 stack의 모의 테스트. 선택 Account로 테스트 run을 필터링하지 않음 |
| Plan | S3 init → runtime.tfvars.json 작성 → plan -out | 변경 계획과 manifest 저장. 실제 자원 적용 없음 |
| Apply | S3 init → apply 저장 계획 | 별도 확인 질문 없이 저장 계획 적용. 성공 후 계획과 manifest 제거 |
| Output | S3 init → output -json | 상태 출력을 outputs.json으로 저장. 실시간 서비스 상태 조회 아님 |

Validate·Test도 provider가 없으면 다운로드가 필요할 수 있다. 스크립트는 브라우저 로그인이나 S3 버킷 생성을 수행하지 않는다.

## 경로와 상태

| 종류 | 계산 규칙 |
| --- | --- |
| Terraform 코드 | infra/terraform/stacks/{Stage} |
| 로컬 작업 폴더 | infra/.local/{Account}/{Stage} |
| 저장 계획 | 작업 폴더의 saved.tfplan, saved-plan.json |
| Plan 런타임 입력 | 작업 폴더의 runtime.tfvars.json |
| 상태 출력 | 작업 폴더의 outputs.json |
| 온라인 TF_DATA_DIR | 작업 폴더의 terraform |
| Validate/Test TF_DATA_DIR | 작업 폴더의 validate-terraform |
| S3 key | {key_prefix}/{Account}/{Stage}/terraform.tfstate |

S3에는 계정별 foundation/workload 10개와 shared/connectivity 1개, 총 11개 상태를 사용한다. encrypt와 use_lockfile을 활성화하며 Terraform workspace는 default로 고정한다. shared Plan의 account_key 입력은 호환용 account1이고, 실제 연결 양쪽 프로필은 connectivity/providers.tf에 명시돼 있다.

## 변경할 때 함께 확인

입력 검사·해시 범위는 [공통 함수 문서](lib/infra-common.ps1.md), 실행기 보호 동작은 [Python 테스트 문서](../tests/test_runner.py.md), 실제 옵션 안내는 [실행 README](../../../infra/scripts/README.md)를 함께 확인한다. 문서 파일은 fingerprint 대상에 포함되지 않는다.
