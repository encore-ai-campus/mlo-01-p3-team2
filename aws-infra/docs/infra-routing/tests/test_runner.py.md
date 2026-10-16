# 실행기 테스트의 Python 구조

[탐색 시작점](../ROUTING-README.md) · [테스트 지도](README.md) · [원본 파일](../../../infra/tests/test_runner.py)

## 근거와 범위

routing-doc-sync의 inventory로 파일과 선언을 조사했다. 원본 Python 본문을 읽어서 함수 구조를 추출하지 않았고, 대상 모듈을 import하거나 실행하지 않았다.

모듈 docstring은 “AWS 호출 없이 Windows PowerShell 실행기의 계정·계획 격리를 검증한다.”이다. 분석 시 파싱 상태는 ok이며 클래스 선언은 없고 함수 선언은 세 개다. 모듈에는 함수 외 최상위 실행 코드도 있다.

## 파일·함수·선언

아래 선언은 분석기의 signature 값과 대조하는 정규 참조다. 인자에는 타입 annotation과 반환 타입 선언이 없다. 정규 참조는 Git 최상위 C:/third_project 기준이므로 aws-infra/ 접두사를 포함한다. 일반 문서 탐색 경로의 프로젝트 루트는 C:/third_project/aws-infra다.

| 파일과 선언 | AST 호출 이름에서 얻은 탐색 단서 |
| --- | --- |
| `aws-infra/infra/tests/test_runner.py::def run(action, account='account1', stage='foundation', extra=None, ok=True)` | subprocess.run, 결과 stdout/stderr decode, AssertionError 호출이 있다. 실행 결과를 확인하는 경로를 찾을 때 보는 함수 |
| `aws-infra/infra/tests/test_runner.py::def calls()` | log.exists, log.read_text, splitlines, json.loads 호출이 있다. 기록된 호출 로그를 읽는 경로의 후보 |
| `aws-infra/infra/tests/test_runner.py::def count_apply()` | calls와 sum 호출이 있다. apply 호출 집계를 찾는 후보이나 정확한 집계 조건은 AST 요약만으로 검증 불가 |

함수별 설명은 정적 호출 이름과 함수명에서 얻은 탐색 단서다. 호출 대상의 실제 런타임 해석과 전체 로직의 의미가 검증됐다는 뜻은 아니다. 함수 docstring은 모두 없으며 스킬 결과의 role_status는 not_verified다.

## 모듈 수준 단서

분석기가 수집한 import는 pathlib.Path, json, os, shutil, subprocess, sys, uuid다. 최상위 calls_syntax에는 파일 쓰기, 설정 읽기, copytree, 환경 복사·갱신, subprocess.run, run, count_apply 등이 나타난다. 문자열로 생성하는 모의 Python 코드는 별도 원본 파일 선언으로 확정하지 않는다.

정확한 시나리오 설명은 [기존 테스트 안내](../../../infra/tests/TEST-README.md)에 있다. 이번 작업에서 이 테스트를 실행하거나 기존 성공 기록을 갱신하지 않았다. 구조 일치와 실제 테스트 성공은 별도다.

## 갱신 방법

함수·매개변수·기본값 변경 시 분석기를 재실행하고 inventory 및 documents.checks의 signature_match를 확인한다. 현재 HEAD 비교에서는 이 파일의 바이트 해시 차이는 있으나 structural_changed=false이고 변경 심볼은 없다. 이번 문서 작업에서 Python 코드는 수정하지 않았다. 재현 명령과 비교 기준은 [검증 기록](../verification.md)에 있다.
