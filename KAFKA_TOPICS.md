# 플랫폼 Kafka 토픽 정리

최종 갱신: **2026-10-15** · 대상: **프론트·백엔드 분리 플랫폼 (`frontend/`, `backend/`)**

현재 **7개 토픽, 15개 이벤트**의 생성·Outbox 저장·Kafka 전송 코드가 구현된 상태임. 학습 답안과 실제 포인트 지급이 연결되어 있으며, 이동 이벤트도 위치 체크포인트와 함께 DB Outbox에 저장하도록 변경됨.

위 개수는 코드에 정의된 발행 구성을 뜻함. 실제 Kafka 전송은 브로커 설정과 발행기 실행이 필요함. `KAFKA_BOOTSTRAP_SERVERS`가 비어 있으면 이동·REST·LEARNING을 포함한 모든 이벤트가 발생 시 Outbox에 대기함.

## 1. 토픽과 이벤트

| 토픽 | 이벤트 | 수집 내용 |
|---|---|---|
| `raw.account` | `session_started`, `session_ended` | 로그인 세션 시작·종료 |
| `raw.chat` | `chat_sent` | 서버가 받아들인 채팅 |
| `raw.board` | `post_created`, `post_updated`, `post_deleted`, `post_read` | 커뮤니티 게시글 작성·수정·삭제·상세 조회 |
| `raw.comment` | `comment_created`, `comment_updated`, `comment_deleted` | 댓글·대댓글 작성·수정·삭제 |
| `raw.content_usage` | `content_open_requested`, `quiz_answered` | 게임·심리 테스트·Python·SQL 학습 열기 요청, 객관식·빈칸 답안 채점 결과 |
| `raw.movement` | `movement_observed`, `floor_transferred` | 변경된 최신 위치를 약 5초마다 저장한 체크포인트·층 전환 |
| `raw.points` | `point_granted` | 정답에 대한 실제 지급 내역과 지급 직후 잔액 |

포인트 사용·광고 입찰 이벤트는 현재 Raw 범위에서 제외함. 찌르기 효과와 보유 포인트·내역 조회도 새 Raw 이벤트를 만들지 않음. 유튜브 홈페이지 팝업도 새 Raw 이벤트를 추가하지 않으며 기존 7개 토픽·15개 이벤트·메시지 계약을 유지함.

이동 토픽명은 `raw.movement`이며, `movement_observed`는 해당 토픽에 들어가는 이벤트명임.

## 2. 공통 메시지 구조

- **Kafka Key:** `user_uuid`
- **Kafka Value:** UTF-8 JSON
- 로그는 JSON 형식으로 생성하며, 별도 `.json` 파일은 생성하지 않음.

| 구분 | 필드 | 의미 |
|---|---|---|
| 최상위 | `event_uuid` | 발생한 이벤트 한 건의 고유 UUIDv4 |
| `raw_manifest` | `schema_version` | `quiz_answered`는 `"1.1"`, 나머지는 `"1.0"` |
| 〃 | `event_type` | 이벤트 종류 |
| 〃 | `occurred_at` | 서버 발생 시간. UTC·밀리초 포함 |
| 〃 | `source` | 발생 서버. 기본값 `"platform_server_1"` |
| 〃 | `fingerprint_algorithm` | 현재 `"xxh3_64"` |
| 〃 | `fingerprint` | `raw_data`로 계산한 16자리 해시 |
| `raw_data` | `user_uuid` | 회원 고유 ID |
| 〃 | `session_uuid` | 로그인 세션 고유 ID |
| 〃 | `class_group_uuid` | 선택한 MLO·SKN 기수의 ID |

모든 이벤트의 `raw_data`에는 회원·세션·기수 ID가 공통으로 들어감. UUID는 소문자·하이픈을 포함한 UUIDv4 형식임.

`event_uuid`는 발생할 때마다 새로 생성하고, 전송 재시도 시에는 기존 값을 유지함. 소비자는 이를 기준으로 중복 제거 가능함.

## 3. 이벤트별 추가 필드

아래 필드는 공통 `raw_data`에 추가됨.

