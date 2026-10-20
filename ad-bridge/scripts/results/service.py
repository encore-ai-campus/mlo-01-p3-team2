"""접수된 개인 노출의 판정을 조회하고 기존 기록에 반영한다."""

from datetime import datetime
from uuid import UUID

from ..api.errors import AdsResponseError
from ..impressions.store import ImpressionNotReady, StoredImpression


def refresh_result(*, client, store, decision_id: str | UUID,
                   owner_id: str | UUID) -> StoredImpression:
    """내부 소유자로 권한을 확인하고 저장된 광고 가명으로 결과를 대조한다."""
    record = store.get_impression(decision_id=decision_id, owner_id=owner_id)
    if record.delivery_state != "ACKNOWLEDGED":
        raise ImpressionNotReady("접수 완료된 노출만 조회할 수 있습니다.")
    result = client.get_reaction(decision_id=record.decision_id, reaction_id=record.reaction_id)
    # 경로의 ID뿐 아니라 저장된 사용자와 최초 발생 시각까지 같은 노출인지 확인한다.
    if (result.decision_id != record.decision_id or result.reaction_id != record.reaction_id
            or result.subject_id != record.subject_id or result.type != "IMPRESSION"
            or datetime.fromisoformat(result.occurred_at) != datetime.fromisoformat(record.occurred_at)):
        raise AdsResponseError("조회한 반응이 저장된 노출과 일치하지 않습니다.", request_id=result.request_id)
    return store.update_result(
        decision_id=record.decision_id, owner_id=owner_id, reaction_id=record.reaction_id,
        status=result.status, reason_code=result.reason_code, request_id=result.request_id,
    )
