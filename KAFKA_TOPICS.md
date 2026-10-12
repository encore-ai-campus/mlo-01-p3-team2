# 플랫폼 Kafka 토픽 정리

현재 **6개 토픽, 13개 이벤트** 구현된 상태임. 플랫폼에 Kafka 전송기까지 구현

## 1. 토픽과 이벤트

| 토픽 | 이벤트 | 수집 내용 |
|---|---|---|
| `raw.account` | `session_started`, `session_ended` | 로그인 세션 시작·종료 |
| `raw.chat` | `chat_sent` | 서버가 받아들인 채팅 |
| `raw.board` | `post_created`, `post_updated`, `post_deleted`, `post_read` | 커뮤니티 게시글 작성·수정·삭제·상세 조회 |
| `raw.comment` | `comment_created`, `comment_updated`, `comment_deleted` | 댓글·대댓글 작성·수정·삭제 |
| `raw.content_usage` | `content_open_requested` | 오목·전쟁시대·아빠와 나·지뢰찾기·사과게임·버블슈터·수박게임·후레시맨·심심테스트 열기 요청 |
| `raw.movement` | `movement_observed`, `floor_transferred` | 이동 좌표·층 전환 |

포인트 지급, 퀴즈 답안, 옥상 부저 참여·추첨은 현재 Raw 이벤트 범위에서 제외함.

## 2. 공통 메시지 구조

- **Kafka Key:** `user_uuid`
- **Kafka Value:** UTF-8 JSON
- 로그는 JSON 형식으로 생성하며, 별도 `.json` 파일은 생성하지 않음.

| 구분 | 필드 | 의미 |
|---|---|---|
| 최상위 | `event_uuid` | 발생한 이벤트 한 건의 고유 UUIDv4 |
| `raw_manifest` | `schema_version` | 현재 `"1.0"` |
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
| `movement_observed` | `floor_uuid`, `zone_uuid`, `x`, `y`, `input_kind` |
| `floor_transferred` | `from_floor_uuid`, `to_floor_uuid`, `zone_uuid` |

**현재 값과 수집 기준**

- `end_reason`: 직접 로그아웃은 `"LOGOUT"`, 세션 만료는 `"SESSION_EXPIRED"`로 기록함. 웹소켓 연결 종료만으로 로그인 세션을 종료하지 않음.
- `channel_code`: 현재 `"GLOBAL"` 사용함.
- `revision`: 1부터 시작하며 수정·삭제 시 증가함.
- `content_kind`: 현재 콘텐츠는 `"EXTERNAL_LINK"`로 기록함.
- `action`: 현재 `"OPEN_REQUESTED"`로 기록함. 외부 사이트의 실제 로딩·게임 완료·테스트 완료를 의미하지 않음.
- `domain`: 현재 오목·전쟁시대·아빠와 나·지뢰찾기·사과게임·버블슈터·수박게임·후레시맨와 심심테스트는 모두 `"REST"`임. 게임과 심리 테스트는 서로 다른 `category_uuid`로 구분하고 각 게임은 서로 다른 `content_uuid`로 구분함. `"LEARNING"`은 추후 학습 콘텐츠용으로 남겨두며 현재 등록된 콘텐츠는 없음.
- `input_kind`: 현재 `"KEYBOARD"`로 기록함.
- `x`, `y`: 맵 좌표임. 이동 Raw에는 방향 필드를 넣지 않음.
- 게시글·이동·층 전환의 `zone_uuid`는 현재 `null`임. 콘텐츠 열기는 해당 부스 ID를 넣음.
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
| `REST` | `game` — 게임 | 오목, 전쟁시대, 아빠와 나, 지뢰찾기, 사과게임, 버블슈터, 수박게임, 후레시맨 |
| `REST` | `psychology` — 심리 테스트 | 심심테스트 |
| `LEARNING` | 추후 학습 콘텐츠에 맞춰 추가 | 현재 없음 |

콘텐츠 열기 이벤트는 모두 `raw.content_usage`로 발행하고, `domain`과 `category_uuid`로 분류함. 게임·심리 테스트의 카테고리는 서로 구분되며, 학습 콘텐츠가 추가되면 `LEARNING`에 해당 카테고리를 등록할 예정임.

채팅 원문·닉네임, 게시글 제목·본문, 댓글 본문은 Kafka Raw에 포함하지 않음. 채팅 원문은 운영 DB에 30일 보관함.

## 4. 저장·전송 방식

| 구분 | 처리 방식 | 실패 처리 |
|---|---|---|
| `movement_observed` | 메모리 대기열 → Kafka | 일부 유실 허용. DB에 보관하지 않음 |
| 그 외 모든 이벤트 | DB Outbox → Kafka | DB에 남겨두고 재시도 |

주요 서비스 변경과 Outbox 기록을 같은 DB 트랜잭션으로 저장함. Kafka의 전송 성공 응답을 받은 뒤 전송 완료로 표시함.

Producer는 `acks=all`, `enable.idempotence=True`를 사용함. Kafka 전송 성공 직후 서버가 종료되면 같은 이벤트가 다시 전송될 수 있으므로, 소비자에서도 `event_uuid` 기준 중복 제거가 필요함.

현재 DB는 SQLite임. Kafka 연결 정보가 없는 상태에서는 Outbox 이벤트가 DB에 대기하고, 이동 Raw는 저장·전송되지 않음.
