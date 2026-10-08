"""반응 유효성 규칙 체인(설계 §4.4). 규칙은 파일 하나에 `check(facts) -> 거부 사유 | None` 하나다. 어떤 규칙을 어떤 순서로 쓸지는 설정(`REACTION_RULES`)이 정한다.

알 수 없는 이름은 **즉시 오류**다(조용히 건너뛰지 않는다 — 규칙이 빠지면 과금이 열린다). 규칙은 DB 를 모른다: 처리 단계가 모은 사실(`RuleInput`)만 본다.
"""
from dataclasses import dataclass
from uuid import UUID

from . import ad_shown, known_decision, once_per_type, same_media


@dataclass(frozen=True)
class RuleInput:
    media_id: UUID  # 보고한 매체(인증된 키)
    reaction_type: str
    decision_exists: bool
    decision_media_id: UUID | None  # 결정을 만든 매체
    ad_was_shown: bool  # 결정에 광고가 있었나
    accepted_types: frozenset  # 이 결정에서 이미 인정된 반응 유형


DEFAULT_RULES = ("known-decision", "same-media", "ad-shown", "once-per-type")
_RULES = {
    "known-decision": known_decision.check, "same-media": same_media.check, "ad-shown": ad_shown.check, "once-per-type": once_per_type.check,
}


class UnknownRule(ValueError):
    pass


def run_rules(names, facts):
    """처음 거부한 규칙의 `(규칙 이름, 사유)`. 모두 통과하면 `None`."""
    checks = []
    for name in names:
        try:
            checks.append((name, _RULES[name]))
        except KeyError:
            raise UnknownRule(f"알 수 없는 반응 규칙: {name!r} (등록된 것: {sorted(_RULES)})")
    for name, check in checks:
        reason = check(facts)
        if reason is not None:
            return name, reason
    return None
