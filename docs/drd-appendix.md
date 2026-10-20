# 데이터 요구사항 정의서 — 부록

> 작성일: 2026-10-17
> 본문: [drd.md](drd.md)

---

# 부록 A. 플랫폼 운영 DB

플랫폼 서버(Django)의 테이블이다. 테이블 이름은 Django 기본 규칙(`<앱>_<모델>`)을 따른다. 사용자를 가리키는 FK는 대부분 `auth_user.id`(정수)이고, 포인트 지갑·원장만 `accounts_profile.user_uuid`를 가리킨다.

## A.1 계정·접속

**`auth_user`** — 로그인 계정(Django 기본 테이블)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `id` | int | | PK, 자동 증가 | 내부 정수 키. 행동 데이터에는 쓰지 않는다 |
| `username` | varchar(150) | | UNIQUE | 로그인 ID |
| `password` | varchar(128) | | | 비밀번호 해시(원문 저장 안 함) |
| `is_active` | bool | | | 계정 사용 여부. 끄면 로그인·기존 세션·실시간 접속에서 빠진다(계정 삭제 방식, 본문 DR-26) |
| `is_staff` | bool | | | 운영자 여부(공지 작성 등) |
| `is_superuser` | bool | | | 최고 관리자 여부 |
| `date_joined` | datetime(6) | | | 가입 시각 |
| `last_login` | datetime(6) | N | | 마지막 로그인 시각 |
| `first_name`·`last_name`·`email` | varchar | | | 쓰지 않음(빈 값) |

**`django_session`** — 로그인 세션(Django 기본 테이블). 브라우저 쿠키 `campus_sessionid`가 이 행을 찾는다.

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `session_key` | varchar(40) | | PK | 쿠키 값 |
| `session_data` | longtext | | | 세션 데이터. `platform_session_uuid`(접속 이력 ID)·로그인 시작 시각·마지막 활동 시각을 담는다 |
| `expire_date` | datetime(6) | | INDEX | 만료 시각 |

**`accounts_profile`** — 사용자 프로필과 가명 식별자

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `id` | bigint | | PK, 자동 증가 | |
| `user_uuid` | UUID | | UNIQUE, 기본 UUIDv4 | **행동 데이터의 사용자 키**(가명). 모든 이벤트의 `user_uuid` |
| `user_id` | int | | FK → `auth_user` CASCADE, UNIQUE(1:1) | |
| `nickname` | varchar(20) | | | 화면 표시 이름 |
| `avatar` | varchar(8) | | 기본 `male-1` | `male-1`·`male-2`·`female-1`·`female-2` |
| `cohort` | varchar(6) | | 기본 `""` | 소속 기수 코드(`mlo-1`·`mlo-2`·`mlo-3`·`skn-34`·`skn-36`·`aio-4`) |
| `setup_complete` | bool | | 기본 True(가입 시 False) | 첫 설정 완료 여부 |
| `guide_completed` | bool | | 기본 False | 안내 완료 여부 |
| `last_position` | JSON | N | | 재접속 위치 `{floor, x, y, dir}`(`floor`는 층 코드) |
| `last_position_at` | datetime(6) | N | | 위치를 관측한 시각. 더 새 관측일 때만 덮어쓴다 |

**`accounts_activelogin`** — 한 계정 한 세션 규칙

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `user_id` | int | | PK, FK → `auth_user` CASCADE | |
| `session_key` | varchar(40) | | UNIQUE | 가장 최근 로그인의 세션 키. 이전 세션은 이 값과 다르면 거부된다 |
| `updated_at` | datetime(6) | | | |

**`eventing_platformsession`** — 접속 이력(로그인 1회 = 1행)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `session_uuid` | UUID | | PK | 이벤트의 `session_uuid` |
| `user_id` | int | | FK → `auth_user` CASCADE | |
| `started_at` | datetime(6) | | | 로그인 시각 |
| `ended_at` | datetime(6) | N | | 종료를 확정한 시각(만료는 서버가 감지한 시각) |
| `end_reason` | varchar(24) | N | | `LOGOUT` · `SESSION_EXPIRED` |
| `last_seen_at` | datetime(6) | | | 마지막으로 접속을 확인한 시각(15초 간격 갱신) |

## A.2 기준정보

**`eventing_classgroup`** — 소속 반(기수)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `class_group_uuid` | UUID | | PK | 이벤트의 `class_group_uuid` |
| `code` | varchar(24) | | UNIQUE | 기수 코드 |
| `name` | varchar(80) | | | 표시 이름 |
| `status` | varchar(16) | | 기본 `ACTIVE` | |

**`eventing_mapfloor`** — 층

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `floor_uuid` | UUID | | PK | |
| `code` | varchar(24) | | UNIQUE | `campus`(18층) · `rooftop`(옥상) |
| `name` | varchar(80) | | | |

**`eventing_mapzone`** — 층 안의 구역

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `zone_uuid` | UUID | | PK | |
| `floor_id` | UUID | | FK → `eventing_mapfloor` PROTECT | |
| `code` | varchar(48) | | UNIQUE(`floor_id`, `code`) | |
| `zone_type` | varchar(24) | | | |
| `name` | varchar(100) | | | |

**`eventing_contentcategory`** — 콘텐츠 분류(계층)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `category_uuid` | UUID | | PK | |
| `code` | varchar(48) | | UNIQUE | |
| `parent_id` | UUID | N | FK → 자기 자신 PROTECT | 상위 분류 |
| `domain` | varchar(16) | | | `LEARNING`(학습) · `REST`(휴식) |
| `name` | varchar(100) | | | |

**`eventing_contentitem`** — 콘텐츠(외부 링크 또는 문제 묶음)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `content_uuid` | UUID | | PK | |
| `code` | varchar(48) | | UNIQUE | 주소에 쓰는 코드 |
| `category_id` | UUID | | FK → `eventing_contentcategory` PROTECT | |
| `content_kind` | varchar(24) | | | `EXTERNAL_LINK` · `QUIZ` |
| `title` | varchar(120) | | | |
| `external_url` | varchar(500) | N | | 외부 링크 주소 |
| `zone_id` | UUID | N | FK → `eventing_mapzone` PROTECT | 콘텐츠가 놓인 구역 |
| `status` | varchar(16) | | 기본 `ACTIVE` | `ACTIVE` · `HIDDEN` |
| `published_at` | datetime(6) | N | | |
| `created_at`·`updated_at` | datetime(6) | | | |

