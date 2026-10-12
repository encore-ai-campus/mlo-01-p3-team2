# scripts/ad_bridge/game/views.py

원본: `scripts/ad_bridge/game/views.py` · [소스 파일](../../../../../scripts/ad_bridge/game/views.py)

개인 슬롯 요청·노출 알림·판정 조회를 로그인과 CSRF 보호 POST로 제공한다. 서버 프로필에서 가명 UUID를 읽고 저장된 사용자 소유 기록만 조회한다. ADS_SUBJECT_ID_ATTRIBUTE 기본은 campus_profile.user_uuid, 테스트 게임은 player.subject_id다. 미접수는 로컬 상태를 반환하고 확정 판정은 재조회하지 않는다.

## 직접 선언

### request_decision

참조: `scripts/ad_bridge/game/views.py::def request_decision(request)`

개인 슬롯 요청 한 번. Django 기본 CSRF 미들웨어와 함께 사용한다.

### report_impression

참조: `scripts/ad_bridge/game/views.py::def report_impression(request, decision_id)`

개인 슬롯의 노출 알림을 최초 한 번 보고한다. 실제 화면 감지는 호출자의 책임이다.

### _subject_id

참조: `scripts/ad_bridge/game/views.py::def _subject_id(user)`

기존 게임은 campus_profile.user_uuid, 테스트 게임은 player.subject_id를 사용한다.

### _result_payload

참조: `scripts/ad_bridge/game/views.py::def _result_payload(record)`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### reaction_result

참조: `scripts/ad_bridge/game/views.py::def reaction_result(request, decision_id)`

서버 저장 상태를 확인하고 접수된 반응만 광고 서버에서 한 번 조회한다.
