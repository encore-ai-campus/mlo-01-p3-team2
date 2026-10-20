from datetime import timedelta

from . import Hold


def check(facts):
    """순서: 클릭은 같은 사람의 **인정된 노출**이, 전환은 같은 사람의 **인정된 클릭**이 먼저 있어야 한다.

    "먼저"는 앞 단계 반응이 **도착한 시각**으로 판정한다(처리 시각이 아니다):
    - 클릭: 노출이 클릭 접수 시각 + `hold` 안에 도착했어야 한다(매체의 재시도 큐 때문에 노출이 클릭보다 늦게 도착할 수 있다).
    - 전환: 클릭이 전환 접수 시각**까지**(같은 시각 포함) 도착했어야 한다 — 클릭은 서버가 즉시 관측하므로 전환보다 늦게 생긴 클릭은 "클릭을 거친" 전환이 아니다.

    제때 도착한 앞 단계가 인정돼 있으면 통과, 제때 도착했지만 아직 처리 전이면 **보류**(처리가 늦은 것이 거부 사유가 되지 않는다),
    제때 도착한 것이 없으면 `hold` 동안 기다리다가 `missing_prerequisite`. 인정 전의 `RECEIVED` 는 통과 근거가 아니다 —
    그래야 인정된 전환 뒤에는 항상 인정된 클릭이 있다.
    """
    if not facts.decision_exists or facts.reaction_type == "IMPRESSION":
        return None
    hold = facts.limits.hold
    limit = facts.received_at + (hold if facts.reaction_type == "CLICK" else timedelta(0))
    if any(arrived <= limit for arrived in facts.prereq_accepted):
        return None
    if any(arrived <= limit for arrived in facts.prereq_waiting):
        return Hold("missing_prerequisite")
    if facts.now - facts.received_at >= hold:
        return "missing_prerequisite"
    return Hold("missing_prerequisite")