**초기 기준정보**(마이그레이션으로 넣는 고정 UUIDv4 값): 반 7개(`mlo-1`·`mlo-2`·`mlo-3`·`skn-34`·`skn-36`·`aio-4`·`unassigned`), 층 2개(`campus`·`rooftop`), 구역 5개(`class34-board`·`psych-booth`·`game-booth`·`python-classroom`·`sql-classroom`), 분류 4개(`game`·`psychology`는 휴식, `python`·`sql`은 학습), 콘텐츠 21개(게임 16·심리 테스트 1은 외부 링크, 문제 묶음 4).

## A.3 커뮤니티·채팅

**`community_post`** — 게시글

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `id` | bigint | | PK, 자동 증가 | |
| `post_uuid` | UUID | | UNIQUE | 이벤트의 `post_uuid` |
| `author_id` | int | | FK → `auth_user` CASCADE | |
| `category` | varchar(12) | | INDEX(`category`, `created_at` 내림차순) | `notice`·`free`·`it`·`project`·`career`·`study`·`question` |
| `title` | varchar(140) | | | |
| `body` | longtext | | | 본문(화면에서 20,000자 제한). **이벤트에는 싣지 않는다** |
| `revision` | int unsigned | | 기본 1 | 수정·삭제마다 1 증가(낙관적 잠금) |
| `created_at`·`updated_at` | datetime(6) | | | |
| `deleted_at` | datetime(6) | N | | 소프트 삭제 시각 |

**`community_comment`** — 댓글·대댓글(1단계)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `id` | bigint | | PK, 자동 증가 | |
| `comment_uuid` | UUID | | UNIQUE | |
| `post_id` | bigint | | FK → `community_post` CASCADE | |
| `parent_comment_uuid` | UUID | N | FK → `community_comment.comment_uuid` CASCADE | 대댓글이면 부모 댓글 |
| `author_id` | int | | FK → `auth_user` CASCADE | |
| `body` | longtext | | | 본문(화면에서 2,000자 제한). 이벤트에는 싣지 않는다 |
| `revision` | int unsigned | | 기본 1 | |
| `created_at`·`updated_at` | datetime(6) | | | |
| `deleted_at` | datetime(6) | N | | 소프트 삭제 시각 |

**`eventing_chatmessage`** — 전체 채팅 본문(운영 확인용, 30일 보관)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `message_uuid` | UUID | | PK | |
| `user_id` | int | | FK → `auth_user` CASCADE | |
| `channel_code` | varchar(16) | | 기본 `GLOBAL` | |
| `body` | varchar(200) | | | 본문(1~200자). 이벤트에는 싣지 않는다 |
| `floor_id` | UUID | N | FK → `eventing_mapfloor` SET_NULL | 보낼 때 있던 층 |
| `sent_at` | datetime(6) | | | |
| `expires_at` | datetime(6) | | INDEX | `sent_at` + 30일. 매일 정리 작업이 지난 행을 지운다 |

**`direct_messages_conversation`**·**`direct_messages_message`** — 1:1 쪽지(기능 스위치로 켜고 끈다, 기본 꺼짐)

| 테이블 | 컬럼 | 키·제약 |
|---|---|---|
| `direct_messages_conversation` | `id` UUID, `first_user_id`, `second_user_id`, `updated_at` | PK `id`; FK 둘 다 → `auth_user` CASCADE; UNIQUE(`first_user_id`, `second_user_id`); CHECK `first_user_id < second_user_id`; INDEX(`updated_at`) |
| `direct_messages_message` | `id` UUID, `conversation_id`, `sender_id`, `recipient_id`, `request_id` UUID, `body` longtext(2,000자), `created_at`, `read_at`(N) | PK `id`; FK 모두 CASCADE; UNIQUE(`sender_id`, `request_id`)(같은 요청의 재전송 방지); INDEX(`conversation_id`, `created_at`), INDEX(`recipient_id`, `read_at`) |

## A.4 학습·포인트

**`learning_question`** — 문제은행

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `question_id` | bigint | | PK, 자동 증가 | |
| `question_uuid` | UUID | | UNIQUE | 이벤트의 `question_uuid` |
| `subject` | varchar(10) | | CHECK, 기본 `python` | `python` · `sql` |
| `question_code` | varchar(32) | N | UNIQUE(`subject`, `question_code`) | 문제 원본 코드 |
| `question_type` | varchar(20) | | CHECK | `multiple_choice`(4지선다) · `fill_blank`(코드 빈칸) |
| `difficulty` | varchar(20) | | CHECK | `beginner` · `intermediate` · `advanced` |
| `category` | varchar(40) | | | 단원 |
| `question_text` | longtext | | | 문제 |
| `code_snippet` | longtext | N | | 코드 |
| `correct_answer` | longtext | | | 정답 텍스트(서버만 안다) |
| `explanation` | longtext | | | 해설 |
| `is_active` | bool | | 기본 True | 출제 여부 |
| `created_at` | datetime(6) | | | |

INDEX(`subject`, `difficulty`, `question_type`, `is_active`)로 출제 풀을 고른다. 한 번 출제한 문제와 보기는 고치거나 지울 수 없다(애플리케이션 규칙).

**`learning_questionchoice`** — 객관식 보기

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `choice_id` | bigint | | PK | |
| `choice_uuid` | UUID | | UNIQUE | 이벤트의 `choice_uuid` |
| `question_id` | bigint | | FK → `learning_question` CASCADE | |
| `choice_no` | smallint unsigned | | UNIQUE(`question_id`, `choice_no`), CHECK 1~4 | |
| `choice_text` | longtext | | | |

**`learning_learningsession`** — 학습 회차(문제 10개 묶음)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `session_id` | bigint | | PK | |
| `user_id` | int | | FK → `auth_user` PROTECT | |
| `subject`·`question_type`·`difficulty` | varchar | | CHECK | 회차 조건 |
| `started_at` | datetime(6) | | | |
| `completed_at` | datetime(6) | N | | |
| `total_questions` | smallint unsigned | | 기본 10, CHECK 1~10 | |
| `correct_count` | smallint unsigned | | 기본 0, CHECK 0 ≤ 값 ≤ `total_questions` | |

**`learning_sessionquestion`** — 회차에 출제된 문제

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `session_question_id` | bigint | | PK | |
| `session_id` | bigint | | FK → `learning_learningsession` PROTECT; UNIQUE(`session_id`, `question_id`) | |
| `question_id` | bigint | | FK → `learning_question` PROTECT | |
| `question_order` | smallint unsigned | | UNIQUE(`session_id`, `question_order`), CHECK 1~10 | |
| `started_at` | datetime(6) | N | | 문제를 연 시각(열어야 답을 낼 수 있다) |

