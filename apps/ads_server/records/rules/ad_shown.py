def check(facts):
    """광고가 없던 결정(광고 없음)에는 노출·클릭·전환이 있을 수 없다."""
    return "no_ad_shown" if facts.decision_exists and not facts.ad_was_shown else None
