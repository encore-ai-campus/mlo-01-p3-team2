# infra/scripts/lib/infra-destroy.ps1

[탐색 시작점](../../ROUTING-README.md) · [원본](../../../../infra/scripts/lib/infra-destroy.ps1) · [전체 삭제 실행기](../destroy-all.ps1.md)

전체 삭제의 순서·저장 계획·원격 상태·삭제 결과 조회 함수다. 아래 선언은 PowerShell 원본과 대조했으며 Python AST 검사 대상이 아니다.

| 함수 | 입력과 책임 |
| --- | --- |
| Get-InfraDestroyTargets | 입력 없음. Bastion 1 → workload 5 → connectivity 1 → foundation 5 대상 반환 |
| Assert-InfraDestroyInvocation | Root·RunId·Account·Stage·Action. 실행 정보·코드 해시·고정 순서·Planning/Applying 상태·선행 단계 완료 검사 |
| Invoke-InfraDestroyAws | Command·Arguments·AbsentErrors. JSON 조회, CLI 시간 제한, 지정한 AWS 오류 코드만 자원 없음으로 처리 |
| Get-InfraDestroyState | Command·Backend·Account·Stage·Directory. 정확한 S3 key의 v4 상태 다운로드·해시·managed 인스턴스 수 계산 |
| Assert-InfraDeletePlan | Plan·Stage·Account·Topology·DeleteDataVolumes. 단계별 허용 주소·delete/no-op·태그·데이터 삭제 선택·계획 완료 여부 검사 |
| Assert-InfraDestroyArtifacts | Root·RunId·Run·Backend. 12개 단계 순서, 전체·공개키 fingerprint, 계획·manifest·요약 해시, 삭제 종류·대상·실행 ID 검사 |
| Test-InfraDeletedResources | Command·Topology·Resources. 삭제 계획의 주요 독립 AWS 자원 ID를 조회하고 남은 항목 반환 |

## 삭제 계획의 경계

managed 변경은 해당 단계의 기존 모듈·자원 주소만 허용한다. 생성·수정·교체·import·미완성·deferred 변경과 삭제 후 managed 자원이 남는 계획은 거부한다. tags_all을 제공하는 자원은 Project·Account·ManagedBy=Terraform·Layout=v2를 대조한다. shared Peering에서는 모듈의 requester/accepter 계정에 맞춰 Account를 판단한다.

workload의 콘솔 SSH Terraform 주소는 다음과 같다.

```hcl
aws_vpc_security_group_ingress_rule.bastion_console_ssh[0]
aws_vpc_security_group_ingress_rule.service_console_ssh["역할"]
```

서비스 역할별 규칙도 workload가 생성하므로 전체 삭제 대상에 포함한다. 이 정확한 자원 이름과 문자열 키 형식만 추가로 허용하며 다른 단계·이름·태그 검사와 delete/no-op 제한은 유지한다. [회귀 검사](../../../../infra/tests/test_destroy_console_ssh.ps1)는 실제 AWS 없이 허용·거부 경계를 확인한다.

데이터 EBS는 DeleteDataVolumes가 필요하다. EC2 루트 디스크가 delete_on_termination=false이면 계획을 거부한다. 자동 삭제되는 루트 디스크 ID는 결과 검증 목록에 포함한다. 이 함수는 prevent_destroy를 수정하지 않는다. Bastion은 기존 Assert-InfraBastionPlan의 전용 주소·Stage 태그 검사도 함께 받는다.

## 원격 상태와 결과 검증

S3 get-object의 NoSuchKey만 상태 없음으로 인정한다. 403·인증·네트워크·JSON 형식 오류를 빈 상태로 처리하지 않는다. 다운로드한 상태는 Git에서 제외되는 .local에 저장한다. 실제 자원 삭제와 관계없이 상태 파일을 먼저 지우지 않는다.

결과 조회는 EC2·OS/데이터 EBS·EIP·VPC·서브넷·SG·IGW·라우팅 테이블·NAT·Peering 요청 자원·키페어·ALB·대상 그룹 ID를 대상으로 한다. EC2 terminated·NAT deleted·Peering deleted 또는 서비스별 정확한 NotFound 오류를 제거된 상태로 인정한다. SG 규칙·라우트·리스너 같은 하위 항목은 Terraform 상태 비움과 부모 자원 제거를 함께 확인하며 전부를 개별 API로 조회하지 않는다.

계획에 없는 수동 자원·스냅샷·다른 프로젝트 자원은 이 검증의 전수 조사 대상이 아니다. 코드의 실제 AWS 삭제 API 호출은 없고, 삭제는 저장 Plan을 적용하는 Terraform만 수행한다.
