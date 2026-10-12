# ad-bridge/scripts/impressions/store.py

원본: `ad-bridge/scripts/impressions/store.py` · [소스 파일](../../../../../scripts/impressions/store.py)

노출 예약·재전송 일정·임대를 보관한다. reserve_impression은 IssuedDecision.owner_id로 내부 소유권을 확인한 뒤 발급 당시 subject_id를 노출에 복사한다. get_impression도 내부 소유권과 결정·노출 간 가명 일치를 확인한다. 비밀 교체 뒤에도 저장된 가명으로 노출·재전송을 처리한다. update_result는 접수 완료 기록의 status·reason_code·request_id만 조건부 갱신하며 확정 판정과 전송 정보를 보존한다. owner_id가 없는 이전 기록은 사용자 경로에서 조회·예약하지 않는다.

claim_blocked_401_impression은 명시한 401 차단 기록만 수동 복구용 임대로 확보한다. 자동 작업자의 claim_due_impression은 BLOCKED 기록을 선택하지 않는 기존 규칙을 유지한다. 복구용 관리 명령과 브라우저 경로는 아직 연결하지 않았다.

## 직접 선언

### StoredImpression

참조: `ad-bridge/scripts/impressions/store.py::StoredImpression`

전송용 스냅샷에는 저장된 광고 subject_id만 포함하며 내부 owner_id는 포함하지 않는다. sender와 재전송 작업자는 이 스냅샷의 불변 요청 내용을 사용한다.

### DecisionNotFound

참조: `ad-bridge/scripts/impressions/store.py::DecisionNotFound`

현재 사용자에게 발급한 결정이 없으며 타 사용자 존재 여부도 공개하지 않는다.

### NoAdForDecision

참조: `ad-bridge/scripts/impressions/store.py::NoAdForDecision`

광고 없는 결정에는 노출을 생성할 수 없다.

### _uuid

참조: `ad-bridge/scripts/impressions/store.py::def _uuid(value: str | UUID) -> UUID`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _utc_time

참조: `ad-bridge/scripts/impressions/store.py::def _utc_time(value: str) -> datetime`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _snapshot

참조: `ad-bridge/scripts/impressions/store.py::def _snapshot(record) -> StoredImpression`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _aware_time

참조: `ad-bridge/scripts/impressions/store.py::def _aware_time(value: datetime, field: str) -> datetime`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### _lease_end

참조: `ad-bridge/scripts/impressions/store.py::def _lease_end(now: datetime, lease_seconds: float) -> datetime`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### reserve_impression

참조: `ad-bridge/scripts/impressions/store.py::def reserve_impression(decision_id: str | UUID, owner_id: str | UUID, occurred_at: str, *, now: datetime | None=None, lease_seconds: float=60) -> tuple[StoredImpression, bool]`

owner_id로 발급 기록을 찾고 광고 유무를 검사한다. 최초 예약에는 결정의 subject_id를 저장하며, 중복 예약에는 기존 반응 ID·가명·발생 시각을 유지한다.

### claim_due_impression

참조: `ad-bridge/scripts/impressions/store.py::def claim_due_impression(*, now: datetime, lease_seconds: float=60) -> StoredImpression | None`

미확인 또는 임대가 만료된 기록 하나를 새 임대로 확보한 뒤 커밋한다.

### claim_blocked_401_impression

참조: `ad-bridge/scripts/impressions/store.py::def claim_blocked_401_impression(reaction_id: str | UUID, *, now: datetime, lease_seconds: float=60) -> StoredImpression | None`

지정한 reaction_id가 BLOCKED·마지막 HTTP 401·status 없음 조건을 만족하고, 임대 만료 시각이 없거나 현재 시각 이하일 때만 확보한다. 403·접수 완료·판정 저장·유효한 임대가 있는 기록은 제외한다. 조건에 맞지 않거나 기록이 없으면 None을 반환하고, 잘못된 UUID·시각·임대 시간은 기존 검증 함수의 ValueError로 처리한다.

transaction.atomic(durable=True) 안에서 복구 조건을 포함한 UPDATE를 수행한다. 성공한 호출만 SENDING 전환·attempts 증가·새 lease_token·lease_expires_at 설정·next_attempt_at 초기화를 수행하고 기존 스냅샷을 반환한다. 경쟁 임대와 뒤늦은 접수 확인으로 조건이 달라지면 임대를 반환하지 않는다. 외부 트랜잭션 안에서 미커밋 전송 기록을 반환하지 않는다.

decision_id·reaction_id·subject_id·occurred_at과 이전 오류 메타데이터는 변경하지 않으며 새 노출 기록도 만들지 않는다. 함수는 HTTP를 호출하지 않는다. 반환 후 기존 send_once로 전송할 수 있으며, 다시 401이면 기존 전송 규칙에 따라 BLOCKED로 남아 자동 작업자에게 선택되지 않는다.

선언·시그니처는 routing-doc-sync AST 결과와 대조했다. 복구 대상 제외·임대 경합 재현·요청 내용 보존·롤백·성공 접수·재차 401 차단은 임시 메모리 DB에서 검사했다. 실제 운영 DB와 관리 명령은 이번 검증 범위에 포함하지 않는다.

### finish_impression

참조: `ad-bridge/scripts/impressions/store.py::def finish_impression(reaction_id: str | UUID, *, delivery_state: str, status: str | None=None, reason_code: str | None=None, request_id: str | None=None, lease_token: str | UUID | None=None, next_attempt_at: datetime | None=None, last_error: str | None=None, last_http_status: int | None=None) -> StoredImpression`

선언 구조는 AST 분석으로 확인한다. 상세 동작은 위 역할 및 원본을 참고한다.

### ImpressionNotReady

참조: `ad-bridge/scripts/impressions/store.py::ImpressionNotReady`

접수 완료되지 않은 노출은 판정 조회 대상으로 삼지 않는다.

### get_impression

참조: `ad-bridge/scripts/impressions/store.py::def get_impression(*, decision_id: str | UUID, owner_id: str | UUID) -> StoredImpression`

owner_id로 사용자 소유의 기존 노출만 읽으며 새 기록을 만들지 않는다. 노출 subject_id와 결정 subject_id가 일치하지 않는 기록도 조회 대상으로 삼지 않는다.

### update_result

참조: `ad-bridge/scripts/impressions/store.py::def update_result(*, decision_id: str | UUID, owner_id: str | UUID, reaction_id: str | UUID, status: str, reason_code: str | None, request_id: str | None) -> StoredImpression`

판정만 조건부 갱신한다. 이미 확정된 판정과 전송 정보는 보존한다.
