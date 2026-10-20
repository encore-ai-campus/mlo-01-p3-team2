def check(facts):
    """판정 단위의 사람이 하나로 정해져야 한다. 일괄 슬롯은 보고에 사람이 있어야 하고, 개인 슬롯은 보고한 사람이 있다면 결정의 사람과 같아야 한다."""
    if not facts.decision_exists:
        return None
    if facts.audience == "shared":
        return "subject_required" if facts.reported_subject_id is None else None
    if facts.reported_subject_id is not None and facts.reported_subject_id != facts.decision_subject_id:
        return "subject_mismatch"
    return None
