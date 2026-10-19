# WBS 전체 검토 기록

- 검토일: `2026-10-18` (KST)
- 대상: [WBS v1.3](./wbs.md)의 5개 영역·30개 작업
- 원격 dev: `8c27c107b53ee9573ba93af2d2e51ccb8af30c2b`
- 원격 doc: `fbb88944b7551081f0dbdd306548e8fafaa477b0`
- 최신 조회 기록: [GitHub 메타데이터](./github-evidence.json)

## 확인 방법과 결론

공개 GitHub API로 최신 브랜치·전체 PR 62개·일반 이슈 54개를 조회했다. 원격 SHA와 로컬 Git 객체의 SHA가 일치함을 확인한 뒤, 체크아웃 변경 없이 해당 커밋의 코드·계약·문서를 읽었다. 기존에 연결한 PR의 작성자·상태·병합일에는 변경이 없었다.

30개 작업 모두 관련 구현 또는 문서 근거를 확인했다. 이는 WBS의 작업 분류와 이력에 대한 정적 대조 결과이며, 모든 코드 줄의 정확성·기능 실행·운영 완료 판정이 아니다. 앱 테스트, DB 등록, 클라우드 상태 조회, 배포·장애·복구 시험은 수행하지 않았다. 실제 작업자는 PR 작성자 기준이며 공동 작업의 전체 기여도를 측정한 것은 아니다.

수정한 내용은 캠퍼스 찌르기 작업 누락, 작성자 본인 변경 권한의 명시, 문제은행 파일 구성의 구체화, 광고 후속 변경의 dev 미반영 상태, Spark 계약·테이블 수의 구분이다. 인프라는 앞서 수정한 6개 분류를 유지하며 README와 코드의 불일치를 추가로 기록했다.

v1.3에서는 PRD v0.10과 기존에 확보한 `infra;#45@7f6108562a5d5785983c4393d2b748d2011282a5` 변경 자료를 대조해 인프라 후속 작업을 추가했다. 아래 30개 작업 표는 기존 `dev` 대조 기록이며, 후속 기준과 정정 사항은 다음 절에 구분한다. 이번 보완에서 GitHub 병합 상태·AWS 자원·운영 서버를 새로 조회하지 않았으며 기존 메타데이터는 당시 조회 기록으로 보존한다.

## v1.3 인프라 후속 대조

