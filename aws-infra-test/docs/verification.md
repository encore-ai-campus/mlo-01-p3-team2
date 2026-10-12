# 검증 기록 — 2026-10-11

실제 AWS 자원 생성·삭제·SSH·원격 설치는 실행하지 않았다. 다음은 로컬 코드 검사 결과다.

- Terraform foundation/connectivity/workload/bastion Validate: 모두 통과.
- Terraform mock provider Test: 총 9개 통과, 실패 0개.
  - foundation 2개: Account 1 Public A·Private A, Account 2 Private A만 생성. NAT·ALB SG 없음.
  - workload 5개: 서비스 3/3/4/3/3대, 모두 small, Bastion·Front B·ALB 제외. 테스트 원격 상태 prefix와 Front→game/ad 규칙 검사.
  - bastion 1개: 테스트 전용 키페어와 small 구성.
  - connectivity 1개: 10개 Peering의 A 라우팅 테이블과 상대 CIDR 양방향 연결, 테스트 상태 참조.
- Windows PowerShell 5.1: 모든 실행기 구문, 입력 검사, 기존 상태 prefix 거부, 기존 Project 삭제 거부, 교체 포함 삭제 거부, 범위 밖 삭제 거부, 삭제 순서 검사 통과.
- Bash run.sh/mount-data.sh 문법 통과. Windows CRLF로 생긴 최초 오류는 LF로 수정하고 재검사했다.
- Ansible front.yml/clusters.yml 문법 통과. 모의 인벤토리를 사용했으며 원격 연결은 하지 않았다.
- Front 템플릿 렌더링: 정적 파일·광고·게임·WebSocket·허용 CIDR 검사 통과. 실제 Nginx 서비스의 nginx -t 및 HTTP 응답은 배포 시 확인한다.
- small 메모리 설정 검사 및 17대·총 EBS 580GiB 선언 검사 통과. 이는 성능·부하 검증이 아니다.
- Terraform fmt 검사 통과.
- source-snapshot.json의 원본 파일 SHA256 불변 확인. 기존 aws-infra/aws-platform의 16개 staged 변경은 유지했다. 새 폴더는 커밋하지 않았다.

재현: infra/tests/check.ps1 -Terraform, WSL에서 bash infra/tests/check-bootstrap.sh.
로컬 provider를 사용할 경우 check.ps1에 -PluginDirectory를 지정한다. 검증 중 provider는 기존 설치본을 사용했고 AWS credentials나 실제 S3 상태를 사용하지 않았다.

남은 실제 검증: AWS 계정별 Plan 검토·Apply, Proxy 다운로드, EBS 장치·자동 마운트, 클러스터 설치와 복제·송수신, 게임/광고/Consumer 앱 배포, 사용자 부하, Bastion 재생성, 전체 삭제 후 잔여 자원 확인.
## 2026-10-12 학원 IP 및 HTTP/SSH 정책 변경 검증

- 최종 학원 IP: 222.112.208.69/32. 기본/current/테스트 traffic에 반영했다.
- workload Terraform 모의 테스트: 기존 33개 + 테스트 구성 10개, 총 43개 통과.
- 각 계정의 Private 역할별 학원 SSH 22, Front HTTP 80 전체 공개, Bastion 콘솔 SSH 미생성, 전체 공개 SSH 미생성을 검사했다.
- 기존 웹 비공개 테스트는 public_http_cidrs=[]를 명시해 비공개 설정도 계속 검증한다. 초기 edge만 생성하는 모드와 서비스 간 통신 회귀도 통과했다.
- PowerShell 구문·CIDR 검사 및 잘못된 public_http_cidrs 거부 검사 통과.
- routing-doc-sync 실행: mismatch 0, structural_status=needs_review, role_status=not_verified. 이번 Terraform·PowerShell 변경은 Python AST 검사 범위 밖이므로 해당 문서와 소스를 직접 대조했다. 보고서의 Python 구조 변경은 없으며 기존 Python 파일의 바이트 차이는 이 작업에서 수정하지 않았다.
- AWS Apply·원격 Nginx 설정은 실행하지 않았다. 새 Plan과 검토가 필요하며 테스트 Front는 Inventory 갱신 후 Front 설정을 다시 적용해야 HTTP 허용 CIDR이 반영된다.