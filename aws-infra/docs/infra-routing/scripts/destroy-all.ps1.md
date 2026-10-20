# infra/scripts/destroy-all.ps1

환경 변수 저장·복원은 infra-common.ps1의 Save-InfraEnvironment / Restore-InfraEnvironment를 사용한다. 기존 변수 목록, 단계 순서, finally의 보호 복원·환경 복원·잠금 해제 순서는 유지한다.

[탐색 시작점](../ROUTING-README.md) · [원본](../../../infra/scripts/destroy-all.ps1) · [삭제 공통 함수](lib/infra-destroy.ps1.md) · [실행 명령](../../operations-recovery.md#6-전체-인프라-삭제)

## 역할과 입력

이 프로젝트의 최대 12개 Terraform 상태를 대상으로 전체 삭제 계획을 준비하고 검토한 계획을 순서대로 적용한다. 다른 프로젝트나 상태 밖 자원을 계정 전체에서 찾아 삭제하는 기능은 아니다. S3 상태 버킷과 버전 이력은 유지한다.

Destroy는 새 Plan → 기존 계획·상태 검사 → Apply → 결과 검증을 한 호출에서 수행한다. 실행 ID는 자동 생성하며 전체 흐름 동안 같은 operation.lock을 유지한다. 추가 입력 대기 없이 실제 삭제까지 진행하므로 DeleteDataVolumes를 반드시 지정한다. 기존 Plan·Apply·Status·Verify 명령도 유지한다.

| 입력 | 의미 |
| --- | --- |
| Action | Plan / Apply / Status / Verify / Destroy. 필수 |
| RunId | Plan·Destroy는 새 GUID 32자 ID 생성하며 입력을 거부한다. 나머지 동작은 출력된 ID를 반드시 지정 |
| DeleteDataVolumes | Plan·Apply·Destroy에 필수. 서비스 데이터 EBS도 삭제한다는 명시적 선택 |
| DisableDataVolumeProtection | Destroy에서만 허용. 지원하는 compute 데이터 EBS 선언의 true를 Plan 전에 false로 바꾸고 종료 시 원래 바이트로 복원. 이미 false이면 변경하지 않음 |
| PluginDirectory | 기존 provider 디렉터리를 공통 실행기에 전달하는 선택 입력 |

## 실행 흐름

1. 공통 JSON·다섯 프로필의 STS 계정 ID·S3 버전 관리를 검사하고 AWS 프로세스 환경을 격리한다. 같은 PC의 전체 삭제 작업은 operation.lock 파일 핸들로 직렬화한다.
2. Plan은 Bastion → account1~5 workload → shared connectivity → account1~5 foundation 순으로 원격 상태를 읽는다. S3 NoSuchKey 또는 managed 인스턴스 0개만 Skipped로 기록한다. AccessDenied·인증 실패·잘못된 상태 형식은 중단한다.
3. 각 상태의 삭제 계획은 infra.ps1의 PlanMode=Delete·DestroyRunId·DeleteDataVolumes로 저장한다. Plan 전후 원격 상태가 같아야 하며 모든 계획·해시 검사를 마쳐야 실행 상태가 Ready가 된다.
4. Apply는 Ready 실행만 허용한다. 첫 삭제 전에 모든 계획·요약·manifest·입력 해시와 모든 원격 상태를 재검사한다. 각 단계는 저장 계획만 적용하고 상태의 managed 자원이 0개일 때 Deleted로 기록한다.
5. 중간 실패는 이후 단계를 실행하지 않고 Failed로 기록한다. Ctrl+C 등 중단으로 Applying이 남아도 같은 계획을 자동 재사용하지 않는다. 새로운 Plan으로 남은 상태를 검토한다.
6. 모든 단계 후 상태가 비었는지와 계획에 있던 주요 독립 AWS 자원 ID가 제거됐는지 조회한다. 확인 성공 시 Complete, 잔존 자원·조회 실패 시 VerificationFailed다. Verify는 삭제 API를 호출하지 않고 이 확인만 재실행한다.

Status는 로컬 run.json의 단계별 상태를 표시한다. AWS 실시간 상태 조회가 아니다. Verify는 Verifying·VerificationFailed·Complete 실행에만 허용하며 삭제가 미완료된 실행을 건너뛰는 명령이 아니다.

## 한 번에 실행과 보호 복원

```powershell
# 프로젝트의 데이터 EBS까지 새 계획으로 검사한 뒤 자동 삭제한다.
.\infra\scripts\destroy-all.ps1 -Action Destroy -DeleteDataVolumes -DisableDataVolumeProtection
```

Set-DestroyDataProtection은 compute/main.tf의 aws_ebs_volume.data와 한 줄 lifecycle 선언을 각각 하나로 식별한다. 지원하지 않는 형식은 추측해서 수정하지 않고 중단한다. true인 경우 data-protection.original.tf에 원본을 보관하고 original_sha256·disabled_sha256·original_fingerprint와 Prepared 상태를 먼저 run.json에 저장한 뒤 파일을 교체한다. Plan·Apply는 보호를 해제한 동일 fingerprint를 사용하며 첫 삭제 전에 원본 사본의 해시도 검사한다. 기존 삭제 대상·태그·순서·원격 상태 검사는 우회하지 않는다.

Restore-DestroyDataProtection은 finally에서 원본 사본과 현재 파일의 해시를 검사한 뒤 원래 바이트를 복원한다. BOM·줄바꿈도 보존한다. 정상 완료뿐 아니라 Plan·Apply·결과 검증 실패에서도 복원하며, 원래 false이면 AlreadyDisabled로 기록하고 파일을 쓰지 않는다. 실행 중 외부 수정이나 사본 변조가 발견되면 덮어쓰지 않고 ProtectionRestoreFailed로 기록하여 실패로 종료한다. 완료 메시지는 복원 검사 후에만 출력한다.

복원 후에는 저장 Plan의 fingerprint를 바꾸지 않고 별도 verification_fingerprint에 보호 해제 전 기준을 남긴다. 이후 읽기 전용 Verify는 이 기준으로 코드·설정 변경을 검사한다. 실패한 Destroy 실행은 Apply로 재사용하지 않고 새 Destroy 또는 새 Plan으로 시작한다.

프로세스 강제 종료·전원 중단은 finally 실행을 보장하지 않는다. 이 경우 run.json의 보호 상태와 해당 실행 폴더의 data-protection.original.tf를 확인하고 현재 파일과 비교하여 원래 설정을 복구한 뒤 새 계획을 만든다. 상태 파일을 지우거나 기존 계획을 강제 적용하지 않는다.

## 파일과 보호 경계

작업 경로는 infra/.local/destroy-all/{RunId}/다. run.json은 진행 기록, run.previous.json은 직전 기록이다. Save-DestroyRun 함수는 임시 파일을 기록한 뒤 교체한다. 계정/단계 하위의 saved.tfplan, saved-plan.json, delete-summary.json, remote-state.json과 terraform 캐시는 일반 배포의 .local/{Account}/{Stage}와 분리한다. delete_count는 Terraform 삭제 자원과 EC2에 연결된 OS 디스크 검증 항목 수이며 Terraform Plan의 destroy 개수와 다를 수 있다.

삭제 허용 검사와 원격 상태 조회는 [infra-destroy.ps1](lib/infra-destroy.ps1.md), 기존 계정·Plan 해시 검사는 [infra.ps1](infra.ps1.md)이 담당한다. [compute의 데이터 EBS 보호](../terraform/README.md#compute)는 실제 소스의 prevent_destroy 값에 따른다. true/false 양쪽 동작은 [검증 기록](../verification.md)과 테스트에서 구분한다. DeleteDataVolumes만 지정하면 보호 값은 변경하지 않는다. 자동 해제·복원은 Destroy와 DisableDataVolumeProtection을 함께 지정한 경우에만 수행한다. 별도 Plan·Apply에서 보호 설정을 직접 변경했다면 새 Plan이 필요하다. override나 배포용 코드 사본은 만들지 않으며 복구용 원본은 해당 삭제 실행 폴더에만 보관한다.

Terraform은 각 상태에 S3 잠금을 사용한다. operation.lock은 같은 PC에만 적용되며, 삭제 중 다른 PC에서 배포·Bastion 전원 작업·수동 콘솔 변경을 동시에 수행하는 것을 전체적으로 잠그지는 않는다. 상태 변경은 사전 해시 검사와 Terraform 저장 Plan 검사로 거부한다.

실제 AWS 생성·삭제 성공은 모의 테스트와 별개다. 수동 자원 때문에 AWS 삭제가 막히면 오류를 보고하며 강제 삭제·state rm·자동 import·전체 계정 청소로 우회하지 않는다.

## edge 단독 초기 구축 상태

Get-InfraDestroyState가 account1 workload의 terraform_data.edge_bootstrap_guard 관리 인스턴스를 발견하면 단계에 edge_bootstrap_only=true를 기록한다. Plan·Apply는 이 값을 infra.ps1의 EdgeBootstrapOnly로 전달하여 아직 없는 다른 계정 foundation·connectivity 조회를 생략한다. 표식이 없으면 기존 정규 삭제 방식으로 처리한다. 단계와 저장 manifest의 모드가 다르면 실행을 거부한다.

edge의 EC2·OS 디스크·EIP·SG 규칙은 기존 workload 삭제 범위에 포함된다. EIP도 반납하므로 이후 재생성 시 이전 HTTPS 주소가 보존되지 않는다. 이 연동의 검증은 모의 테스트이며 실제 AWS 전체 삭제는 이번 작업에서 실행하지 않았다.

connectivity_ready는 edge_bootstrap_guard에 의존하며, compute와 SG 규칙은 connectivity_ready 뒤에 생성된다. 삭제 시 역순으로 정리해 EC2·규칙 삭제가 중단돼도 초기 구축 표식이 남도록 한다.
