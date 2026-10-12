# scripts/ad_bridge/impressions/store.py

원본: `scripts/ad_bridge/impressions/store.py` · [소스 파일](../../../../../scripts/ad_bridge/impressions/store.py)

노출 예약·재전송 일정·임대를 보관한다. get_impression은 사용자 소유 기록만 읽는다. update_result는 접수 완료 기록의 status·reason_code·request_id만 조건부 갱신하며 확정 판정과 전송 정보를 보존한다.

## 직접 선언

### StoredImpression

참조: `scripts/ad_bridge/impressions/store.py::StoredImpression`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### DecisionNotFound

참조: `scripts/ad_bridge/impressions/store.py::DecisionNotFound`

현재 사용자에게 발급한 결정이 없으며 타 사용자 존재 여부도 공개하지 않는다.

### NoAdForDecision

참조: `scripts/ad_bridge/impressions/store.py::NoAdForDecision`

광고 없는 결정에는 노출을 생성할 수 없다.

### _uuid

참조: `scripts/ad_bridge/impressions/store.py::def _uuid(value: str | UUID) -> UUID`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _utc_time

참조: `scripts/ad_bridge/impressions/store.py::def _utc_time(value: str) -> datetime`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _snapshot

참조: `scripts/ad_bridge/impressions/store.py::def _snapshot(record) -> StoredImpression`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _aware_time

참조: `scripts/ad_bridge/impressions/store.py::def _aware_time(value: datetime, field: str) -> datetime`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _lease_end

참조: `scripts/ad_bridge/impressions/store.py::def _lease_end(now: datetime, lease_seconds: float) -> datetime`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### reserve_impression

참조: `scripts/ad_bridge/impressions/store.py::def reserve_impression(decision_id: str | UUID, subject_id: str | UUID, occurred_at: str, *, now: datetime | None=None, lease_seconds: float=60) -> tuple[StoredImpression, bool]`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### claim_due_impression

참조: `scripts/ad_bridge/impressions/store.py::def claim_due_impression(*, now: datetime, lease_seconds: float=60) -> StoredImpression | None`

미확인 또는 임대가 만료된 기록 하나를 새 임대로 확보한 뒤 커밋한다.

### finish_impression

참조: `scripts/ad_bridge/impressions/store.py::def finish_impression(reaction_id: str | UUID, *, delivery_state: str, status: str | None=None, reason_code: str | None=None, request_id: str | None=None, lease_token: str | UUID | None=None, next_attempt_at: datetime | None=None, last_error: str | None=None, last_http_status: int | None=None) -> StoredImpression`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### ImpressionNotReady

참조: `scripts/ad_bridge/impressions/store.py::ImpressionNotReady`

접수 완료되지 않은 노출은 판정 조회 대상으로 삼지 않는다.

### get_impression

참조: `scripts/ad_bridge/impressions/store.py::def get_impression(*, decision_id: str | UUID, subject_id: str | UUID) -> StoredImpression`

사용자 소유의 기존 노출만 읽으며 새 기록을 만들지 않는다.

### update_result

참조: `scripts/ad_bridge/impressions/store.py::def update_result(*, decision_id: str | UUID, subject_id: str | UUID, reaction_id: str | UUID, status: str, reason_code: str | None, request_id: str | None) -> StoredImpression`

판정만 조건부 갱신한다. 이미 확정된 판정과 전송 정보는 보존한다.