**`learning_useranswer`** — 답안(추가 전용: 고치거나 지울 수 없다)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `answer_id` | bigint | | PK | |
| `attempt_uuid` | UUID | | UNIQUE | 이벤트의 `attempt_uuid` |
| `submission_request_uuid` | UUID | N | UNIQUE(`user_id`, `submission_request_uuid`) | 브라우저가 제출마다 만드는 멱등 키. 같은 요청의 재전송이면 기존 결과를 돌려준다 |
| `user_id` | int | | FK → `auth_user` PROTECT | |
| `platform_session_id` | UUID | N | FK → `eventing_platformsession` PROTECT | |
| `content_id` | UUID | N | FK → `eventing_contentitem` PROTECT | |
| `session_question_id` | bigint | | FK → `learning_sessionquestion` PROTECT; UNIQUE(`session_question_id`, `attempt_no`) | |
| `selected_choice_id` | bigint | N | FK → `learning_questionchoice` PROTECT | 객관식에서 고른 보기 |
| `submitted_answer` | longtext | | | 제출 원문. 이벤트에는 싣지 않는다 |
| `is_correct` | bool | | | 서버 채점 결과 |
| `attempt_no` | smallint unsigned | | 기본 1, CHECK ≥ 1 | 문항당 최대 3회 |
| `response_snapshot` | json | | 기본 `{}` | 같은 요청을 다시 받았을 때 돌려줄 응답 |
| `answered_at` | datetime(6) | | | |

**`learning_pointwallet`** — 캠퍼스 포인트 잔액

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `user_uuid` | UUID | | PK, FK → `accounts_profile.user_uuid` PROTECT(1:1) | 가입할 때 0으로 만든다 |
| `balance` | bigint unsigned | | 기본 0, CHECK ≥ 0 | |
| `updated_at` | datetime(6) | | | |

**`learning_pointledger`** — 포인트 지급 원장(추가 전용)

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `ledger_uuid` | UUID | | PK | 이벤트의 `ledger_uuid` |
| `user_uuid` | UUID | | FK → `accounts_profile.user_uuid` PROTECT | |
| `attempt_uuid` | UUID | | **UNIQUE**, FK → `learning_useranswer.attempt_uuid` PROTECT | 정답 답안 하나에 지급 하나 |
| `delta` | bigint unsigned | | CHECK > 0 | 지급량(초급 20 · 중급 50 · 고급 80) |
| `balance_after` | bigint unsigned | | CHECK ≥ 0 | 지급 뒤 잔액 |
| `granted_at` | datetime(6) | | | |

## A.5 이벤트 발행 대기(outbox)

**`eventing_eventoutbox`**

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `event_uuid` | UUID | | PK | 이벤트 ID(UUIDv4). 다시 보내도 같은 값 |
| `event_type` | varchar(64) | | | 부록 B.2의 이벤트 유형 |
| `topic` | varchar(64) | | | 보낼 Kafka 토픽(`raw.*`) |
| `message_key` | UUID | | | Kafka key로 쓸 `user_uuid` |
| `raw_data` | JSON | | | 이벤트 데이터 |
| `occurred_at` | datetime(6) | | | 서버가 확정한 발생 시각 |
| `payload_json` | JSON | N | | 완성된 Raw 메시지(부록 B.1). 비어 있으면 발행기가 만든다 |
| `retry_count` | int unsigned | | 기본 0 | 발행 실패 횟수 |
| `created_at` | datetime(6) | | INDEX(`published_at`, `created_at`) | |
| `published_at` | datetime(6) | N | | Kafka 수신 확인(ACK)을 받은 시각. NULL이면 발행 대기 |

## A.6 광고 연동

플랫폼이 광고 서버에 보낸 요청과 노출 보고를 기록한다. 사용자 ID 대신 광고 전용 가명 `subject_id`(본문 §8.4)만 광고 서버로 보낸다.

**`ad_bridge_issueddecision`** — 광고 서버에서 받은 결정

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `decision_id` | UUID | | PK | 광고 서버가 발급한 결정 ID |
| `audience` | varchar(16) | | 기본 `individual`, CHECK | `individual`(개인 슬롯 — `subject_id` 필수) · `shared`(공용 슬롯 — `owner_id`·`subject_id` 모두 NULL) |
| `owner_id` | UUID | N | | 요청한 사용자의 `user_uuid`(FK 없음, 광고 서버로 보내지 않음) |
| `subject_id` | UUID | N | | 광고 전용 가명 |
| `slot_id` | UUID | | | 광고 자리 |
| `decided_at` | datetime(6) | | | |
| `has_ad` | bool | | | 광고가 나왔는지 |

**`ad_bridge_impression`** — 노출 보고와 재전송 상태

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `reaction_id` | UUID | | PK | 반응 ID(플랫폼이 만들어 광고 서버에 넘긴다) |
| `decision_id` | UUID | | FK → `ad_bridge_issueddecision` PROTECT; UNIQUE(`decision_id`, `owner_id`), UNIQUE(`decision_id`, `subject_id`) | 결정 하나에 사람마다 노출 하나 |
| `owner_id` | UUID | N | | 요청한 사용자의 `user_uuid` |
| `subject_id` | UUID | | | 광고 전용 가명 |
| `occurred_at` | varchar(64) | | | 노출 시각(보낸 문자열 그대로) |
| `delivery_state` | varchar | | 기본 `SENDING` | `SENDING` · `UNCONFIRMED`(재전송 대기) · `ACKNOWLEDGED` · `BLOCKED` |
| `status`·`reason_code` | varchar·text | N | | 광고 서버의 판정(`RECEIVED`·`ACCEPTED`·`REJECTED`)과 사유 |
| `attempts`·`next_attempt_at`·`last_error`·`last_http_status` | | | INDEX(`delivery_state`, `next_attempt_at`) | 재전송 관리 |
| `lease_token`·`lease_expires_at` | | | INDEX(`delivery_state`, `lease_expires_at`) | 동시 전송 방지(점유) |
| `request_id` | text | N | | 광고 서버 응답의 요청 ID |

**`ad_bridge_placementbatch`** — 자리 배치 묶음

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `key` | varchar(100) | | PK | `roof:<10초 회차>`(옥상 공용 광고) · `portal:<이동 ID>`(층 이동 화면의 개인 광고) |
| `owner_id` | UUID | N | | |
| `state` | varchar | | 기본 `PENDING` | `PENDING` · `READY` · `FAILED` |
| `payload` | json | | 기본 `[]` | 화면에 보낼 결정 목록 |
| `expires_at` | datetime(6) | | | |

## A.7 쓰지 않는 테이블

`raffle_event`·`raffle_entry`·`raffle_control`·`raffle_surveyconnection`·`raffle_surveyattempt`·`raffle_winnercontact`는 옥상 추첨 이벤트용이었다. 이 기능은 사용하지 않기로 확정해 코드에서 지웠고, 운영 DB에는 테이블만 남아 있다(본문 §12.2).