| 이벤트 | 추가 필드 |
|---|---|
| `session_started` | 추가 없음 |
| `session_ended` | `end_reason` |
| `chat_sent` | `message_uuid`, `channel_code`, `floor_uuid` |
| `post_created`, `post_updated`, `post_deleted`, `post_read` | `post_uuid`, `revision`, `zone_uuid` |
| `comment_created`, `comment_updated`, `comment_deleted` | `comment_uuid`, `post_uuid`, `parent_comment_uuid`, `revision` |
| `content_open_requested` | `content_uuid`, `category_uuid`, `domain`, `content_kind`, `zone_uuid`, `action` |
| `quiz_answered` | `attempt_uuid`, `question_uuid`, `content_uuid`, `question_type`, `choice_uuid`, `is_correct` |
| `point_granted` | `ledger_uuid`, `attempt_uuid`, `delta`, `balance_after` |
| `movement_observed` | `floor_uuid`, `zone_uuid`, `x`, `y`, `input_kind` |
| `floor_transferred` | `from_floor_uuid`, `to_floor_uuid`, `zone_uuid` |

**현재 값과 수집 기준**

- `end_reason`: 직접 로그아웃은 `"LOGOUT"`, 세션 만료는 `"SESSION_EXPIRED"`로 기록함. 웹소켓 연결 종료만으로 로그인 세션을 종료하지 않음.
- `channel_code`: 현재 `"GLOBAL"` 사용함.
- `revision`: 1부터 시작하며 수정·삭제 시 증가함.
- `content_kind`: 게임·심리 테스트는 `"EXTERNAL_LINK"`, Python·SQL은 `"QUIZ"`로 기록함.
- `action`: 현재 `"OPEN_REQUESTED"`로 기록함. 외부 사이트의 실제 로딩·게임 완료·테스트 완료를 의미하지 않음.
- `domain`: 게임·심리 테스트는 `"REST"`, Python·SQL 학습은 `"LEARNING"`임. `category_uuid`로 게임·심리 테스트·Python·SQL을 구분함. 각 게임과 학습 과목×문제 유형마다 고유한 `content_uuid` 사용함.
- `question_type`: `"MULTIPLE_CHOICE"` 또는 `"FILL_BLANK"`임. 객관식은 실제 선택한 보기의 `choice_uuid`를 기록하고, 빈칸은 반드시 `null`임. `is_correct`는 서버 채점 불리언임. 제출 원문·정답·해설·재전송용 요청 UUID는 Kafka에 넣지 않음.
- `delta`: 실제 지급한 양의 정수 포인트임. 기본 초급 20P·중급 50P·고급 80P임. `balance_after`는 그 지급 직후의 0 이상 정수 잔액임. 같은 `attempt_uuid`는 지급 원장 한 건만 생성 가능함.
- `input_kind`: 현재 `"KEYBOARD"`로 기록함.
- `x`, `y`: 맵 좌표임. 이동 Raw에는 방향 필드를 넣지 않음.
- `movement_observed`의 좌표는 실제 위치 DB에 저장한 값이며, `occurred_at`은 그 위치 변경을 서버가 관측한 시각임. 체크포인트 실행 시각이나 Kafka 전송 시각과 구분함.
- 게시글·이동·층 전환의 `zone_uuid`는 현재 `null`임. 콘텐츠 열기는 해당 부스 또는 1·2 강의실 구역 ID를 넣음.
- 일반 댓글의 `parent_comment_uuid`는 `null`, 대댓글은 부모 댓글의 UUIDv4를 넣음. 작성·수정·삭제 시 같은 부모 UUID를 유지함. 대댓글은 한 단계까지 지원함.

**댓글·대댓글 구분**

기존 `raw.comment`와 3개 이벤트를 그대로 사용함. 새 토픽·이벤트 종류 없이 이미 정의된 `parent_comment_uuid` 값으로 구분함. 공통 JSON 형식과 `schema_version: "1.0"`도 유지함.

```json
{
  "comment_uuid": "60ffcf07-04d0-4e5d-97d2-042877e18d3e",
  "post_uuid": "14ed0b9c-f2e3-4dc3-8527-5a769e530a3e",
  "parent_comment_uuid": "ca890a36-e6ee-4609-8b4f-090df3f79a24",
  "revision": 1
}
```

