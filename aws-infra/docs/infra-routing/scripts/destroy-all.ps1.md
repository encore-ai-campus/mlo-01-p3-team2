# infra/scripts/destroy-all.ps1

[탐색 시작점](../ROUTING-README.md) · [원본](../../../infra/scripts/destroy-all.ps1) · [삭제 공통 함수](lib/infra-destroy.ps1.md) · [실행 명령](../../../infra/scripts/README.md#15-전체-인프라-삭제)

## 역할과 입력

이 프로젝트의 최대 12개 Terraform 상태를 대상으로 전체 삭제 계획을 준비하고 검토한 계획을 순서대로 적용한다. 다른 프로젝트나 상태 밖 자원을 계정 전체에서 찾아 삭제하는 기능은 아니다. S3 상태 버킷과 버전 이력은 유지한다.

| 입력 | 의미 |
| --- | --- |
| Action | Plan / Apply / Status / Verify. 필수 |
| RunId | Plan은 새 GUID 32자 ID 생성. 나머지 동작은 출력된 ID를 반드시 지정 |
| DeleteDataVolumes | Plan·Apply에 필수. 서비스 데이터 EBS도 삭제한다는 명시적 선택 |
| PluginDirectory | 기존 provider 디렉터리를 공통 실행기에 전달하는 선택 입력 |

## 실행 흐름

1. 공통 JSON·다섯 프로필의 STS 계정 ID·S3 버전 관리를 검사하고 AWS 프로세스 환경을 격리한다. 같은 PC의 전체 삭제 작업은 operation.lock 파일 핸들로 직렬화한다.
2. Plan은 Bastion → account1~5 workload → shared connectivity → account1~5 foundation 순으로 원격 상태를 읽는다. S3 NoSuchKey 또는 managed 인스턴스 0개만 Skipped로 기록한다. AccessDenied·인증 실패·잘못된 상태 형식은 중단한다.
3. 각 상태의 삭제 계획은 infra.ps1의 PlanMode=Delete·DestroyRunId·DeleteDataVolumes로 저장한다. Plan 전후 원격 상태가 같아야 하며 모든 계획·해시 검사를 마쳐야 실행 상태가 Ready가 된다.
4. Apply는 Ready 실행만 허용한다. 첫 삭제 전에 모든 계획·요약·manifest·입력 해시와 모든 원격 상태를 재검사한다. 각 단계는 저장 계획만 적용하고 상태의 managed 자원이 0개일 때 Deleted로 기록한다.
5. 중간 실패는 이후 단계를 실행하지 않고 Failed로 기록한다. Ctrl+C 등 중단으로 Applying이 남아도 같은 계획을 자동 재사용하지 않는다. 새로운 Plan으로 남은 상태를 검토한다.
6. 모든 단계 후 상태가 비었는지와 계획에 있던 주요 독립 AWS 자원 ID가 제거됐는지 조회한다. 확인 성공 시 Complete, 잔존 자원·조회 실패 시 VerificationFailed다. Verify는 삭제 API를 호출하지 않고 이 확인만 재실행한다.

Status는 로컬 run.json의 단계별 상태를 표시한다. AWS 실시간 상태 조회가 아니다. Verify는 Verifying·VerificationFailed·Complete 실행에만 허용하며 삭제가 미완료된 실행을 건너뛰는 명령이 아니다.

## 파일과 보호 경계

작업 경로는 infra/.local/destroy-all/{RunId}/다. run.json은 진행 기록, run.previous.json은 직전 기록이다. Save-DestroyRun 함수는 임시 파일을 기록한 뒤 교체한다. 계정/단계 하위의 saved.tfplan, saved-plan.json, delete-summary.json, remote-state.json과 terraform 캐시는 일반 배포의 .local/{Account}/{Stage}와 분리한다. delete_count는 Terraform 삭제 자원과 EC2에 연결된 OS 디스크 검증 항목 수이며 Terraform Plan의 destroy 개수와 다를 수 있다.

삭제 허용 검사와 원격 상태 조회는 [infra-destroy.ps1](lib/infra-destroy.ps1.md), 기존 계정·Plan 해시 검사는 [infra.ps1](infra.ps1.md)이 담당한다. 서비스 데이터 EBS의 prevent_destroy는 스크립트가 변경하지 않는다. 2026-10-10 현재 [compute/main.tf](../../../infra/terraform/modules/compute/main.tf)의 값은 false다. true인 상태에서 삭제하려면 사용자가 수동으로 false로 바꾼 뒤 새 Plan을 만들어야 한다. 코드 사본이나 override 파일은 생성하지 않는다. 값을 바꾸면 기존 Plan의 코드 해시가 달라지므로 새 Plan이 필요하다.

Terraform은 각 상태에 S3 잠금을 사용한다. operation.lock은 같은 PC에만 적용되며, 삭제 중 다른 PC에서 배포·Bastion 전원 작업·수동 콘솔 변경을 동시에 수행하는 것을 전체적으로 잠그지는 않는다. 상태 변경은 사전 해시 검사와 Terraform 저장 Plan 검사로 거부한다.

실제 AWS 생성·삭제 성공은 모의 테스트와 별개다. 수동 자원 때문에 AWS 삭제가 막히면 오류를 보고하며 강제 삭제·state rm·자동 import·전체 계정 청소로 우회하지 않는다.
