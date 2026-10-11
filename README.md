# 게임 서버 광고 API 통신 구현 계획

이 문서는 구현할 다섯 가지 통신 작업을 정리한다. 아직 코드 구현 완료를 의미하지 않는다. 아래 함수·설정 이름은 구현 제안이며, HTTP 요청·응답 규격은 기존 광고 계약을 따른다.

규칙: [광고 API 연동 규칙](./api-rules.md#지켜야-할-규칙) · [OpenAPI 원본](../ads-server/docs/ads-server/contracts/serving.openapi.yaml)

완료 확인: [구현·검증 체크리스트](./api-checklist.md). 아래에서 구현 내용을 확인한 뒤, 체크리스트의 해당 완료 기준을 검증하고 체크한다.

<a id="connection-settings"></a>

## 1. 연결 설정

완료 기준: [연결 설정 체크](./api-checklist.md#connection-settings)

**목표:** 게임 서버에서 광고 API에 접속할 공통 설정을 준비한다.

| 설정 이름(제안) | 의미 |
|---|---|
| `ADS_API_BASE_URL` | `/api/media/v1`까지 포함한 API 기본 주소. 환경별로 주입한다. |
| `ADS_MEDIA_KEY` | 광고 서버에서 발급한 매체 인증 키 |
| `ADS_API_TIMEOUT` | HTTP 요청 타임아웃. 단위는 초이며 값은 담당자와 정한다. |

- 기본 주소 뒤에 `/decisions` 등을 붙이며 경로가 중복되지 않게 한다.
- 서버에서 `X-Media-Key`와 JSON 요청용 `Content-Type: application/json`을 첨부한다.
- 키는 소스에 직접 작성하거나 브라우저에 전달하지 않는다. 로그에도 비밀 값을 기록하지 않는다.
- 필수 설정 누락은 요청 전에 설정 오류로 알려준다.

관련 규칙: [인증·요청 규칙](./api-rules.md#지켜야-할-규칙)

<a id="create-decision"></a>

## 2. 광고 요청 — `create_decision()`

완료 기준: [광고 요청 체크](./api-checklist.md#create-decision)

**입력:** `slot_id`, 선택 `subject_id`, 선택 `context`.

**처리:** `POST /api/media/v1/decisions`에 JSON 본문을 전송하고 201 응답을 해석한다.

- 개인 슬롯은 `subject_id`를 보내고 공유 슬롯은 해당 필드를 생략한다.
- 사용자가 읽는 슬롯 이름 대신 슬롯 UUID를 보낸다.
- `context`는 필요한 경우에만 넣으며 직접 식별정보와 크기·깊이 제한을 지킨다.

**반환:** `decision_id`, `slot_id`, `slot_name`, `audience`, `decided_at`, `ad`.

- `ad`가 있으면 `creative_id`, `title`, `image_url`, `redirect_url`, `click_url`을 호출자에게 전달한다.
- `ad: null`은 광고 없음이라는 정상 결과로 반환한다.
- 응답 필드가 추가되어도 모르는 필드 때문에 실패하지 않는다.

관련 규칙: [슬롯·광고 요청 규칙](./api-rules.md#지켜야-할-규칙)

<a id="put-reaction"></a>

## 3. 반응 보고 — `put_reaction()`

완료 기준: [반응 보고 체크](./api-checklist.md#put-reaction)

**입력:** 게임 쪽에서 준비한 `decision_id`, `reaction_id`, `type`, `occurred_at`, 필요한 `subject_id`.

**처리:** `PUT /api/media/v1/decisions/{decision_id}/reactions/{reaction_id}`를 호출한다.

- 경로에는 결정·반응 ID를 넣고 본문에는 `type`, `occurred_at`, 필요한 `subject_id`만 넣는다.
- 이번 연동에서 보내는 유형은 `IMPRESSION`·`CONVERSION`이다. `CLICK`을 별도 보고하지 않는다.
- 감지한 시각을 UTC `...Z` 형식으로 전달한다. 재시도 시 현재 시각으로 바꾸지 않는다.
- 공유 슬롯의 반응에는 해당 사용자의 가명 UUID를 넣는다.
- 감지 시점에 만든 반응 ID와 본문을 전달받아 그대로 사용한다. 통신 함수에서 재시도마다 새 ID를 만들지 않는다.

**반환:** HTTP 접수 결과(201 또는 200)와 광고 서버의 반응 응답.

- 201은 최초 접수, 200은 같은 내용 재전송 성공이다.
- 2xx를 최종 인정·과금 완료로 해석하지 않는다. 응답의 상태는 별도로 읽는다.

관련 규칙: [반응·접수·중복 방지 규칙](./api-rules.md#지켜야-할-규칙)

<a id="get-reaction"></a>

## 4. 결과 조회 — `get_reaction()`

완료 기준: [결과 조회 체크](./api-checklist.md#get-reaction)

**입력:** `decision_id`, `reaction_id`.

**처리:** `GET /api/media/v1/decisions/{decision_id}/reactions/{reaction_id}`를 호출한다. 요청 본문은 보내지 않는다.

**반환:** 광고 서버의 반응 정보, 특히 `status`와 `reason_code`.

- `RECEIVED`: 접수 후 처리 대기·보류. 이미 접수된 반응을 다시 PUT하지 않는다.
- `ACCEPTED`: 반응 인정. 통신 모듈에서 차감액을 계산하지 않는다.
- `REJECTED`: 반응 거부. 사유를 호출자에게 전달한다.
- 새로운 거부 사유 문자열이 와도 응답 해석 자체가 실패하지 않게 한다.
- 이 함수는 조회 한 번을 담당한다. 반복 조회 필요 여부와 간격은 호출하는 게임 코드에서 정한다.

관련 규칙: [접수와 최종 결과 구분](./api-rules.md#지켜야-할-규칙)

<a id="error-retry"></a>

## 5. 오류 처리·반응 재시도

완료 기준: [오류 처리·반응 재시도 체크](./api-checklist.md#error-retry)

**목표:** 호출자가 오류 원인을 구분하고, 실패한 반응을 동일한 요청으로 다시 보낼 수 있게 한다.

| 상황 | 처리 |
|---|---|
| 연결 실패·타임아웃 | 통신 오류로 구분한다. 반응 PUT은 같은 요청으로 재시도한다. |
| 반응 PUT의 429·5xx | 지수 백오프를 적용하고 `Retry-After`를 반영한다. |
| 400·401·403·404 등 429 외 4xx | 자동 재시도하지 않고 상태 코드·오류 정보를 전달한다. |
| 409 | 충돌로 전달한다. 새 반응 ID로 우회하지 않는다. |
| 응답 JSON 오류·필수 응답 누락 | 정상 결과로 취급하지 않고 응답 형식 오류로 구분한다. |

- 반응 재시도 동안 경로 ID·발생 시각·사용자·본문을 유지한다.
- 광고 요청 POST는 반복 호출하면 새 결정이 생길 수 있으므로 반응 재시도 정책을 일괄 적용하지 않는다.
- 오류 조사에 필요한 HTTP 상태·`X-Request-ID`를 전달하되 인증 키는 제외한다.
- 재시도 요청의 보관·실행 책임은 게임 담당자와 정한다. 이 문서는 게임 DB 저장을 필수로 정하지 않으며, 메모리 보관만으로는 재시작 후 복구를 보장하지 않는다.

관련 규칙: [오류·재시도 규칙](./api-rules.md#지켜야-할-규칙)
