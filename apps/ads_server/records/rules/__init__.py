"""반응 유효성 규칙 체인(설계 §4.4). 규칙은 파일 하나에 `check(facts) -> 거부 사유 | Hold | None` 하나다. 어떤 규칙을 어떤 순서로 쓸지는 설정(`REACTION_RULES`)이 정한다.

알 수 없는 이름은 **즉시 오류**다(조용히 건너뛰지 않는다 — 규칙이 빠지면 과금이 열린다). 규칙은 DB 를 모른다: 처리 단계가 모은 사실(`RuleInput`)만 본다.
`Hold` 는 "아직 판단할 수 없다"(앞 단계 반응을 기다린다)이고, 거부도 인정도 아니다 — 반응은 `RECEIVED` 로 남아 다시 판정된다.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


class Hold:
    """보류. `reason` 은 기한이 지나면 거부 사유가 될 코드다."""

    def __init__(self, reason):
        self.reason = reason


@dataclass(frozen=True)
class Limits:
    """설정에서 온 기간·허용치(`REACTION_*`). 규칙이 시계나 설정을 직접 읽지 않게 사실과 함께 넘긴다."""

    click_window: timedelta
    display_grace: timedelta
    conversion_window: timedelta
    occurred_at_tolerance: timedelta
    hold: timedelta


@dataclass(frozen=True)
class RuleInput:
    # 이 반응
    media_id: UUID  # 보고한 매체(인증된 키)
    reaction_type: str
    source: str  # `media`(매체가 보고) | `server`(광고 서버가 관측한 클릭)
    reported_subject_id: str | None  # 보고에 실린 사람
    occurred_at: datetime | None  # 매체가 감지한 시각
    received_at: datetime  # 서버 수신 시각(기간 판정의 기준)
    now: datetime  # 판정 시각(보류 기한 계산용)
    # 결정
    decision_exists: bool
    decision_media_id: UUID | None  # 결정을 만든 매체
    ad_was_shown: bool  # 결정에 광고가 있었나
    audience: str | None  # `individual` | `shared`
    decision_subject_id: str | None
    decided_at: datetime | None
    # 판정 단위(개인 슬롯 = 결정, 일괄 슬롯 = 결정·사람)에서 모은 사실
    accepted_types: frozenset  # 이 단위에서 이미 인정된 반응 유형
    # 앞 단계 반응(클릭이면 같은 사람의 노출, 전환이면 같은 사람의 서버 관측 클릭)이 **도착한 시각**들. 인정 여부와 도착 시각을 함께 본다:
    # 기한은 "언제 도착했나"로 판정해야 처리 작업자가 늦게 돈 것이 매체의 잘못이 되지 않고, 기한 뒤에 도착한 전제가 반응을 되살리지도 않는다
    prereq_accepted: tuple  # 인정된(`ACCEPTED`) 앞 단계 반응의 수신 시각
    prereq_waiting: tuple  # 아직 처리 전(`RECEIVED`)인 앞 단계 반응의 수신 시각
    next_display_at: datetime | None  # 같은 표시 단위의 다음 결정 시각(없으면 아직 표시 중)
    campaign_ends_at: datetime | None  # 판정 시점의 캠페인 종료 시각(없으면 계속 진행)
    limits: Limits


from . import ad_shown, campaign_open, click_source, funnel_order, funnel_window, known_decision, occurred_at, once_per_type, same_media, subject  # noqa: E402

_RULES = {
    "known-decision": known_decision.check, "same-media": same_media.check, "ad-shown": ad_shown.check, "click-source": click_source.check,
    "subject": subject.check, "occurred-at": occurred_at.check, "campaign-open": campaign_open.check, "once-per-type": once_per_type.check,
    "funnel-window": funnel_window.check, "funnel-order": funnel_order.check,
}
DEFAULT_RULES = tuple(_RULES)
# 설정과 무관하게 **언제나** 거치는 조건: 과금의 권한·근거(누구의 결정이고 광고가 있었나, 클릭은 서버 관측만, 사람이 하나로 정해짐, 종료 뒤 수신 아님).
# 정책(`REACTION_RULES`)을 바꿔도 이것들은 빠지지 않는다.
MANDATORY_RULES = ("known-decision", "same-media", "ad-shown", "click-source", "subject", "campaign-open")


class UnknownRule(ValueError):
    pass


def run_rules(names, facts):
    """처음 거부·보류한 규칙의 `(규칙 이름, 사유 또는 Hold)`. 모두 통과하면 `None`. **거부가 보류보다 먼저**다(보류는 거부가 없을 때만)."""
    checks = []
    for name in names:
        try:
            checks.append((name, _RULES[name]))
        except KeyError:
            raise UnknownRule(f"알 수 없는 반응 규칙: {name!r} (등록된 것: {sorted(_RULES)})")
    held = None
    for name, check in checks:
        result = check(facts)
        if isinstance(result, Hold):
            held = held or (name, result)  # 첫 보류를 기억하고 뒤의 규칙이 확정 거부를 낼 수 있게 계속 본다
        elif result is not None:
            return name, result
    return held
