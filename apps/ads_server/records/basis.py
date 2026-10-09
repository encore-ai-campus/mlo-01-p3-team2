"""판정 근거(`Reaction.basis`) 만들기(설계 §10 "판정 근거 기록").

`ACCEPTED`/`REJECTED` 를 정하는 **같은 트랜잭션**에서 `processing._finish` 가 한 번 쓰고 이후 바꾸지 않는다. 보류(`Hold`)는 판정이 아니므로 만들지 않는다.
목적은 분쟁·감사 때 이후에 쌓이거나 바뀐 데이터(새로 도착한 노출, 연장된 캠페인, 바뀐 설정)로 다시 계산하지 않고 **그때의 판정을 그대로 설명**하는 것이다.
값은 판정에 쓴 사실(`RuleInput`)에서 그대로 옮긴다 — 여기서 새로 조회하거나 계산하지 않는다. JSON 이므로 UUID·시각은 문자열(UTC ISO 8601)이다.
"""
SCHEMA_VERSION = 1


def _iso(value):
    return None if value is None else value.isoformat()


def build(facts, rule, reason, person, judged_at):
    """판정 근거. `rule`·`reason` 은 거부일 때만 있다(인정이면 `None`)."""
    limits = facts.limits
    return {
        "v": SCHEMA_VERSION,
        "verdict": {"rule": rule, "reason": reason},
        "judged_at": _iso(judged_at),
        "person": person,
        "audience": facts.audience,
        "decided_at": _iso(facts.decided_at),
        "campaign_ends_at": _iso(facts.campaign_ends_at),
        "reaction": {
            "type": facts.reaction_type, "source": facts.source, "reported_subject_id": facts.reported_subject_id,
            "occurred_at": _iso(facts.occurred_at), "received_at": _iso(facts.received_at),
        },
        "limits_seconds": {
            "click_window": limits.click_window.total_seconds(), "display_grace": limits.display_grace.total_seconds(),
            "conversion_window": limits.conversion_window.total_seconds(), "occurred_at_tolerance": limits.occurred_at_tolerance.total_seconds(),
            "hold": limits.hold.total_seconds(),
        },
        **facts.evidence,
    }
