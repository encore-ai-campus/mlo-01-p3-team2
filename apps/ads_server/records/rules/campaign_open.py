def check(facts):
    """캠페인 종료 전에 **수신한** 반응만 인정한다(종료 뒤 과금 없음 — 종료는 확정된 사실). 종료 시각은 판정 시점의 값이라 연장이 반영된다."""
    ends_at = facts.campaign_ends_at
    return "campaign_ended" if facts.decision_exists and ends_at is not None and facts.received_at >= ends_at else None