위는 대댓글의 이벤트별 추가 필드 예시이며 공통 `user_uuid`, `session_uuid`, `class_group_uuid`는 생략함. 일반 댓글은 `parent_comment_uuid`만 `null`임. 부모 댓글을 삭제해도 남은 대댓글의 부모 참조는 유지함. 댓글 본문은 계속 Raw에 넣지 않음.

**콘텐츠 분류**

| 상위 분류 (`domain`) | 하위 카테고리 | 현재 콘텐츠 |
|---|---|---|
| `REST` | `game` — 게임 | 오목, 전쟁시대, 아빠와 나, 지뢰찾기, 사과게임, 버블슈터, 수박게임, 후레시맨, 테트리스, 세상에서 가장 어려운 게임, 죽림고수, 검 강화하기, 황새와 오래 걷기, 아이작, 팔라독, 솔리테어 |
| `REST` | `psychology` — 심리 테스트 | 심심테스트 |
| `LEARNING` | `python` — Python 학습 | Python 객관식, Python 코드 빈칸 |
| `LEARNING` | `sql` — SQL 학습 | SQL 객관식, SQL 코드 빈칸 |

콘텐츠 열기 이벤트는 모두 `raw.content_usage`로 발행하고 `domain`·`category_uuid`로 분류함. 학습 맵의 유형별 영역에서 E로 문제 팝업을 열 때 기록함. 난이도 선택·개별 문항 조회 때 같은 열기 로그를 추가하지 않음. `session_uuid`는 로그인 세션 UUID이며 내부 학습 세션의 정수 ID와 다름.

게임은 총 16개이며 추가 8종도 기존 `raw.content_usage / content_open_requested`와 REST/game 분류를 사용함. `0008_add_requested_games` 마이그레이션은 콘텐츠 UUIDv4를 고정해 신규 기준정보를 등록하고 기존 항목은 보존함.

학습 콘텐츠 ID는 난이도나 출제 순서에 따라 바뀌지 않음. 개별 문제·보기에 UUIDv4를 부여하고 기존 정수 PK도 유지함. 새 환경·기존 환경은 마이그레이션으로 기준정보를 준비함.

## 4. 학습 답안·포인트 흐름

1. 클라이언트가 답안별 `submission_request_uuid`를 발급하고 재시도까지 유지함. HTTP API는 UUIDv4를 필수로 받음. 객관식 화면은 실제 `choice_uuid`도 함께 보냄.
2. 서버가 소유자·문제·선택지·3회 제한을 검증하고 직접 채점함. 유효한 정답·오답 각각 `quiz_answered` 한 건 생성함. 거부된 요청은 답안 로그를 만들지 않음.
3. 정답이면 난이도 배점으로 지갑 적립·지급 원장·`point_granted` 생성함. 빈칸도 같은 배점임. 오답은 포인트 이벤트 없음. 배점을 0으로 설정한 경우에도 0P 지급 이벤트는 만들지 않음.
4. 답안·성적·지갑·원장·두 Outbox 이벤트·응답 스냅샷을 **같은 운영 DB의 한 트랜잭션**으로 확정함. 중간 실패 시 모두 취소함. Kafka ACK를 기다리면서 채점하지 않음.
5. 동일 사용자·요청 UUID·답안은 이전 응답을 반환하며 답안·원장·이벤트를 중복 생성하지 않음. 같은 요청 UUID를 다른 답안이나 학습 세션에 재사용하면 409임. 동시 제출도 사용자별로 직렬화함.

재시도 응답의 `balance_after`는 원래 지급 시점의 값임. 최신 잔액은 별도 지갑 조회 API로 확인함. 다른 사용자는 같은 요청 UUID를 사용해도 서로 별도 요청임. 새 학습에서 같은 문제를 다시 맞히면 새 시도이며 다시 적립됨. 통과 여부와 별개로 정답 제출 시 지급됨.

기존 미연동 답안의 정수 ID·`attempt_uuid`·응답 스냅샷은 보존함. 이전 답안에 소급 지급하거나 Kafka 로그를 새로 만들지 않음. 기존 계정 지갑은 0P로 시작함. 운영 보상 정책 변경 시 `backend/.env`의 `LEARNING_POINTS_BEGINNER`, `LEARNING_POINTS_INTERMEDIATE`, `LEARNING_POINTS_ADVANCED` 변경 후 서버 재시작함. 이미 지급한 내역과 재시도 결과는 바뀌지 않음.