---

# 부록 B. 행동 이벤트 계약

## B.1 Raw 메시지(플랫폼 → `raw.*`)

Kafka value는 UTF-8 JSON 한 개다.

| 위치 | 필드 | 형식 | 규칙 |
|---|---|---|---|
| 최상위 | `event_uuid` | UUIDv4 | 이벤트 ID. 재시도·재발행·재처리 동안 같다 |
| `raw_manifest` | `schema_version` | 문자열 | `quiz_answered`는 `1.1`, 나머지는 `1.0` |
| | `event_type` | 문자열 | 소문자 snake(B.2) |
| | `occurred_at` | UTC 시각 | ISO-8601, 밀리초, `Z` |
| | `source` | 문자열 | 보낸 서버 이름 |
| | `fingerprint_algorithm` | 코드 | `xxh3_64` |
| | `fingerprint` | 16자리 소문자 16진수 | `raw_data`를 정규 JSON(키 사전순, 공백 없음, UTF-8, NaN 금지)으로 직렬화한 바이트의 xxh3_64 |
| `raw_data` 공통 | `user_uuid` | UUIDv4 | 사용자 가명 키. **Kafka key와 같아야 한다** |
| | `session_uuid` | UUIDv4 | 접속 이력 ID |
| | `class_group_uuid` | UUIDv4 | **이벤트 당시** 소속 반 |

Kafka key는 `user_uuid`(UTF-8), headers는 없다.

## B.2 이벤트 유형별 필드

공통 필드(B.1) 외에 아래 필드를 더한다. `N`은 null 허용이다. 이 목록 밖의 필드는 플랫폼이 넣지 않는다 — 발행 전에 필드 목록이 정확히 같은지 검사하고, 다르면 저장을 중단한다.

| 이벤트(버전) | 토픽 | 추가 필드 | 언제 만드는가 |
|---|---|---|---|
| `session_started`(1.0) | `raw.account` | 없음 | 로그인 성공(접속 이력과 같은 트랜잭션) |
| `session_ended`(1.0) | `raw.account` | `end_reason`(`LOGOUT`·`SESSION_EXPIRED`) | 로그아웃, 또는 세션 만료·다른 곳 로그인을 서버가 감지 |
| `chat_sent`(1.0) | `raw.chat` | `message_uuid`, `channel_code`(`GLOBAL`), `floor_uuid`(N) | 채팅 저장 |
| `post_created`·`post_updated`·`post_deleted`·`post_read`(1.0) | `raw.board` | `post_uuid`, `revision`(정수), `zone_uuid`(N, 지금은 항상 null) | 글 저장·수정·삭제, 상세 조회 응답 |
| `comment_created`·`comment_updated`·`comment_deleted`(1.0) | `raw.comment` | `comment_uuid`, `post_uuid`, `parent_comment_uuid`(N), `revision` | 댓글 저장·수정·삭제 |
| `content_open_requested`(1.0) | `raw.content_usage` | `content_uuid`, `category_uuid`, `domain`, `content_kind`, `zone_uuid`, `action`(`OPEN_REQUESTED`) | 콘텐츠 열기 요청을 받아 외부 주소로 보내기 전 |
| `quiz_answered`(1.1) | `raw.content_usage` | `attempt_uuid`, `question_uuid`, `content_uuid`, `question_type`(`MULTIPLE_CHOICE`·`FILL_BLANK`), `choice_uuid`(N), `is_correct` | 답안 저장·채점. 객관식이면 `choice_uuid` 필수, 빈칸이면 반드시 null |
| `point_granted`(1.0) | `raw.points` | `ledger_uuid`, `attempt_uuid`, `delta`(양의 정수), `balance_after` | 정답 답안의 포인트 지급(답안과 같은 트랜잭션) |
| `movement_observed`(1.0) | `raw.movement` | `floor_uuid`, `zone_uuid`(N, 지금은 항상 null), `x`, `y`(유한한 수, 0 이상), `input_kind`(지금은 `KEYBOARD`만) | 5초마다 위치를 저장할 때 좌표가 바뀌었으면. 층 이동·종료 때는 바로 |
| `floor_transferred`(1.0) | `raw.movement` | `from_floor_uuid`, `to_floor_uuid`, `zone_uuid`(N) | 층 이동 완료(위치 저장과 같은 트랜잭션) |

`quiz_answered` 1.0(`question_type` 없음, `choice_uuid` 필수)은 이전 계약이다. 수신 쪽은 1.0과 1.1을 모두 받는다.

**싣지 않는 값**: 비밀번호, 로그인 ID, 닉네임, 채팅·게시글·댓글 본문, 제출한 답안 원문, `submission_request_uuid`.

## B.3 Std 메시지(Std and Sinker → `standardized.*`)

| 위치 | 필드 | 규칙 |
|---|---|---|
| `std_manifest` | `event_type` | 대문자 상수(예: `QUIZ_ANSWERED`) |
| | `std_schema_version` | Raw의 `schema_version`과 같다 |
| | `status` | `SUCCESS`(발행되는 것은 이것뿐) · `FAIL` |
| | `processed_at` | 처리 시각(UTC, 밀리초, `Z`) |
| | `parser_version` | 표준화 규칙의 버전(`1.0.0`·`1.1.0`) |
| | `fingerprint_algorithm` | `xxh3_64` |
| | `fingerprint` | `std_data`의 지문(FAIL이면 null) |
| | `error_code` | 실패 코드(SUCCESS면 null) |
| `std_data` | `event_uuid` | Raw와 같은 이벤트 ID |
| | `occurred_at` | UTC `Z` 표기로 정규화(밀리초 또는 마이크로초) |
| | 공통 3개 + 이벤트별 필드 | 이름은 Raw와 같다. `x`·`y`만 실수로 바꾸고, 나머지 값은 그대로 옮긴다 |
| | `event_type`·`action` | 상수. 게시글·댓글은 `CREATE`·`UPDATE`·`DELETE`·`READ`, 콘텐츠 열기는 `OPEN_REQUESTED`, 포인트는 `GRANTED` |

Kafka key는 `std_data.user_uuid`, headers는 `event_type`·`std_schema_version`(manifest 값 복사)이다. Std에 들어가지 않는 Raw 값은 `schema_version`·`source`·Raw 지문이다.

## B.4 값 형식(도메인)

