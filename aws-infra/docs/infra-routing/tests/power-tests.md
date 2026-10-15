# 전체 EC2 전원 테스트 구조

[테스트 지도](README.md) · [전체 전원 실행기](../scripts/power-all.ps1.md) · [계정별 작업자](../scripts/lib/infra-power.ps1.md)

Python 구조는 routing-doc-sync의 HEAD → WORKTREE AST 보고서에서 추출했다. 대상 Python을 import하거나 함수 본문을 직접 읽어 선언을 추출하지 않았다. 역할 설명은 모듈 docstring과 호출 이름을 보조 근거로 대조했으며 구조 일치가 실제 AWS 전원 전환 성공을 뜻하지 않는다.

## 파일별 위치

| 원본 | 역할과 연결 |
| --- | --- |
| [test_power_all.py](../../../infra/tests/test_power_all.py) | 실제 AWS 변경 없이 전체 EC2 중지·시작, 계정 경계와 실패 처리를 검증하는 실행 진입점 |
| [power_cli.py](../../../infra/tests/power_cli.py) | 전원 테스트 전용 모의 AWS CLI. 계정별 파일을 사용해 병렬 호출을 격리 |

## Python 선언

| 정규 선언 참조 | AST에서 확인한 보조 근거 |
| --- | --- |
| `aws-infra/infra/tests/power_cli.py::def read(path)` | path.read_text와 json.loads 호출 |
| `aws-infra/infra/tests/power_cli.py::def write(path, value)` | json.dumps와 path.write_text 호출 |
| `aws-infra/infra/tests/test_power_all.py::def write(path, value)` | 부모 디렉터리 생성과 JSON 파일 쓰기 호출 |
| `aws-infra/infra/tests/test_power_all.py::def seed(name, state='running')` | 코드 사본·bin 폴더·모의 CLI 파일·입력 파일 준비에 사용하는 호출 |
| `aws-infra/infra/tests/test_power_all.py::def calls(root)` | 계정별 로그 파일 탐색·읽기·JSON 변환 호출 |
| `aws-infra/infra/tests/test_power_all.py::def mutations(root)` | calls를 사용해 호출 기록을 확인하는 보조 함수 |
| `aws-infra/infra/tests/test_power_all.py::def run(root, action, fault='', what_if=False, success=True, timeout=30, file_entry=False)` | 자식 프로세스 환경 준비·subprocess.run·실행 출력 저장 호출 |

선언 경로는 Git 최상위 기준이다. 호출 이름만으로 각 단언의 의미나 전체 분기 실행을 증명하지 않는다. 부모 실행기·작업자의 실제 전원 경계는 두 PowerShell 문서에서 확인한다.

## 실행 위치와 검증 범위

저장소 루트에서 별도로 실행하는 모의 테스트 명령이다.

```powershell
# 실제 AWS 대신 테스트용 CLI를 사용하는 전원 회귀 검사를 실행한다.
python -B .\aws-infra\infra\tests\test_power_all.py
```

이번 문서 동기화에서는 Python AST·문서 참조만 다시 검사했다. 모의 테스트나 원격 중지·시작을 재실행한 결과로 기록하지 않는다. 구조 검사 결과는 [검증 기록](../verification.md)에 남긴다.
