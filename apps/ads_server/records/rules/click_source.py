def check(facts):
    """클릭은 **광고 서버가 관측한 것만** 인정한다(설계 §10 "클릭 출처"). 매체가 보고한 `CLICK` 은 접수만 하고 거부한다 — 과금·전환의 전제에 쓰지 않는다."""
    return "click_not_reported" if facts.decision_exists and facts.reaction_type == "CLICK" and facts.source != "server" else None