| 도메인 | 형식 | 허용값 |
|---|---|---|
| `UUID_V4_JSON` | UUIDv4, 소문자·하이픈 포함 | |
| `STRING` | 빈 문자열이 아닌 문자열 | |
| `UTC_INSTANT` | ISO-8601, UTC(오프셋 0) | |
| `FINGERPRINT` | `[0-9a-f]{16}` | |
| `ALGORITHM` | 코드 | `xxh3_64` |
| `INTEGER` | 64비트 정수(참·거짓과 `"3"` 같은 문자열은 거부) | |
| `POSITIVE_INT` | 0보다 큰 정수 | |
| `BOOLEAN` | 참·거짓 | |
| `FINITE_DOUBLE` | 유한한 수 | |
| `END_REASON` | 코드 | `LOGOUT`·`SESSION_EXPIRED` |
| `CHANNEL` | 코드 | `GLOBAL` |
| `CONTENT_DOMAIN` | 코드 | `LEARNING`·`REST` |
| `CONTENT_KIND` | 코드 | `EXTERNAL_LINK`·`QUIZ` |
| `CONTENT_OPEN_ACTION` | 코드 | `OPEN_REQUESTED` |
| `QUESTION_TYPE` | 코드 | `MULTIPLE_CHOICE`·`FILL_BLANK` |
| `INPUT_KIND` | 코드 | `KEYBOARD`·`MOUSE`·`SYSTEM` |
| `STD_STATUS` | 코드 | `SUCCESS`·`FAIL` |
| `STD_ACTION` | 코드 | `CREATE`·`UPDATE`·`DELETE`·`READ`·`OPEN_REQUESTED`·`GRANTED` |
| `ERROR_CODE` | 코드 | B.5 |

계약에 쓰는 필드 이름은 모두 표준 용어(43개)에 있어야 하고, 용어는 표준 단어(49개)를 밑줄로 이은 이름이다. 표준화 작업자는 시작할 때 이 관계를 검사한다.

## B.5 오류 코드

| 단계 | 코드 | 뜻 | 남는 곳 |
|---|---|---|---|
| Std and Sinker | `PARSE_ERROR` | JSON이 아니거나, 중복 키·NaN이 있거나, `event_uuid`가 UUIDv4가 아니거나, 저장할 수 없는 값 | `raw_wrong_receipts` |
| | `EVENT_UUID_CONFLICT` | 같은 `event_uuid`로 내용이 다른 Raw 메시지 | `raw_conflict_receipts` |
| | `UNSUPPORTED_VERSION` | 계약이 없는 (이벤트, 버전) | `std_logs`(FAIL) |
| | `MISSING_FIELD` | 필수 필드 없음 | `std_logs`(FAIL) |
| | `INVALID_VALUE` | 형식·허용값 위반, 토픽과 이벤트 불일치, Kafka key ≠ `user_uuid` | `std_logs`(FAIL) |
| | `RAW_CHECKSUM_MISMATCH` | Raw 지문 불일치 | `std_logs`(FAIL) |
| Spark | `INVALID_HEADER`·`HEADER_BODY_MISMATCH` | headers가 없거나 manifest와 다름 | `stream_processing_error` |
| | `UNSUPPORTED_SCHEMA`·`UNSUPPORTED_PARSER` | 등록되지 않은 (이벤트, 버전)·파서 버전 | 〃 |
| | `PARSE_ERROR`·`MISSING_FIELD`·`INVALID_VALUE` | 구조·필드·값 위반(모르는 필드도 거부) | 〃 |
| | `STD_CHECKSUM_MISMATCH` | Std 지문 불일치 | 〃 |
| | `KEY_MISMATCH` | Kafka key ≠ `std_data.user_uuid` | 〃 |
| | `RESULT_CONFLICT` | 같은 이벤트·같은 파서 순위인데 결과(지문)가 다름 | 〃(기존 행 유지) |

오류 기록에는 필드 이름만 남기고 원문 값은 남기지 않는다.

## B.6 MongoDB 보존 컬렉션(Std and Sinker)

| 컬렉션 | `_id` | 필드 | 쓰기 규칙 |
|---|---|---|---|
| `raw_logs` | `event_uuid` | `raw_manifest`, `raw_data`, `ingested_at`(받은 시각), `kafka_origin`{`topic`, `partition`, `offset`, `timestamp`, `key`, `headers`} | **처음 받은 Raw만** 저장(이미 있으면 덮어쓰지 않음). 같은 ID로 다시 오면 내용을 비교한다 |
| `std_logs` | `event_uuid` | `std_manifest`(B.3), `std_data`(FAIL이면 null), `error_detail`(필드 이름만) | 성공·실패 결과. 상위 파서 버전이 FAIL을 SUCCESS로 바꿀 때만 교체 |
| `raw_wrong_receipts` | `<토픽>:<파티션>:<오프셋>` | `kafka_origin`, `received_at`, `error_code`(`PARSE_ERROR`), `error_detail`, `raw_bytes`(받은 바이트) | 해석할 수 없는 입력 격리 |
| `raw_conflict_receipts` | `<토픽>:<파티션>:<오프셋>` | 위 필드 + `event_uuid`, `raw_manifest`, `raw_data` | 같은 ID의 다른 내용 격리 |

쓰기는 과반 확인(`w=majority`)을 받는다. `_id` 외의 색인과 만료(TTL) 설정은 없다.

---

# 부록 C. 분석 DB(Spark 적재)

모든 테이블은 InnoDB·utf8mb4다. UUID는 하이픈을 뺀 `CHAR(32)`(ascii, 이진 비교), 시각은 UTC `DATETIME(6)`이다. **FK는 두지 않는다** — 이벤트는 순서 없이 도착할 수 있고, 각 행은 이벤트 당시의 값을 그대로 보존한다.

## C.1 공통 컬럼(9개 분석 테이블 모두, 이 순서)

| 컬럼 | 타입 | N | 키 | 설명 |
|---|---|---|---|---|
| `event_uuid` | CHAR(32) | | **PK** | 이벤트 ID. 같은 이벤트는 한 행 |
| `occurred_at` | DATETIME(6) | | INDEX(`user_uuid`, `occurred_at`) | 발생 시각 |
| `user_uuid` | CHAR(32) | | | 사용자 가명 키 |
| `class_group_uuid` | CHAR(32) | | | 이벤트 당시 소속 반 |
| `session_uuid` | CHAR(32) | | | 접속 이력 ID |
| (테이블별 컬럼) | | | | C.2 |
| `parser_version` | VARCHAR(64) | | | 이 행을 만든 표준화 규칙 버전 |
| `parser_rank` | INT | | | 파서 버전의 순위(`1.0.0`=0, `1.1.0`=1) |
| `std_fingerprint` | CHAR(16) | | | Std 메시지 지문 |

## C.2 테이블별 컬럼