**빈칸 계약 확장**

기존 DRD의 객관식 전용 `quiz_answered 1.0`은 수신측에서 유지함. 새 발행자는 객관식·빈칸 모두 `1.1`을 사용함. 추가 필드는 `question_type`이며 `choice_uuid`는 빈칸에서만 `null` 허용함. `point_granted`와 다른 이벤트는 `1.0` 유지함.

이 프로젝트는 프론트·백엔드로 나뉜 발행 측 프로젝트이며, 수신 서비스는 별도로 관리함. 새 메시지 계약은 `quiz_answered 1.1`임. 저장소의 수신 파이프라인은 팀원이 별도로 관리하며 이 분리 PR에서 교체하지 않음. 수신 서비스에서 `quiz_answered 1.1`, 빈칸의 nullable `choice_uuid`, `raw.points` 구독을 지원하도록 반영한 뒤 실제 Kafka 발행을 켜야 함. 실 Kafka·MongoDB 송수신 검증은 팀 서버에서 별도로 필요함.

**객관식 답안 예시 — 이벤트별 `raw_data` 추가 필드**

```json
{
  "attempt_uuid": "98fc94d3-a44f-47e2-b584-bbb8af2b4638",
  "question_uuid": "ec543f6c-fabe-48fb-8753-6c7c7e1ce188",
  "content_uuid": "0a2e7beb-e01b-4c0f-b0b6-85dbe00452d6",
  "question_type": "MULTIPLE_CHOICE",
  "choice_uuid": "d9c8bf8b-1aa5-4d45-9f15-78a7a486191a",
  "is_correct": true
}
```

**빈칸 답안 예시**

```json
{
  "attempt_uuid": "56fd1d9c-b1ae-4a3d-9c4a-b86811f0ab25",
  "question_uuid": "8b59b8ad-7d8d-46f4-838b-9c3a1ca0f91a",
  "content_uuid": "424c4db5-0a92-42e2-a009-23c675c2b889",
  "question_type": "FILL_BLANK",
  "choice_uuid": null,
  "is_correct": true
}
```

**위 빈칸의 지급 예시 — `raw.points`**

```json
{
  "ledger_uuid": "9c2c2877-e9d4-4e30-8474-bd8f705b8ac7",
  "attempt_uuid": "56fd1d9c-b1ae-4a3d-9c4a-b86811f0ab25",
  "delta": 20,
  "balance_after": 70
}
```

예시의 문제·보기·시도·원장 UUID는 설명용임. 실제로는 발급·저장한 UUID를 사용함. 위 필드에 공통 회원·로그인 세션·기수 UUID가 추가되고 최상위 `event_uuid`, `raw_manifest`, `raw_data`로 감싸 전송됨. 답안과 지급은 같은 `attempt_uuid`로 연결하되 각기 다른 `event_uuid`를 사용함. 서로 다른 토픽 간 도착 순서는 보장되지 않으므로 수신측은 연결 키로 합쳐야 함.

채팅 원문·닉네임, 게시글 제목·본문, 댓글 본문은 Kafka Raw에 포함하지 않음. 채팅 원문은 운영 DB에 30일 보관함.

## 5. 이동 로그 수집 흐름

매 이동마다 이벤트를 메모리 큐에 넣던 경로를 제거하고, 기존 위치 저장 체크포인트를 재사용함. 실시간 화면 이동과 다른 사용자에게 보내는 웹소켓 동기화는 계속 유지함.

