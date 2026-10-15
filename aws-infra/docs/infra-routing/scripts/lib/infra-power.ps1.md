# infra/scripts/lib/infra-power.ps1

같은 폴더의 infra-common.ps1을 로드한다. Invoke-PowerAws는 Invoke-InfraCapturedCommand로 출력·종료 코드를 수집하며, 제한 시간·DryRunOperation 판정·오류 메시지는 유지한다. 자식 프로세스의 환경 해제 범위와 Check·Change 각각의 인증 검사는 그대로다.

[공통 함수 지도](README.md) · [원본](../../../../infra/scripts/lib/infra-power.ps1) · [전체 전원 실행기](../power-all.ps1.md) · [모의 테스트](../../tests/power-tests.md)

power-all.ps1의 계정별 자식 작업에서 실행하는 AWS CLI 작업자다. 입력은 AwsCommand·TargetJson·Operation(Stop/Start)·Mode(Check/Change)·TimeoutSeconds다. 자체적으로 계정 전체를 검색하지 않고 부모가 전달한 EC2 ID만 조회한다.

## 함수와 검사 위치

| 함수 | 입력·책임 |
| --- | --- |
| Invoke-PowerAws | Arguments, 선택 DryRun. 대상 프로필·리전으로 AWS CLI 실행, 연결 5초·읽기 20초 제한, 종료 코드·JSON 처리. DryRun은 DryRunOperation 응답만 권한 검사 성공으로 인정 |
| Get-PowerInstances | 입력 없음. 대상 ID의 소유자·중복·누락·Project/Account/ManagedBy/Layout/Node/Role 태그를 검사하고 상태·사설/공인 IP 반환. Bastion은 Stage 태그도 검사 |

자식 프로세스에서 상속한 자격 증명·프로필·역할·엔드포인트 환경 변수를 제거하고 대상 프로필을 명시한다. EC2 메타데이터 인증과 대화형 CLI 입력을 비활성화한다. Check·Change 각각 STS 계정 ID를 대조하므로 사전 검사 후 인증 정보가 달라진 경우도 다시 검사한다.

EBS 루트이며 running/stopped/pending/stopping 상태인 EC2만 허용한다. Check는 원하는 상태와 다른 인스턴스의 중지·시작 권한을 dry-run으로 확인한다.

## 전원 전환 루프

Stop은 running에서 stopped로, Start는 stopped에서 running으로 전환한다. pending·stopping 중인 서버는 안정 상태가 될 때까지 기다린다. 요청한 ID는 기록해 같은 작업에서 중복 요청하지 않고 최대 3초 간격으로 상태와 태그를 다시 확인한다. 모든 서버가 목표 상태에 도달하면 결과를 반환한다.

계정별 TimeoutSeconds가 지나면 현재 상태를 포함한 오류로 끝난다. 마지막 AWS 조회에는 CLI 제한 시간만큼 더 걸릴 수 있다. 강제 중지·OS 종료 생략·terminate·EBS 삭제는 호출하지 않는다. 일부 계정의 변경 실패 처리와 작업 정리는 [부모 실행기](../power-all.ps1.md)에서 담당한다.
