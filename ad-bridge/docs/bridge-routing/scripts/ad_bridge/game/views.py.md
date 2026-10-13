# ad-bridge/scripts/game/views.py

원본: `ad-bridge/scripts/game/views.py` · [소스 파일](../../../../../scripts/game/views.py)

개인 슬롯 요청·노출 알림·판정 조회를 로그인과 CSRF 보호 POST로 제공한다. _owner_id로 서버 프로필의 내부 사용자 UUID를 읽는다. 결정 요청에서만 광고 가명을 생성하고 owner_id와 subject_id를 분리해 저장한다. 노출·판정 조회는 owner_id로 소유권을 확인하며 저장된 광고 가명을 사용한다. ADS_SUBJECT_ID_ATTRIBUTE 기본은 campus_profile.user_uuid, 테스트 게임의 입력 위치는 player.subject_id다. 세 경로 모두 AdsConfig.from_env로 비밀을 검증한다. 미접수는 로컬 상태를 반환하고 확정 판정은 재조회하지 않는다.

ADS_SUBJECT_SECRET 누락·오류 또는 잘못된 사용자 UUID는 외부 요청 전에 HTTP 503·ads_invalid_config로 처리한다. 유효한 설정에서 프로필 UUID가 없으면 기존 HTTP 409·profile_uuid_missing을 반환한다. 오류 응답에 비밀값과 원본 UUID를 넣지 않는다.

## 직접 선언

### request_decision

참조: `ad-bridge/scripts/game/views.py::def request_decision(request)`

개인 슬롯 요청 한 번. 광고 서버에는 가명 subject_id만 전달하고, 발급 저장소에는 내부 owner_id도 함께 전달한다. Django 기본 CSRF 미들웨어와 함께 사용한다.

### report_impression

참조: `ad-bridge/scripts/game/views.py::def report_impression(request, decision_id)`

개인 슬롯의 노출 알림을 최초 한 번 보고한다. 내부 owner_id로 소유권을 확인하고 발급 당시 저장된 가명으로 노출을 예약한다. 실제 화면 감지는 호출자의 책임이다.

### _owner_id

참조: `ad-bridge/scripts/game/views.py::def _owner_id(user) -> UUID | None`

설정된 프로필 경로에서 내부 UUID를 읽고 표준 UUID 값으로 정규화한다. 프로필 누락은 None, 잘못된 값은 원문 없는 ValueError로 처리한다. 이 값은 광고 서버 요청이나 브라우저 응답에 넣지 않는다.

### _subject_id

참조: `ad-bridge/scripts/game/views.py::def _subject_id(user_uuid: UUID, *, subject_secret: str) -> UUID`

_owner_id가 검증한 UUID를 받아 광고 가명을 생성한다. UTF-8로 인코딩한 ADS_SUBJECT_SECRET을 키로, "ads-subject/v1:" + 표준 UUID 문자열을 메시지로 HMAC-SHA256을 계산하고 앞 16바이트를 UUID로 변환한다. UUID 버전 비트는 바꾸지 않는다. 같은 사용자와 같은 비밀은 같은 가명을 만든다. 비밀은 호출 전에 AdsConfig에서 검증한다.

### _result_payload

참조: `ad-bridge/scripts/game/views.py::def _result_payload(record)`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### reaction_result

참조: `ad-bridge/scripts/game/views.py::def reaction_result(request, decision_id)`

내부 owner_id로 서버 저장 상태를 확인하고 접수된 반응만 광고 서버에서 한 번 조회한다. 반환된 반응은 저장된 발급 당시 가명으로 대조한다.

## 분석 근거와 범위

직접 선언·시그니처·import·호출 표기는 routing-doc-sync AST 결과를 사용한다. 내부 소유권·저장된 가명·비밀 교체 뒤 노출·재전송·결과 조회는 단위 테스트와 임시 DB 검사로 검증했다. 기존 기록의 소유자를 자동 복원하는 기능은 구현하지 않는다.
