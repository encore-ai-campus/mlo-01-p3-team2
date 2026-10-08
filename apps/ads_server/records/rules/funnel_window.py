def check(facts):
    """기간: 클릭은 결정 후 `click_window` 안이고 **광고가 표시 중일 때**(같은 표시 단위의 다음 결정 + 여유 안), 전환은 클릭 후 `conversion_window` 안이다.

    판단에 필요한 앞 단계 반응이 아직 없으면 판단하지 않는다(`funnel-order` 의 몫).
    """
    if not facts.decision_exists:
        return None
    limits = facts.limits
    if facts.reaction_type == "CLICK":
        if facts.received_at > facts.decided_at + limits.click_window:
            return "window_expired"
        if facts.next_display_at is not None and facts.received_at > facts.next_display_at + limits.display_grace:
            return "display_ended"
    elif facts.reaction_type == "CONVERSION" and facts.click_received_at is not None:
        if facts.received_at > facts.click_received_at + limits.conversion_window:
            return "window_expired"
    return None
