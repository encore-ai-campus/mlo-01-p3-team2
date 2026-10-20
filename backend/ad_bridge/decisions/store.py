"""개인 결정의 소유권과 사용자 없는 공유 결정을 불변 기록으로 저장한다."""

from datetime import datetime
import re
from uuid import UUID

from ..api.types import Decision


def _uuid(value: str | UUID) -> UUID:
    if not isinstance(value, (str, UUID)):
        raise ValueError("식별자는 UUID여야 합니다.")
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as error:
        raise ValueError("식별자는 UUID여야 합니다.") from error


def _utc_time(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value
    ):
        raise ValueError("시각은 UTC Z 형식이어야 합니다.")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("시각은 유효한 UTC 시각이어야 합니다.") from error


def remember_decision(
    decision: Decision, subject_id: str | UUID | None = None,
    *, owner_id: str | UUID | None = None,
) -> None:
    from ..models import IssuedDecision

    if decision.audience == "individual":
        owner, subject = _uuid(owner_id), _uuid(subject_id)
    elif decision.audience == "shared":
        if owner_id is not None or subject_id is not None:
            raise ValueError("공유 결정에는 소유자와 사용자 가명을 저장하지 않습니다.")
        owner, subject = None, None
    else:
        raise ValueError("지원하지 않는 광고 슬롯 종류입니다.")
    values = {
        "audience": decision.audience,
        "owner_id": owner,
        "subject_id": subject,
        "slot_id": _uuid(decision.slot_id),
        "decided_at": _utc_time(decision.decided_at),
        "has_ad": decision.ad is not None,
    }
    record, created = IssuedDecision.objects.get_or_create(
        decision_id=_uuid(decision.decision_id), defaults=values
    )
    # 같은 결정의 내부 소유자와 발급 당시 가명 모두 불변으로 유지한다.
    if not created and any(getattr(record, name) != value for name, value in values.items()):
        raise ValueError("이미 저장된 광고 결정과 일치하지 않습니다.")


def is_shared_decision(decision_id):
    """뷰에서 공유 결정의 사용자 가명 전달 여부를 선택한다. 소유권 검사는 노출 저장소가 수행한다."""
    from ..models import IssuedDecision
    return IssuedDecision.objects.filter(pk=_uuid(decision_id), audience="shared").exists()
