# 검증 범위와 결과

2026-10-09 로컬 검증 기록이다. 실제 AWS 배포·삭제 테스트는 실행하지 않았다.

| 검사 | 결과 |
|---|---|
| foundation / connectivity / workload의 Terraform validate | 세 stack 모두 통과. 이후 출력·테스트 보완은 fmt로 문법 확인 |
| foundation 모의 테스트 | 3개 통과: Proxy 기본값, Account 2 Private A·C, 같은 AZ NAT 라우팅 |
| connectivity 모의 테스트 | 2개 통과: 10쌍·양방향 라우팅, 다른 계정 상태 거부 |
| workload 모의 테스트 | 최초 실행에서 Account 1·2 통과. Account 3에서 테스트 상태 공유로 prevent_destroy 발생 |
| workload 테스트 수정 | run마다 state_key를 분리. 수정 후 재실행 권한 요청이 거절되어 최종 통과 여부 미확인 |
| Windows PowerShell 5.1 실행기 모의 테스트 | infra/scripts로 이동한 뒤에도 8개 시나리오 모두 통과. infra 폴더 밖에서 실행해 경로 해석 확인 |
| prepare-key.sh | Git Bash 자체가 시작 오류(-1073741502)로 종료되어 구문·실행 검사 미완료. 키 생성은 실행하지 않음 |

실행기 테스트는 저장 계획 적용, 설정 변경 후 적용 거부, 잘못된 프로필 계정 거부,
새 계획 실패 후 옛 계획 무효화, 계정/단계 조합 검사, 계정별 backend·환경 인증 격리,
기존 환경 복원, SSH 전체 공개 거부를 확인한다.
실제 AWS와 Terraform 대신 임시 가짜 CLI를 사용하며 파일은 infra/.local/tests에만 만든다.

Terraform 테스트는 AWS mock provider와 terraform_remote_state override를 사용한다.
계정마다 별도 테스트 상태를 사용해 실제 계정별 상태 분리를 모사한다.
[Terraform 테스트 상태 설명](https://developer.hashicorp.com/terraform/language/tests#modules-state)

실제 IAM 권한, 계정별 AZ 제공 여부, AMI, 인증서, Peering 연결 상태, EC2 내부 프로그램 동작은
이 검사로 확인하지 않았다. 배포 전 실제 계획 및 설치 후 연결 확인이 필요하다.