1. 서버가 받아들인 위치 정보가 바뀌면 `position_dirty=True`로 표시하고 최신 위치와 관측 시각을 메모리에 유지함.
2. 일반 체크포인트는 마지막 체크포인트로부터 약 5초가 지났고 `position_dirty=True`인 경우에만 저장함. 변경 표시가 없는 사용자는 위치 저장·Outbox 기록을 건너뜀. 이를 위해 모든 사용자의 좌표를 DB에서 다시 조회하지 않음.
3. 사용자 위치(`last_position`, `last_position_at`)를 갱신하고 이전 저장 위치와 층 또는 x/y가 달라졌으면 `movement_observed` 한 건을 **같은 DB 트랜잭션**으로 Outbox에 기록함. 방향만 바뀌면 복원용 방향만 저장하고 이동 이벤트는 생성하지 않음. 여러 이동은 저장 시점의 최신 위치 한 건으로 모음.
4. 저장이 성공하면 처리한 위치의 변경 표시를 해제함. 저장 중 더 최신 위치가 들어오면 변경 표시를 유지해서 다음 체크포인트에서 저장함. Outbox 기록에 실패하면 위치 갱신도 취소하고 다음 체크포인트에서 재시도함.
5. 백그라운드 발행기가 Outbox의 이벤트를 `raw.movement`로 전송함. **5초는 위치 기록 간격이며 실제 Kafka 전송 시각을 보장하는 간격은 아님.**

`position_dirty`는 현재 `moving=True`인지가 아니라 **지난 저장 이후 위치 정보가 바뀌었는지**를 나타냄. 따라서 잠깐 움직였다가 멈춘 사용자도 마지막 변경 위치를 한 번 저장하고, 그 뒤 변경이 없으면 기록하지 않음. 위치 정보에는 층·좌표·방향이 포함되지만 Kafka Raw에는 방향 필드를 넣지 않음. 정지 또는 방향 변경만으로 이동 이벤트가 추가되지 않음.

**최종 위치와 층 전환 처리**

- 층 이동·웹소켓 접속 종료·명시적 로그아웃·세션 만료에는 미저장 최종 위치를 5초 제한을 기다리지 않고 저장함.
- 층 이동에는 위치 갱신·`movement_observed`·`floor_transferred`를 같은 트랜잭션으로 기록함.
- 이미 저장한 관측 시각과 같거나 더 오래된 좌표는 위치를 덮어쓰지 않고 이동 이벤트도 추가하지 않음. 오래된 탭이나 중복 종료 처리로 인한 중복 기록을 방지함.
- 일반 주기 확인은 5초 제한을 유지함. 위치를 갱신하지 않은 사용자에 대한 이동 이벤트는 생성하지 않음.

이동 토픽·이벤트 필드·스키마 `1.0`은 유지함. 수집 빈도와 저장·재시도 방식만 변경함.

## 6. 저장·전송 방식

| 구분 | 처리 방식 | 실패 처리 |
|---|---|---|
| `movement_observed` | 변경된 위치의 체크포인트 → 위치 DB 갱신 + Outbox 저장 → Kafka | 위치와 Outbox를 함께 확정하고, 전송 실패 시 DB에 남겨두고 재시도 |
| 그 외 모든 이벤트 | DB Outbox → Kafka | DB에 남겨두고 재시도 |

주요 서비스 변경과 Outbox 기록을 같은 DB 트랜잭션으로 저장함. Kafka의 전송 성공 응답을 받은 뒤 전송 완료로 표시함.

저장 트랜잭션이 커밋되면 같은 프로세스의 발행기에 즉시 알림. 롤백된 기록은 알리지 않음. 빈 Outbox는 조회 간격을 0.25초부터 최대 5초까지 늘리며, 다른 프로세스가 기록한 이벤트도 주기 조회로 발견함. MySQL 발행기 스레드만 기본 60초 동안 연결 하나를 재사용하고, 연결 상태 확인·만료·오류·종료 시 정리함. 사용자 HTTP·WebSocket의 연결 정책과 이벤트 계약은 유지함.

Producer는 `acks=all`, `enable.idempotence=True`를 사용함. Kafka 전송 성공 직후 서버가 종료되면 같은 이벤트가 다시 전송될 수 있으므로, 소비자에서도 `event_uuid` 기준 중복 제거가 필요함.

로컬 개발 기본 DB는 SQLite이며 2026-10-15 기준 AWS 운영 Outbox는 MySQL에 저장함. Kafka 연결 정보가 없어도 이동 체크포인트를 포함한 모든 이벤트는 발생 시 Outbox에 기록됨. 브로커 주소가 없으면 실제 Kafka 전송은 시작하지 않고, 설정 후 발행기를 실행하면 기존 미발행 이벤트부터 전송함.