| 테이블 | 받는 이벤트 | 테이블별 컬럼(타입, N) |
|---|---|---|
| `account_activity_fact` | `SESSION_STARTED`·`SESSION_ENDED` | `event_type` VARCHAR(32); `end_reason` VARCHAR(32) N(시작이면 null) |
| `chat_activity_fact` | `CHAT_SENT` | `message_uuid` CHAR(32); `floor_uuid` CHAR(32) N |
| `post_activity_fact` | `POST_*` 4종 | `post_uuid` CHAR(32); `action` VARCHAR(32); `revision` BIGINT; `zone_uuid` CHAR(32) N |
| `comment_activity_fact` | `COMMENT_*` 3종 | `comment_uuid`·`post_uuid` CHAR(32); `parent_comment_uuid` CHAR(32) N; `action` VARCHAR(32); `revision` BIGINT |
| `content_activity_fact` | `CONTENT_OPEN_REQUESTED` | `content_uuid`·`category_uuid` CHAR(32); `domain`·`content_kind`·`action` VARCHAR(32); `zone_uuid` CHAR(32) |
| `quiz_attempt_fact` | `QUIZ_ANSWERED` 1.0·1.1 | `attempt_uuid`·`question_uuid`·`content_uuid` CHAR(32); `question_type` VARCHAR(32) N(1.0은 `MULTIPLE_CHOICE`로 채움); `choice_uuid` CHAR(32) N; `is_correct` BOOLEAN |
| `movement_fact` | `MOVEMENT_OBSERVED` | `floor_uuid` CHAR(32); `zone_uuid` CHAR(32) N; `x`·`y` DOUBLE; `input_kind` VARCHAR(32) |
| `floor_transfer_fact` | `FLOOR_TRANSFERRED` | `from_floor_uuid`·`to_floor_uuid` CHAR(32); `zone_uuid` CHAR(32) N |
| `point_grant_fact` | `POINT_GRANTED` | `ledger_uuid`·`attempt_uuid` CHAR(32); `delta`·`balance_after` BIGINT |

## C.3 처리 오류 테이블 `stream_processing_error`

| 컬럼 | 타입 | N | 키 | 설명 |
|---|---|---|---|---|
| `topic` | VARCHAR(249) | | PK(`topic`, `partition`, `offset`) | 입력 위치 |
| `partition` | INT | | | |
| `offset` | BIGINT | | | |
| `event_uuid` | CHAR(32) | N | | 읽을 수 있을 때만 |
| `error_code` | VARCHAR(64) | | | 부록 B.5의 Spark 코드 |
| `error_detail` | VARCHAR(255) | | | 필드 이름 수준의 설명 |
| `source_reference` | VARCHAR(512) | | | `kafka://<토픽>/<파티션>/<오프셋>` |
| `observed_at` | DATETIME(6) | | 기본 현재 시각 | |

같은 입력 위치의 오류는 처음 기록한 행을 유지한다.

---

# 부록 D. 광고 서버 DB

광고 서버(Django)의 테이블 20개다. **모든 PK는 UUIDv7**(시간 순서가 있는 UUID)이고 자동 증가 키는 없다. 예외는 `events_outbox.event_id` 하나로, 같은 원천에서 언제나 같은 값이 나오는 UUIDv5다. 금액은 정수 포인트이고 상한은 2^53−1(`MAX`)이다. **[추가 전용]** 표는 저장만 하고 고치거나 지우지 않는다(애플리케이션 계층이 막는다).

## D.1 계정·감사

**`foundation_user`** — 광고주·관리자 계정

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `id` | UUID | | PK | |
| `username` | varchar(30) | | UNIQUE | 로그인 ID(`[a-z0-9_]{4,20}`) |
| `password` | varchar(128) | | | Argon2 해시 |
| `role` | varchar(20) | | 기본 `advertiser` | `admin` · `advertiser` |
| `nickname` | varchar(20) | | | |
| `class_label` | varchar(30) | | | 소속 반(자유 입력) |
| `is_active`·`is_superuser` | bool | | | `is_active`를 끄면 비활성화(계정 삭제 방식) — 열린 세션·광고 송출·공개 이미지가 함께 멈춘다 |
| `session_epoch` | int unsigned | | 기본 0 | 비활성화하면 1 늘려 열린 세션을 끊는다 |
| `last_login` | datetime(6) | N | | |
| `created_at` | datetime(6) | | | |

**`foundation_audit_log`** [추가 전용] — 운영·계정 동작 기록

| 컬럼 | 타입 | N | 키·제약 | 설명 |
|---|---|---|---|---|
| `log_id` | UUID | | PK | |
| `actor_id` | UUID | N | INDEX | 행위자(FK 아님 — 계정이 바뀌어도 기록은 남는다) |
| `actor_username` | varchar(30) | | | |
| `action` | varchar(64) | | INDEX | 예: `account.signup`, `billing.adjusted`, `campaign.suspended` |
| `target_type`·`target_id` | varchar(64) | | | |
| `detail` | json | | 기본 `{}` | 비밀 값 이름은 지우고, 길면 줄인다 |
| `ip` | varchar(45) | | | |
| `request_id` | varchar(36) | | | |
| `created_at` | datetime(6) | | INDEX | |

## D.2 마스터(관리자가 관리)

| 테이블 | 컬럼 | 키·제약 |
|---|---|---|
| `masters_media` 매체 | `media_id` PK, `name` varchar(100), `is_active` bool, `created_at` | UNIQUE(`name`) |
| `masters_media_deactivation` 매체 비활성화 기록 [추가 전용] | `deactivation_id` PK, `media_id`, `deactivated_at` | FK `media_id` PROTECT; INDEX(`media_id`, `deactivated_at`) |
| `masters_slot` 광고 자리 | `slot_id` PK, `media_id`, `name` varchar(100), `audience` varchar(20), `is_active`, `created_at` | FK `media_id` PROTECT; UNIQUE(`media_id`, `name`); CHECK `audience` ∈ {`individual`, `shared`}; `audience`는 만든 뒤 바꿀 수 없다 |
| `masters_media_key` 매체 키 | `key_id` PK, `media_id`, `secret_hash` varchar(64), `label`, `created_at`, `expires_at`(N), `revoked_at`(N), `request_key`(N) | FK PROTECT; UNIQUE(`request_key`). 키 원문은 저장하지 않고 SHA-256만 둔다 |
| `masters_bid_policy` 입찰 정책 [추가 전용, 버전] | `bid_policy_id` PK, `slot_id`, `policy_version` int unsigned, `floor_amount`·`base_amount`·`cap_amount` bigint unsigned, `impression_share`·`click_share`·`conversion_share` smallint unsigned, `changed_by` UUID, `changed_at`, `reason` varchar(200) | FK PROTECT; UNIQUE(`slot_id`, `policy_version`); CHECK 하한 ≥ 100, 하한 ≤ 기준 ≤ 상한 ≤ MAX; CHECK 비율 각 1~98, 합 100 |

