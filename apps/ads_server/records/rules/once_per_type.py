def check(facts):
    """결정당 반응 유형별로 **한 번만** 인정한다."""
    return "duplicate_type" if facts.reaction_type in facts.accepted_types else None
