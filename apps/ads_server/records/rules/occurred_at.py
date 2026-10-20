def check(facts):
    """매체가 보낸 감지 시각(노출·전환)이 말이 되는 범위에 있어야 한다: 결정 시각보다 허용 오차 넘게 앞서지 않고, 수신 시각보다 허용 오차 넘게 미래가 아니다.

    **양쪽 모두 허용 오차를 둔다**: 매체 시계가 서버보다 조금 느리거나 시각을 초 단위로 자르면, 결정 직후의 정상 노출이 "결정보다 앞선" 시각으로 보인다
    (부하 시험에서 같은 초 안의 노출이 전부 거부되는 것으로 드러났다). 서버가 관측한 클릭은 서버 시각이라 해당 없다.
    """
    if not facts.decision_exists or facts.source == "server" or facts.reaction_type == "CLICK":
        return None
    tolerance = facts.limits.occurred_at_tolerance
    if facts.occurred_at < facts.decided_at - tolerance or facts.occurred_at > facts.received_at + tolerance:
        return "invalid_occurred_at"
    return None
