# scripts/ad_bridge/api/client.py

원본: `scripts/ad_bridge/api/client.py` · [소스 파일](../../../../../scripts/ad_bridge/api/client.py)

광고 결정 POST·노출 PUT·반응 GET을 각각 한 번 수행한다. GET은 200 JSON과 ID·노출 응답 형식을 검사하며 자동 재시도하지 않는다. PUT의 접수 확인 의미와 GET 오류는 구분한다.

## 직접 선언

### _NoRedirect

참조: `scripts/ad_bridge/api/client.py::_NoRedirect`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _NoRedirect.redirect_request

참조: `scripts/ad_bridge/api/client.py::def _NoRedirect.redirect_request(self, req, fp, code, msg, headers, newurl)`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _uuid

참조: `scripts/ad_bridge/api/client.py::def _uuid(value: str | UUID, field: str) -> str`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _utc

참조: `scripts/ad_bridge/api/client.py::def _utc(value: str, field: str) -> datetime`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _url

참조: `scripts/ad_bridge/api/client.py::def _url(value: str, *, https_only: bool=False) -> bool`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _parse_decision

참조: `scripts/ad_bridge/api/client.py::def _parse_decision(body: bytes, slot_id: str, audience: str, request_id: str | None) -> Decision`

필수 값만 읽고 추가된 응답 필드는 무시한다. 잘못된 응답은 광고 없음과 구분한다.

### AdsClient

참조: `scripts/ad_bridge/api/client.py::AdsClient`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### AdsClient.__init__

참조: `scripts/ad_bridge/api/client.py::def AdsClient.__init__(self, config: AdsConfig) -> None`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### AdsClient._safe_metadata

참조: `scripts/ad_bridge/api/client.py::def AdsClient._safe_metadata(self, value: str | None) -> str | None`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### AdsClient._http_error

참조: `scripts/ad_bridge/api/client.py::def AdsClient._http_error(self, response) -> AdsHTTPError`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### AdsClient.create_decision

참조: `scripts/ad_bridge/api/client.py::def AdsClient.create_decision(self, slot_id: str | UUID, subject_id: str | UUID | None=None) -> Decision`

개인 슬롯에는 가명 subject_id를 전달하고, shared 슬롯에서는 생략한다. 자동 재시도하지 않는다.

### AdsClient._parse_reaction

참조: `scripts/ad_bridge/api/client.py::def AdsClient._parse_reaction(self, body: bytes, decision_id: str, reaction_id: str, occurred_at: str | None, subject_id: str | None, request_id: str | None, *, lookup: bool=False) -> Reaction`

보낸 반응과 일치하는 필수 값은 검증하고 새 필드·거부 사유는 허용한다.

### AdsClient.report_impression

참조: `scripts/ad_bridge/api/client.py::def AdsClient.report_impression(self, *, decision_id: str | UUID, reaction_id: str | UUID, occurred_at: str, subject_id: str | UUID | None=None) -> Reaction`

호출자가 보관한 반응 ID·감지 시각으로 노출을 한 번 보고한다. 자동 재시도하지 않는다.

### AdsClient.get_reaction

참조: `scripts/ad_bridge/api/client.py::def AdsClient.get_reaction(self, *, decision_id: str | UUID, reaction_id: str | UUID) -> Reaction`

저장된 노출 반응의 판정을 한 번 조회한다. PUT이나 자동 재시도는 하지 않는다.
