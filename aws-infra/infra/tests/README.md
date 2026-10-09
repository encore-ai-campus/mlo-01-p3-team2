# 검증 범위와 결과

## 현재 검사 지도 — 2026-10-10

아래 날짜별 통과 기록은 기존 검증 이력이다. 이번 일반 문서 갱신에서는 Terraform·PowerShell 모의 테스트나 실제 AWS 배포·삭제·서비스 시험을 실행하지 않았다. 로컬 문서 링크·현재 설정 설명을 확인한 범위와 테스트 실행 결과를 구분한다.

현재 테스트에는 [Spark 포트·콘솔 SSH 검사 지도](../../docs/infra-routing/tests/README.md)가 있다. Spark 포트 범위 검사는 model 4개·security-rules 1개·workload 4개이며, 콘솔 SSH 검사는 workload의 계정별 5개다. 검사 선언이 있다는 사실만으로 현재 환경에서 모두 통과했다고 기록하지 않는다. 기존 workload 테스트의 최종 통과 여부 미확인 기록도 아래에 유지한다. 라우팅 문서가 확인한 account1_default_closed의 이전 5개 노드 기대값은 현재 4개 workload 노드와 불일치하므로 기존 테스트 전체가 현재 코드에서 통과한다고 안내하지 않는다.

현재 compute 데이터 EBS 보호 값은 prevent_destroy=false다. 아래 보호 관련 실패와 임시 코드 사본의 보호 해제는 당시 시험 조건이다. 실제 AWS 삭제·provider 실행 순서·원격 동시 실행은 별도 검증 범위다.

## 서비스 콘솔 SSH 삭제 경계 검사 기록 — 2026-10-10

작업 중 갱신된 [삭제 검사 라우팅 문서](../../docs/infra-routing/tests/destroy-tests.md)에 따르면 test_destroy_console_ssh.ps1은 서비스 역할 7개의 정확한 자원 주소와 기존 Bastion 주소를 허용하고, 잘못된 이름·키·단계·태그·수정·import를 거부하는 별도 검사다. 해당 문서에는 Windows PowerShell 5.1에서 16개 검사 통과가 기록되어 있다. 이는 기존 작업의 검증 기록이며 이번 일반 문서 갱신에서 재실행한 결과가 아니다.

```powershell
# aws-infra 루트에서 모의 검사만 실행한다. AWS·Terraform은 호출하지 않는다.
powershell -NoProfile -ExecutionPolicy Bypass -File .\infra\tests\test_destroy_console_ssh.ps1
```

기존 전체 삭제 모의 테스트 17개와 서비스 콘솔 SSH 모의 검사 16개는 서로 다른 검사다. 실제 AWS 삭제 완료의 근거로 사용하지 않는다.

## 전체 삭제 실행기 추가 검증 — 2026-10-09~10

[전체 삭제 모의 테스트](../../docs/infra-routing/tests/destroy-tests.md)는 Windows PowerShell 5.1과 PowerShell 7에서 각각 17개 시나리오가 통과했다. 전체 Plan 준비, 삭제 순서, 변조·계정·권한 오류 거부, 중간 실패 후 새 Plan, 잔존 상태·자원의 완료 거부와 Verify를 검사한다. 기존 실행기 테스트 8개도 재실행하여 통과했다.

```powershell
# 실제 AWS/Terraform 대신 가짜 CLI와 임시 상태로 검증한다.
python .\infra\tests\test_destroy_all.py powershell
python .\infra\tests\test_destroy_all.py pwsh
python .\infra\tests\test_runner.py
```

새 테스트의 EBS 보호 해제는 임시 코드 사본에서만 수행한다. 원본 compute/main.tf·계정 설정·키는 변경하지 않는다. 실제 AWS 삭제, provider의 삭제 순서와 원격 동시 실행은 이 검사로 검증하지 않았다. 결과와 구조 검사 한계는 [검증 기록](../../docs/infra-routing/verification.md)에 구분해서 기록한다.

## 기존 검증 기록

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
