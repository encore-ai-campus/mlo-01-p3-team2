def check(facts):
    """결정을 만든 매체만 그 결정의 반응을 보고할 수 있다. 결정이 없으면 이 규칙은 판단하지 않는다(`known-decision` 의 몫)."""
    return "media_mismatch" if facts.decision_exists and facts.decision_media_id != facts.media_id else None
