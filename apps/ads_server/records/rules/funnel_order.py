from . import Hold


def check(facts):
    """순서: 클릭은 같은 사람의 **인정된 노출**이, 전환은 같은 사람의 **인정된 클릭**이 먼저 있어야 한다.

    앞 단계가 아직 없거나 처리 중이면 거부하지 않고 **보류**한다(매체의 재시도 큐 때문에 노출이 클릭보다 늦게 도착할 수 있다).
    기다리는 시간이 `hold` 를 넘으면 `missing_prerequisite`. 인정 전의 `RECEIVED` 는 "있음"으로 치지 않는다 —
    그래야 인정된 전환 뒤에는 항상 인정된 클릭이 있다.
    """
    if not facts.decision_exists:
        return None
    needed = {"CLICK": facts.impression_state, "CONVERSION": facts.click_state}.get(facts.reaction_type, "ACCEPTED")
    if needed == "ACCEPTED":
        return None
    if facts.now - facts.received_at >= facts.limits.hold:
        return "missing_prerequisite"
    return Hold("missing_prerequisite")
