# 실행기 공통 함수 지도

[탐색 시작점](../../ROUTING-README.md) · [스크립트 지도](../README.md) · [원본 폴더](../../../../infra/scripts/lib)

| 파일 | 책임 | 연결 문서 |
| --- | --- | --- |
| [infra-common.ps1](infra-common.ps1.md) | 설정 읽기·입력 검증, 계정과 원격 상태 확인, 구성 지문·로컬 작업 경로·저장 계획 처리 | [infra.ps1](../infra.ps1.md), [deploy.ps1](../deploy.ps1.md), [설정 지도](../../config/README.md) |
| [infra-destroy.ps1](infra-destroy.ps1.md) | 삭제 단계 순서·허용 자원·태그·동작 검사, 진행 기록과 삭제 결과 확인 | [destroy-all.ps1](../destroy-all.ps1.md), [삭제 테스트](../../tests/destroy-tests.md) |

각 함수의 위치와 조건은 파일별 문서에서 찾는다. 공통 라이브러리를 수정할 때는 이를 호출하는 실행기와 테스트도 대조한다. workload의 서비스 콘솔 SSH 삭제 허용 조건은 infra-destroy.ps1 문서와 별도 PowerShell 회귀 테스트에 연결돼 있다.
