# 전체 삭제 모의 테스트

[탐색 시작점](../ROUTING-README.md) · [테스트 지도](README.md) · [실행기](../scripts/destroy-all.ps1.md)

## 파일과 실행 범위

- [test_destroy_all.py](../../../infra/tests/test_destroy_all.py): 테스트 사본·가짜 CLI 경로를 만들고 PowerShell 전체 삭제 실행기를 호출한다.
- [test_destroy_once.py](../../../infra/tests/test_destroy_once.py): Destroy의 단일 실행, 동일 실행 ID·삭제 순서, 실패 시 중단과 보호 복원을 검사한다. 기존 테스트의 seed·JSON 보조 함수를 재사용하고 실패 주입용 가짜 CLI를 추가한다.
- [destroy_cli.py](../../../infra/tests/destroy_cli.py): AWS/Terraform을 대신하여 모의 상태·계획·조회 응답을 JSON으로 처리한다. 네트워크나 실제 클라우드를 호출하지 않는다.
- [test_destroy_console_ssh.ps1](../../../infra/tests/test_destroy_console_ssh.ps1): 전체 삭제 검사 함수를 직접 호출해 역할별 서비스 콘솔 SSH 규칙의 허용과 다른 주소·단계·계정 태그·수정·import 거부를 검사한다. AWS와 Terraform 실행 파일을 호출하지 않는다.

임시 파일은 infra/.local/tests/destroy-{ID}/에 남긴다. 원본 설정·키·Terraform을 사본으로 읽되 .local·.terraform·개인키 파일은 복사하지 않는다. EBS 보호 해제는 테스트 사본에서만 수행한다. 가짜 aws/terraform 경로가 우선 선택되는지 검사한 뒤 실행기에 진입한다.

## 검사 시나리오

전체 Plan 준비 중 Apply 미호출, 데이터 삭제 선택 누락, 잘못된 계정, S3 접근 거부, 계획 변조, 원격 상태 변경, 삭제 순서 변경, 코드·공개키 변경을 검사한다. 정상 실행은 12개 단계 순서·빈 상태·주요 AWS ID 제거를 확인한다. 중간 Apply 실패 후 하위 단계 중단과 새 Plan으로 남은 상태 재개, Apply 후 상태 잔존, 실제 ID 잔존 시 완료 거부와 Verify 재조회도 검사한다.

prevent_destroy가 켜진 테스트 사본의 Plan 실패, 생성/수정이 섞인 계획·다른 자원의 삭제 거부, 미생성 Bastion 상태 건너뛰기를 포함한다. 모의 Peering 수락 측에는 Account 2 태그를 사용해 다른 계정 소유권 검사를 확인한다.

한 번의 삭제 검사는 12개 시나리오를 선언한다. 정상 12단계 삭제·동일 실행 ID·BOM/CRLF 원본 복원·복원 후 Status/Verify, Verify의 코드 변경 거부, Plan 실패 시 Apply 미호출, 중간 Apply 실패 시 후속 중단, 데이터 삭제 선택 누락·다른 Action의 보호 옵션·기존 RunId 거부, 원래 false 유지, 보호 해제 옵션 없는 true의 실패, 지원하지 않는 lifecycle 형식 거부, 외부 파일 수정과 원본 사본 변조 시 복원 실패를 검사한다. 보호 옵션·사양 변경은 임시 사본에서만 수행한다. 이 선언 목록은 실제 AWS 삭제 성공을 뜻하지 않는다.

```powershell
# 프로젝트 루트에서 실행한다. 각 시험은 가짜 CLI 선택을 검사한다.
python .\infra\tests\test_destroy_once.py powershell
python .\infra\tests\test_destroy_once.py pwsh
```

2026-10-10 이번 구현의 최종 실행에서 Windows PowerShell 5.1·PowerShell 7 각각 단일 삭제 12개 시나리오를 통과했다. 기존 전체 삭제 17개 시나리오는 Windows PowerShell 5.1에서, 콘솔 SSH 삭제 경계 16개는 별도 PowerShell 검사에서 통과했다. 기존 전체 삭제 테스트가 가정하는 보호 초기값 true는 격리된 회귀 시험 사본에서만 설정했다. 작업 파일의 compute 보호 값 false는 보존했다. 실제 AWS·Terraform provider·원격 동시 작업을 시험한 결과는 아니다.