## 7. 설정·실행·검증

- 연결 정보는 `backend/.env`에서 설정함. 예시는 `backend/.env.example`에 있음.
- `KAFKA_BOOTSTRAP_SERVERS`가 발행기 시작에 필요하며, 인증을 사용하는 환경에서는 `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME`, `KAFKA_SASL_PASSWORD`도 설정함.
- 기본 출처는 `CAMPUS_RAW_SOURCE=platform_server_1`임.
- 빈 조회 최대 간격은 `CAMPUS_OUTBOX_IDLE_POLL_SECONDS=5`, MySQL 발행기 연결 재사용 수명은 `CAMPUS_OUTBOX_CONNECTION_MAX_AGE_SECONDS=60`으로 조정함. 변경 후 백엔드를 재시작함.
- `run-campus.py`와 `manage.py runserver` 모두 실제 서비스 프로세스에서 발행기를 시작함. 자동 재시작을 감시하는 부모 프로세스에서는 시작하지 않으며, 마이그레이션·검사·테스트 명령도 발행기를 시작하지 않음.
- 토픽 생성, 파티션·복제 수 설정과 수신 서비스 구독은 별도로 관리함. 토픽·이벤트 코드가 구현되었다는 사실과 실제 브로커 송수신 확인을 구분함.

2026-10-13 기준 검증: 이동 체크포인트·정지 사용자 제외·최종 위치·오래된 좌표 제외·Outbox 실패 시 전체 취소·전송 재시도와 기존 학습·포인트 기능을 포함한 **테스트 66개 통과**. DB 스키마 변경 없이 기존 Outbox를 사용함. 이 검증은 실제 브로커 연결 검증과 별개임.

2026-10-14 AWS 운영 환경에서 브로커 3대와 7개 Raw 토픽을 확인하고, 기존 대기 로그 716건의 ACK 발행과 실제 브로커 메시지 조회를 검증함. 이후에도 신규 로그 발행이 이어지는 것을 확인함. 이 확인은 플랫폼 발행 측까지이며 수신 서비스의 정제·집계 완료를 뜻하지 않음. 2026-10-15 AWS의 MySQL Outbox로 이전하고 기존 데이터·UUID·발행 상태를 보존함. Kafka 3대·7개 토픽·실제 메시지 조회와 대기 0건을 재확인함. 좌표가 포함된 `raw_data`·`payload_json`은 숫자 원문과 fingerprint를 유지하도록 MySQL에서 LONGTEXT + JSON_VALID 검사로 저장함. Django와 Kafka에서는 기존 JSON 객체로 사용하며 토픽·이벤트·스키마 버전은 변경하지 않음. 연결 주소·인증값은 운영 `.env`에서 관리하고 저장소에 넣지 않음.

백엔드 폴더에서 설정과 마이그레이션 파일 상태를 확인할 수 있음.

```powershell
cd C:\3rd-pr-f\backend
python manage.py check
python manage.py makemigrations --check --dry-run
```

실행 방법은 [RUN_GUIDE.md](RUN_GUIDE.md)를 참고함.

## 8. 주요 구현 위치

| 파일 | 역할 |
|---|---|
| [backend/eventing/events.py](backend/eventing/events.py) | 토픽 매핑, 필드 검증, 메시지 구조, Outbox 기록 |
| [backend/campus/consumers.py](backend/campus/consumers.py) | 변경 표시와 약 5초 체크포인트, 실시간 이동·최종 위치 처리 |
| [backend/campus/positions.py](backend/campus/positions.py) | 위치 갱신과 이동 Outbox를 같은 트랜잭션으로 저장 |
| [backend/eventing/publisher.py](backend/eventing/publisher.py) | Outbox 전송, Kafka ACK 확인, 실패 재시도 |
| [backend/learning/services.py](backend/learning/services.py) | 학습 열기·답안 채점·포인트·Outbox를 연결 |
| [backend/learning/point_integration.py](backend/learning/point_integration.py) | 실제 지갑 적립과 지급 원장 |
| [backend/accounts/views.py](backend/accounts/views.py), [backend/accounts/session_policy.py](backend/accounts/session_policy.py) | 로그아웃·세션 만료의 최종 위치 저장 |