## D.3 광고 운영(광고주가 관리)

| 테이블 | 컬럼 | 키·제약 |
|---|---|---|
| `campaigns_campaign` 캠페인 | `campaign_id` PK, `owner_id`, `name`, `starts_at`, `ends_at`(N), `daily_budget` bigint unsigned, `status`, `ended_from`(N), `suspended_reason`, `suspended_at`(N), `request_key`(N), `created_at`, `updated_at` | FK `owner_id` → `foundation_user` PROTECT; `status` ∈ {`ACTIVE`, `PAUSED`, `SUSPENDED`, `ENDED`}; CHECK 0 < 일예산 ≤ MAX; CHECK 종료 ≥ 시작; UNIQUE(`request_key`); INDEX(`status`, `ends_at`) |
| `campaigns_ad_group` 광고그룹 | `ad_group_id` PK, `campaign_id`, `name`, `enabled`, `creative_id`(N, 지금 쓰는 소재), `request_key`(N), `created_at`, `updated_at` | FK PROTECT; UNIQUE(`request_key`) |
| `campaigns_ad_group_slot` 광고그룹-자리 | `ad_group_slot_id` PK, `ad_group_id`, `slot_id` | FK `ad_group_id` CASCADE, `slot_id` PROTECT; UNIQUE(`ad_group_id`, `slot_id`). 자리를 바꾸면 빠진 행을 지운다(유일한 삭제 대상) |
| `campaigns_creative` 소재 | `creative_id` PK, `owner_id`, `title` varchar(200), `redirect_url` varchar(2048), `image_name` varchar(80), `image_bytes`, `archived_at`(N), `created_at`, `updated_at` | FK PROTECT; INDEX(`image_name`). 삭제 대신 보관(`archived_at`) |
| `campaigns_ad_group_creative` 광고그룹-소재 연결 [추가 전용] | `link_id` PK, `ad_group_id`, `creative_id`, `linked_at` | FK PROTECT; UNIQUE(`ad_group_id`, `creative_id`) |
| `campaigns_creative_image` 소재 이미지 보유 [추가 전용] | `creative_image_id` PK, `creative_id`, `image_name`, `image_bytes`, `created_at` | FK PROTECT; UNIQUE(`creative_id`, `image_name`). 이미지를 바꿔도 이전 파일을 계속 공개할 수 있게 남긴다 |
| `campaigns_bid` 입찰 [추가 전용, 버전] | `bid_id` PK, `ad_group_id`, `bid_version` int unsigned, `amount` bigint unsigned, `created_by` UUID, `created_at` | FK PROTECT; UNIQUE(`ad_group_id`, `bid_version`); CHECK 0 < 금액 ≤ MAX |
| `campaigns_review_request` 재검토 요청 | `review_request_id` PK, `campaign_id`, `message`, `status`, `response_note`, `created_at`, `closed_at`(N), `open_campaign`(계산 열) | FK PROTECT; `status` ∈ {`OPEN`, `RELEASED`, `REJECTED`, `CLOSED_ENDED`}; UNIQUE(`open_campaign`) — 캠페인마다 열린 요청 하나 |

## D.4 지갑·원장

| 테이블 | 컬럼 | 키·제약 |
|---|---|---|
| `billing_wallet` 광고 포인트 지갑 | `wallet_id` PK, `owner_id`, `balance` bigint unsigned(기본 0), `created_at` | FK `owner_id` PROTECT, UNIQUE(1:1); CHECK 잔액 ≤ MAX |
| `billing_ledger_entry` 원장 [추가 전용] | `entry_id` PK, `wallet_id`, `seq` int unsigned, `entry_type`, `amount` bigint, `balance_after` bigint unsigned, `campaign_id`(N), `reaction_ref`(N), `adjust_key`(N), `charge_policy`, `shortfall` bigint unsigned, `note`, `created_at`, `signup_grant_wallet`(계산 열) | FK PROTECT; UNIQUE(`wallet_id`, `seq`); `entry_type` ∈ {`SIGNUP_GRANT`, `CHARGE`, `ADMIN_ADJUST`, `TOPUP`(예약)}; CHECK 유형별 부호(과금은 0 이하, 가입 지급은 양수, 조정은 0 아님); UNIQUE(`reaction_ref`) — 반응 하나에 과금 하나; UNIQUE(`adjust_key`); UNIQUE(`signup_grant_wallet`) — 지갑마다 가입 지급 하나; INDEX(`campaign_id`, `entry_type`, `created_at`, `amount`) |

## D.5 결정·반응·이벤트

**`records_decision`** [추가 전용] — 광고 요청 하나의 결정과 그때의 스냅샷(FK 없음)

| 컬럼 | 타입 | N | 설명 |
|---|---|---|---|
| `decision_id` | UUID | | PK |
| `media_id`·`slot_id` | UUID | | 요청한 매체·자리 |
| `audience` | varchar(20) | | `individual` · `shared` |
| `subject_id` | varchar(200) | N | 매체가 만든 광고 가명. 개인 자리면 필수, 공용 자리면 NULL(CHECK) |
| `context` | json | | 매체가 보낸 문맥(직접 식별자 금지). 이벤트에는 싣지 않는다 |
| `decided_at` | datetime(6) | | INDEX |
| `owner_id`·`campaign_id`·`ad_group_id`·`creative_id` | UUID | N | 뽑힌 광고 |
| `bid_id`·`bid_version`·`bid_amount` | | N | 그때의 입찰 |
| `bid_policy_id`·`policy_version`·`applied_amount` | | N | 그때의 정책과 적용 금액 |
| `impression_share`·`click_share`·`conversion_share` | smallint unsigned | N | 그때의 과금 비율(합 100, CHECK) |
| `snapshot` | json | N | 그때의 소재 `{title, redirect_url, image_name}` |
| `selection_policy` | varchar(64) | | 고른 방식 |
| `candidate_count` | int unsigned | | 후보 수 |
| `rejected_counts` | json | | 탈락 사유별 수 |
| `trace` | json | | 추첨 근거 |

CHECK: 뽑힌 광고의 열 14개는 모두 있거나 모두 없다. INDEX(`media_id`, `decided_at`), (`slot_id`, `subject_id`, `decided_at`), (`owner_id`, `campaign_id`, `ad_group_id`).

**`records_reaction`** — 반응 수신함(노출·클릭·전환). 받은 그대로 저장한 뒤 판정 결과로 상태만 바뀐다.

