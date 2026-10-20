# 인프라 스크립트 지도

[탐색 시작점](../ROUTING-README.md) · [실행 명령 안내](../../../infra/scripts/scripts.md) · [공통 함수 지도](lib/README.md)

| 작업 | 진입 파일 | 연결되는 영역 |
| --- | --- | --- |
| 단계·계정별 Terraform Plan·Apply·Output | [infra.ps1](infra.ps1.md) | config → 공통 입력 검사 → foundation/connectivity/workload/bastion stack |
| EC2 배치·사양을 선택하고 인벤토리·프록시 준비 | [deploy.ps1](deploy.ps1.md) | 구성 폴더 → infra.ps1 → 플랫폼 인벤토리 → WSL setup-proxy.sh |
| 배스천 생성·삭제·전원·접속 정보 | [bastion.ps1](bastion.ps1.md) | 별도 bastion stack과 AWS EC2 조회·전원 제어 |
| 현재 구성의 전체 EC2 중지·시작 | [power-all.ps1](power-all.ps1.md) · [사용법](../../operations/ec2-power.md) | 로컬 배포 출력 → 계정·태그·권한 확인 → [계정별 작업자](lib/infra-power.ps1.md)의 병렬 전원 요청 |
| 전체 인프라의 삭제 계획·적용·결과 검사 | [destroy-all.ps1](destroy-all.ps1.md) | infra-destroy.ps1의 단계 순서·자원 범위·저장 계획 검사 |
| 계정별 SSH 키 준비·서버 공개키 등록 | [account-keys.ps1](account-keys.ps1.md) | 공개키 경로·계정별 서버·SSH 연결 |
| Linux에서 SSH 키 파일 준비 | [prepare-key.sh](prepare-key.sh.md) | 로컬 파일·권한 준비 |

실행 옵션은 각 파일별 문서와 실행 명령 안내에서 확인한다. Plan과 Apply, 인벤토리 생성과 프로그램 설치는 서로 다른 동작이다. Proxy는 프록시 준비를 실행하며 DB·Kafka·Spark 설치 역할은 플랫폼 [site.yml](../../../../aws-platform/platform/docs/platform-routing/site.yml.md)에서 찾는다.

보호 조건을 수정할 때는 테스트 지도에서 모의 실행기·삭제 회귀 테스트를 함께 확인한다.