서비스 콘솔 SSH 허용 목록 회귀 검사는 별도로 실행한다. 실제 오류의 ad 규칙을 포함한 현재 서비스 역할 7개와 기존 Bastion 주소를 허용하고 비슷한 자원 이름·잘못된 키·추가 주소·다른 단계·계정 태그 불일치·수정·import를 거부한다. Terraform 주소는 위 PowerShell 검사 파일과 [삭제 경계 문서](../scripts/lib/infra-destroy.ps1.md)에 있다.

2026-10-13에는 현재 Front 송신 규칙 두 개의 허용 및 다른 역할·유사 이름·단계·계정 태그·수정 거부를 추가하여 Windows PowerShell에서 총 28개 경계 검사를 통과했다. 실제 AWS 삭제 계획에서 발견된 광고 Front 송신 규칙의 허용 누락 회귀 검사다. 정확한 Terraform 주소는 [삭제 경계 문서](../scripts/lib/infra-destroy.ps1.md#삭제-계획의-경계)에서 확인한다.

```powershell
# C:/third_project/aws-infra에서 실행하며 실제 클라우드는 호출하지 않는다.
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\tests\test_destroy_console_ssh.ps1
```

## Python 선언

선언은 routing-doc-sync inventory와 대조한다. 경로는 Git 최상위 기준이며 aws-infra/ 접두사를 포함한다. 함수 역할은 작성한 테스트의 목적이며 AST 구조 일치가 테스트 성공이나 실제 AWS 동작을 증명하지 않는다.

| 정규 선언 참조 | 역할 |
| --- | --- |
| `aws-infra/infra/tests/test_destroy_all.py::def read(path)` | 테스트 JSON 읽기 |
| `aws-infra/infra/tests/test_destroy_all.py::def write(path, value)` | 테스트 JSON 쓰기 |
| `aws-infra/infra/tests/test_destroy_all.py::def seed(root, infra, protected=False)` | 코드 사본·가짜 CLI·모의 상태 준비 |
| `aws-infra/infra/tests/test_destroy_all.py::def invoke(root, shell, action, run_id=None, fault='', consent=True, success=True)` | 가짜 CLI 경로 검사·PowerShell 실행·성공 여부 확인 |
| `aws-infra/infra/tests/test_destroy_all.py::def apply_calls(root)` | 모의 적용 호출 확인 |
| `aws-infra/infra/tests/test_destroy_all.py::def main()` | 테스트 전체 실행 |
| `aws-infra/infra/tests/test_destroy_all.py::def main.clone(name)` | 검토된 계획을 사례별 테스트 사본으로 복제 |
| `aws-infra/infra/tests/test_destroy_once.py::def apply_steps(root)` | 계획 파일 삭제와 무관하게 가짜 Terraform 호출의 적용 순서 집계 |
| `aws-infra/infra/tests/test_destroy_once.py::def mock_cli(kind, args)` | 기존 가짜 CLI에 Plan/Apply 실패·원본/사본 변조 주입 |
| `aws-infra/infra/tests/test_destroy_once.py::def make_fixture(root, infra, protected=True, full=False)` | 임시 원본 바이트·모의 상태·CLI 경로 준비 |
| `aws-infra/infra/tests/test_destroy_once.py::def invoke_once(root, shell, action='Destroy', run_id=None, fault='', consent=True, disable=True, success=True)` | 가짜 CLI 경로 검사 후 실행기 호출, 출력과 성공 여부 확인 |
| `aws-infra/infra/tests/test_destroy_once.py::def main()` | 단일 삭제 12개 시나리오 실행과 작업 파일 보존 검사 |
| `aws-infra/infra/tests/destroy_cli.py::def read(path)` | 모의 상태·계획 읽기 |
| `aws-infra/infra/tests/destroy_cli.py::def write(path, value)` | 모의 상태·계획 쓰기 |
| `aws-infra/infra/tests/destroy_cli.py::def main()` | 허용된 모의 AWS/Terraform 호출 분기 |
| `aws-infra/infra/tests/destroy_cli.py::def main.option(name)` | 모의 CLI 옵션 값 읽기 |
| `aws-infra/infra/tests/destroy_cli.py::def main.fail(code)` | 지정한 AWS 오류를 모사 |

실행 결과와 AST 검사 한계는 [검증 기록](../verification.md)에 기록한다. 서비스 설치·실제 IAM 권한·Terraform provider의 AWS API 동작·원격 동시 실행은 이 모의 테스트로 검증되지 않는다.