| 컬럼 | 타입 | N | 설명 |
|---|---|---|---|
| `inbox_id` | UUID | | PK |
| `media_id`·`reaction_id` | UUID | | UNIQUE(`media_id`, `reaction_id`) — 같은 반응은 한 번만 |
| `decision_id` | UUID | | 대상 결정(FK 아님) |
| `type` | varchar(20) | | `IMPRESSION` · `CLICK` · `CONVERSION` |
| `occurred_at`·`received_at` | datetime(6) | | 매체가 말한 시각·서버가 받은 시각 |
| `raw` | json | | 받은 본문 그대로 |
| `source` | varchar(10) | | `media`(매체 보고) · `server`(서버가 관측한 클릭) |
| `subject_id`·`person_id` | varchar(200) | N | 보고된 가명·판정에 쓴 사람 |
| `status` | varchar(20) | | `RECEIVED` → `ACCEPTED` 또는 `REJECTED` |
| `reason_code` | varchar(40) | N | 거부 사유(거부일 때만, 13종) |
| `applied_rule`·`processed_at`·`checked_at` | | N | 판정한 규칙·시각·보류 확인 시각 |
| `accepted_key` | varchar(255) | N | UNIQUE — 같은 사람·결정·유형의 인정은 하나 |
| `attempts` | smallint unsigned | | 처리 실패 횟수(5회면 멈춘 것으로 표시) |
| `basis` | json | N | 판정 근거 |

INDEX(`status`, `received_at`), (`decision_id`, `type`, `status`), (`received_at`), (`processed_at`).

**`events_outbox`** — MongoDB로 옮길 이벤트 대기(보낸 지 7일 뒤 지운다)

| 컬럼 | 타입 | N | 설명 |
|---|---|---|---|
| `event_id` | UUID | | PK. UUIDv5(`이벤트 이름/원천 ID`) — 같은 사실은 언제나 같은 ID |
| `event_name` | varchar(64) | | `ad.decision` · `ad.reaction_received` · `ad.reaction` · `ad.charge` |
| `schema_version` | smallint unsigned | | `ad.decision`은 2, 나머지는 1 |
| `aggregate_id` | UUID | | 결정 ID |
| `payload` | json | | 부록 D.6 |
| `created_at` | datetime(6) | | INDEX(`sent_at`, `created_at`), INDEX(`event_name`, `created_at`) |
| `sent_at` | datetime(6) | N | MongoDB 저장 확인 시각. NULL이면 대기 |

## D.6 MongoDB `ad_events`

| 필드 | 형식 | 설명 |
|---|---|---|
| `_id` | UUID(이진) | outbox의 `event_id` |
| `event_name` | 문자열 | |
| `schema_version` | 정수 | |
| `produced_at` | 날짜 | outbox `created_at`(밀리초) |
| `payload` | 객체 | 아래 |

컬렉션 검증(`$jsonSchema`, 엄격)이 위 다섯 필드를 강제한다. 색인은 (`event_name`, `produced_at`), (`payload.decision_id`, `produced_at`)다. 쓰기는 과반 확인(`w=majority`)을 받는다.

| 이벤트 | 언제 | payload 필드 |
|---|---|---|
| `ad.decision`(2) | 결정 | `decision_id`, `media_id`, `slot_id`, `decided_at`, `audience`, `subject_id`, `selected`(null 또는 캠페인·광고그룹·소재·과금 비율·입찰·정책·금액), `selection_policy`, `candidate_count`, `rejected_counts` |
| `ad.reaction_received`(1) | 반응 접수 | `inbox_id`, `reaction_id`, `media_id`, `decision_id`, `type`, `occurred_at`, `received_at`, `subject_id`, `source`, `raw` |
| `ad.reaction`(1) | 판정 | 접수 필드 + `person_id`, `audience`, `status`, `reason_code`, `applied_rule`, `basis` |
| `ad.charge`(1) | 과금 | `entry_id`, `campaign_id`, `charge_policy`, `created_at`, `reaction_ref`, `decision_id`, `requested_amount`, `charged_amount`, `shortfall`, `budget_day` |

payload 안의 시각은 UTC ISO-8601(`+00:00` 표기, 마이크로초)이다.

## D.7 코드값

| 항목 | 값 |
|---|---|
| 반응 거부 사유(13) | `unknown_decision`, `media_mismatch`, `media_deactivated`, `no_ad_shown`, `click_not_reported`, `subject_required`, `subject_mismatch`, `invalid_occurred_at`, `campaign_ended`, `duplicate_type`, `window_expired`, `display_ended`, `missing_prerequisite` |
| 후보 탈락 사유(7) | `campaign_not_active`, `ad_group_disabled`, `not_started`, `expired`, `below_floor`, `budget_exhausted`, `insufficient_balance` |
| 반응 판정 기간 | 클릭은 결정 뒤 300초 안, 전환은 클릭 뒤 30일 안, 보고 시각 허용 오차 60초 |
| 과금 | 적용 금액 × 반응 유형의 비율 ÷ 100(정수 나눗셈). 잔액이 모자라면 있는 만큼만 차감하고 모자란 양을 `shortfall`에 남긴다 |

---

# 부록 E. 근거 위치

이 문서의 사실은 아래 코드에서 확인했다(저장소 기준 경로).

| 영역 | 위치 |
|---|---|
| 플랫폼 모델 | `backend/accounts/models.py`, `backend/eventing/models.py`, `backend/learning/models.py`, `backend/community/models.py`, `backend/direct_messages/models.py`, `backend/ad_bridge/models.py`, 각 앱의 `migrations/` |
| 플랫폼 이벤트 발행 | `backend/eventing/events.py`(이벤트 생성·필드 검사), `backend/eventing/publisher.py`(outbox 발행기·Producer 설정), `backend/campus/positions.py`(위치 저장), `backend/learning/services.py`(답안·포인트), `backend/accounts/session_policy.py`·`session_cleanup.py`(세션·채팅 정리) |
| Std and Sinker | `pipeline/std_and_sinker/contracts/`(계약·도메인·표준 단어·용어·지문 시험 벡터), `pipeline/std_and_sinker/sinker/`(처리·저장·발행), `pipeline/std_and_sinker/manage_topics.py` |
| Spark | `pipeline/spark/contracts/registry.json`, `pipeline/spark/migrations/001_facts.sql`, `pipeline/spark/spark_pipeline/`(검증·적재) |
| 광고 서버 | `apps/ads_server/*/models.py`, `apps/ads_server/events/`(outbox·중계·이벤트 모양), `apps/ads_server/records/`(결정·반응·판정), `apps/ads_server/billing/`(지갑·원장), `apps/ads_server/config/settings/base.py`(한도·기간) |
| 저장소 구성 | `aws-platform/platform/roles/`(MySQL·MongoDB·Kafka·Spark 설치·설정), `aws-infra/`(서버 배치) |
