"""캠페인 도메인 오류. 계약(console.openapi.yaml)의 `code` 와 같은 값을 쓴다. 공통 어휘는 foundation 의 ApiError 를 잇는다."""
from foundation.api import errors as base


class CampaignEnded(base.Conflict):
    """종료(기간 경과 또는 조기 종료)된 캠페인은 어떤 값도 바꿀 수 없다."""

    code, title = "ended", "종료된 캠페인은 수정할 수 없습니다"


class CampaignSuspended(base.Conflict):
    code, title = "suspended", "관리자가 중단한 캠페인은 상태를 바꿀 수 없습니다"


class NotSuspended(base.Conflict):
    code, title = "not_suspended", "중단된 캠페인에만 재검토를 요청할 수 있습니다"


class ReviewPending(base.Conflict):
    code, title = "review_pending", "이미 대기 중인 재검토 요청이 있습니다"


class UnitImmutable(base.Conflict):
    code, title = "unit_immutable", "과금 단위는 바꿀 수 없습니다"


class UnitMismatch(base.InvalidRequest):
    code, title = "unit_mismatch", "게재 위치의 과금 단위가 광고그룹과 다릅니다"


class LimitExceeded(base.Conflict):
    code, title = "limit_exceeded", "허용된 개수 또는 용량을 넘었습니다"


class InvalidTransition(base.Conflict):
    code, title = "invalid_transition", "현재 상태에서는 할 수 없는 동작입니다"
