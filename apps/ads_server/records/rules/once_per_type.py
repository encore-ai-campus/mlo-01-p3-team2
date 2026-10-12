from . import Hold


def check(facts):
    """결정(의 사람)당 반응 유형별로 **한 번만** 인정한다. 인정되는 쪽은 **먼저 접수된 유효한 반응**이다.

    처리 순서가 대표를 정하면 같은 접수 사실에서도 판정이 달라진다(늦게 접수된 노출이 먼저 처리돼 인정되면 제때 도착한 노출이 중복으로 거부되고,
    그 노출에 기댄 클릭의 판정이 바뀐다). 그래서 **먼저 접수된 같은 유형이 아직 처리 전이면 기다린다**: 그쪽이 인정되면 이 반응은 중복이 되고,
    거부되면(유효하지 않았으면) 이 반응이 다음 후보다. 기다림은 실패가 아니라 보류다(앞 단계를 기다리는 것과 같다).
    """
    if facts.reaction_type in facts.accepted_types:
        return "duplicate_type"
    if facts.earlier_unprocessed:
        return Hold("duplicate_type")
    return None