- 기준: [infra;#45 후속 커밋](https://github.com/encore-ai-campus/mlo-01-p3-team2/commit/7f6108562a5d5785983c4393d2b748d2011282a5). 해당 변경의 `dev` 통합 예정이며, 기존 PR #90의 병합·검증 이력과 구분한다.
- 5.2 정정: Bastion은 EIP를 사용하며 후속 README에도 반영됐다. 아래 기존 검토 표의 자동 공인 IP 설명 불일치는 이전 커밋에서 확인한 사항으로, 후속 기준의 미해결 문제에 포함하지 않는다.
- 5.4 보완: 정식 게임 도메인 HTTPS, IP HTTPS·ACME 경로 외 HTTP의 도메인 이동, 정적 파일·선택 백엔드 WebSocket 연결, 도메인·IP 인증서 갱신을 추가했다. [운영 구성 문서](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/7f6108562a5d5785983c4393d2b748d2011282a5/aws-infra/docs/operations/current-state.md)는 후속 설정 코드가 로컬 검증 완료·EC2 재배포 전임을 명시한다.
- 5.5 보완: [전원 운영 기록](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/7f6108562a5d5785983c4393d2b748d2011282a5/aws-infra/docs/operations/ec2-power.md)의 평일 08:30 시작·매일 22:00 중지(KST), 예약 대상 18대·game-server-test 제외, 수동 current 명령 대상 19대의 차이를 반영했다. 수동 중지는 자동 예약을 비활성화하지 않는다. 기록된 조회 결과를 인용했으며 이번에 예약을 재조회하거나 변경하지 않았다.

## 1. 캠퍼스·커뮤니티

| WBS | 대조 결과 | 코드·문서 근거 |
|---|---|---|
| 1.1 | 회원·세션·과정별 아바타 코드 확인. AIO 4기 포함. | [accounts/cohorts.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/accounts/cohorts.py), [accounts/single_login.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/accounts/single_login.py) |
| 1.2 | 이동·층 전환·점프·찌르기 처리 확인. WBS에서 빠진 찌르기와 PR #62를 보완. | [campus/consumers.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/campus/consumers.py), [dist/isometric.js](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/frontend/dist/isometric.js) |
| 1.3 | 채팅 및 쪽지 당사자 조회 제한 확인. CAMPUS_DM_ENABLED 기본값은 0이며 운영 활성화는 별도. | [direct_messages/views.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/direct_messages/views.py), [config/settings.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/config/settings.py) |
| 1.4 | can_manage는 관리자(is_staff) 또는 작성자 본인을 허용. 공지는 관리자 제한. 제품 정책과 구현을 구분하도록 보완. | [community/views.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/community/views.py) |
| 1.5 | 설문·이벤트 참가·당첨자 저장·수령 안내 코드 확인. 외부 콘텐츠 내부 실행 완료까지 보장하지 않음. | [raffle/service.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/raffle/service.py), [raffle/winner_contact.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/raffle/winner_contact.py) |
| 1.6 | 프론트의 백엔드 중계와 백엔드 MySQL 설정 확인. 실제 이전 데이터 대조 결과는 PR #70의 기록으로 인용. | [pages/views.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/frontend/pages/views.py), [config/settings.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/config/settings.py) |

## 2. 학습

| WBS | 대조 결과 | 코드·문서 근거 |
|---|---|---|
| 2.1 | 선택 분류의 문제 풀에서 random.sample(pool, 10)으로 출제 확인. | [learning/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/services.py) |
| 2.2 | 기본 20 + 초기 과목 100 + 확장 2,280개를 정적 집계. 확장 12분류는 각각 190개. 적용 후 200개 검사·기본 dry-run·백업 필수 확인. | [commands/import_learning_bank.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/management/commands/import_learning_bank.py), [data/expanded_questions_20261016.json](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/data/expanded_questions_20261016.json) |
| 2.3 | MAX_ATTEMPTS=3, 서버 채점, 완료한 10문제 세션의 correct_count>=7 통과 확인. | [learning/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/services.py), [learning/views.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/views.py) |
| 2.4 | 결과·해설 공개와 선택 난이도에 맞는 세션 재개 분기 확인. | [learning/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/services.py), [learning/learning.js](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/frontend/learning/static/learning/learning.js) |
| 2.5 | 20/50/80 정책과 답안·지갑·원장·이벤트의 트랜잭션, 제출 UUID 중복 처리 확인. 관련 PR 작성자는 이재원. | [learning/point_policy.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/point_policy.py), [learning/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/services.py) |
| 2.6 | 지갑·원장은 learning 앱 내부 모델. 본인 잔액·내역·커서 조회 확인. 별도 backend/points 경로로 기재하지 않음. | [learning/models.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/models.py), [learning/views.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/learning/views.py) |

## 3. 광고

| WBS | 대조 결과 | 코드·문서 근거 |
|---|---|---|
| 3.1 | 캠페인 생성·변경·중단·해제와 관리자 화면 확인. 캠퍼스 계정의 자동 광고 계정 통합을 뜻하지 않음. | [campaigns/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/campaigns/services.py), [operator/views.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/console/operator/views.py) |
| 3.2 | 현재 archive_creative는 미종료 캠페인의 광고에 연결된 소재를 제한. 이슈 #93의 선택 소재 기준 변경은 dev 미반영. | [campaigns/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/campaigns/services.py) |
| 3.3 | 광고 선택의 기간·예산 등 필터와 매체 브리지·배치 코드 확인. 서버 김남동 / 브리지 조성현의 PR 구분 유지. | [engine/api.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/engine/api.py), [game/placements.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/ad_bridge/game/placements.py) |
| 3.4 | 반응 처리·중복 판정 및 과금·잔액·원장 코드 확인. 운영 전체 흐름 통과는 별도. | [records/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/records/services.py), [billing/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/billing/services.py) |
| 3.5 | 대시보드 기간 선택지는 7·14·30·90일. 가입 지급·관리자 조정·원장 조회 존재. '오늘' 선택지는 dev 미반영. | [console/forms.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/console/forms.py), [billing/services.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/billing/services.py) |
| 3.6 | Outbox→MongoDB ad_events 중계의 중복·충돌 처리 및 백필·구간 대조 도구 확인. | [events/relay.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/events/relay.py), [records/backfill.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/apps/ads_server/records/backfill.py) |

## 4. 파이프라인

| WBS | 대조 결과 | 코드·문서 근거 |
|---|---|---|
| 4.1 | 업무 Outbox·Kafka 발행, 커밋 알림·빈 큐 대기·연결 재사용 확인. 발행 측 실제 PR 작성자는 이재원. | [eventing/events.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/eventing/events.py), [eventing/publisher.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/backend/eventing/publisher.py) |
| 4.2 | 파싱 오류와 동일 event_uuid 내용 충돌을 별도 receipt로 기록하는 분기 및 원천 저장 확인. | [sinker/processor.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/std_and_sinker/sinker/processor.py), [sinker/mongo.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/std_and_sinker/sinker/mongo.py) |
| 4.3 | 계약·지문 검증, 표준 결과 저장, SUCCESS만 발행하는 분기 확인. | [sinker/contracts.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/std_and_sinker/sinker/contracts.py), [sinker/processor.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/std_and_sinker/sinker/processor.py) |
| 4.4 | 처리 후 offset 커밋, 재연결·점진 대기·미커밋 재처리 흐름 확인. 실제 장애 시험 범위는 이슈 #46의 제한 유지. | [sinker/worker.py](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/std_and_sinker/sinker/worker.py) |
| 4.5 | 퀴즈 1.1 계약과 포인트 Std 토픽 등록 확인. Raw 수신 README 예시에는 raw.points가 없으므로 실행 설정 확인은 유지. | [quiz_answered/1.1.json](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/std_and_sinker/contracts/events/quiz_answered/1.1.json), [contracts/registry.json](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/spark/contracts/registry.json) |
| 4.6 | 이벤트 유형 15종·버전별 schema 16개·Std 토픽 7개·사실 테이블 9개 확인. 오류 테이블 1개는 사실 테이블 수에서 제외. | [contracts/registry.json](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/spark/contracts/registry.json), [migrations/001_facts.sql](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/pipeline/spark/migrations/001_facts.sql) |

## 5. 인프라

| WBS | 대조 결과 | 코드·문서 근거 |
|---|---|---|
| 5.1 | 5개 계정의 topology 및 분리된 Terraform stack 구성 확인. 실제 AWS 자원 재조회는 하지 않음. | [config/topology.tfvars.json](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-infra/infra/config/topology.tfvars.json), [workload/main.tf](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-infra/infra/terraform/stacks/workload/main.tf) |
| 5.2 | 네트워크 구성 및 Bastion 전용 EIP 생성·연결·출력 확인. README의 자동 공인 IP 설명과 불일치하므로 코드 기준 유지. | [bastion/main.tf](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-infra/infra/terraform/modules/bastion/main.tf), [config/traffic.tfvars.json](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-infra/infra/config/traffic.tfvars.json) |
| 5.3 | MySQL·MongoDB·Kafka·ZooKeeper·Spark 및 game/ad/spark/mysql/backend Router 대상 확인. 설치·장애 전환 완료와 구분. | [platform/site.yml](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-platform/platform/site.yml) |
| 5.4 | Nginx·인증서 IP/수명·TLS·갱신 타이머 검사 코드 확인. 실제 성공 기록은 PR #90을 인용. | [tasks/verify.yml](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-platform/platform/roles/edge/tasks/verify.yml) |
| 5.5 | EC2 전체 Stop/Start 도구와 배포 명령 확인. Monitoring은 대상 그룹이 있어야 실행되므로 통합 감시 완료로 간주하지 않음. | [scripts/power-all.ps1](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-infra/infra/scripts/power-all.ps1), [scripts/deploy.ps1](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-infra/infra/scripts/deploy.ps1) |
| 5.6 | 보존·복구 절차와 비용 기록 문서 확인. EBS 선언·서비스 데이터 경로 설정이 실제 포맷·마운트·복원 성공을 보장하지 않음. | [docs/operations-recovery.md](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-infra/docs/operations-recovery.md), [operations/daily-usage.md](https://github.com/encore-ai-campus/mlo-01-p3-team2/blob/8c27c107b53ee9573ba93af2d2e51ccb8af30c2b/aws-infra/docs/operations/daily-usage.md) |

## 후속 확인의 범위

- 커뮤니티: 작성자 수정·삭제 정책과 개인 쪽지의 실제 활성화 여부.
- 학습: 운영 문제은행 등록 수량·내용 품질·전체 기능 재검증. 데이터 집계만으로 정답·해설 품질을 판정하지 않음.
- 광고: 이슈 #93·#94 작업의 별도 브랜치·운영 반영 여부와 캠퍼스 표시부터 최종 과금까지의 통합 결과.
- 파이프라인: 실제 Raw 구독 설정·장애 복구 및 전체 구간 대조. 이슈 #80의 포인트 31건 검증은 당시 작성자의 운영 기록.
- 인프라: 현재 계정의 실제 자원·마운트·클러스터·Monitoring·백업 복원·비용 조회 상태. 예전 설치 시험을 현재 환경 결과로 확대하지 않음.

이 항목들은 [WBS 5절](./wbs.md#5-추가-확인-작업)에 연결했으며, 미확인을 미구현이나 완료로 단정하지 않았다.

