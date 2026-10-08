"""반응 판정에 쓰는 사실을 모은다(읽기 전용). **판정은 하지 않는다** — 규칙(`records/rules/`)이 이 사실만 보고 정한다.

판정 단위의 사람: 개인(`individual`) 슬롯은 결정의 `subject_id` 하나, 일괄(`shared`) 슬롯은 보고에 실린 사람이다(없으면 `None` —
`subject` 규칙이 `subject_required` 로 거부한다). 질의는 필요한 만큼만 한다: 결정 1, 캠페인 종료 1, 인정된 유형 1, (클릭) 노출 상태 1·다음 결정 1, (전환) 클릭 상태 1.
"""
from datetime import timedelta

from django.conf import settings
from django.db.models import Q

from campaigns import api as campaigns
from masters import api as masters

from .models import Decision, Reaction, ReactionSource, ReactionStatus, ReactionType
from .rules import Limits, RuleInput


def limits():
    return Limits(
        click_window=timedelta(seconds=settings.REACTION_CLICK_WINDOW_SECONDS),
        display_grace=timedelta(seconds=settings.REACTION_DISPLAY_GRACE_SECONDS),
        conversion_window=timedelta(seconds=settings.REACTION_CONVERSION_WINDOW_SECONDS),
        occurred_at_tolerance=timedelta(seconds=settings.REACTION_OCCURRED_AT_TOLERANCE_SECONDS),
        hold=timedelta(seconds=settings.REACTION_HOLD_SECONDS),
    )


def person_of(decision, reported_subject_id):
    """판정 단위의 사람. 개인 슬롯은 결정의 사람, 일괄 슬롯은 보고된 사람(없으면 `None`)."""
    return decision.subject_id if decision.audience == masters.Audience.INDIVIDUAL else reported_subject_id


def _same_person(qs, decision, person):
    """판정 전의 반응(`person_id` 가 아직 없다)을 사람으로 좁힌다. 개인 슬롯은 보고에 사람이 없거나 결정의 사람과 같은 것만 이 결정의 사람 몫이다."""
    if decision.audience == masters.Audience.SHARED:
        return qs.filter(subject_id=person)
    return qs.filter(Q(subject_id__isnull=True) | Q(subject_id=decision.subject_id))


def _arrivals(qs):
    """앞 단계 후보 반응의 수신 시각: (인정된 것들, 처리 전인 것들). 거부된 것은 없는 것과 같다 — 질의 한 번."""
    accepted, waiting = [], []
    for status, received_at in qs.filter(status__in=[ReactionStatus.ACCEPTED, ReactionStatus.RECEIVED]).values_list("status", "received_at"):
        (accepted if status == ReactionStatus.ACCEPTED else waiting).append(received_at)
    return tuple(sorted(accepted)), tuple(sorted(waiting))


def next_display_at(decision):
    """같은 표시 단위의 **다음 결정**이 만들어진 시각(없으면 `None` = 아직 표시 중). 개인 슬롯은 (슬롯, 사람), 일괄 슬롯은 슬롯이다."""
    later = Decision.objects.filter(slot_id=decision.slot_id, subject_id=decision.subject_id) if decision.subject_id else Decision.objects.filter(
        slot_id=decision.slot_id, subject_id__isnull=True,
    )
    later = later.filter(Q(decided_at__gt=decision.decided_at) | Q(decided_at=decision.decided_at, decision_id__gt=decision.decision_id))
    return later.order_by("decided_at", "decision_id").values_list("decided_at", flat=True).first()


def gather(row, decision, now):
    """`Reaction` 하나와 그 결정(없으면 `None`)에 대한 `RuleInput`."""
    common = dict(
        media_id=row.media_id, reaction_type=row.type, source=row.source, reported_subject_id=row.subject_id, occurred_at=row.occurred_at,
        received_at=row.received_at, now=now, limits=limits(),
    )
    if decision is None:
        return RuleInput(
            **common, decision_exists=False, decision_media_id=None, ad_was_shown=False, audience=None, decision_subject_id=None, decided_at=None,
            accepted_types=frozenset(), prereq_accepted=(), prereq_waiting=(), next_display_at=None, campaign_ends_at=None,
        )
    person = person_of(decision, row.subject_id)
    accepted = frozenset()
    if person is not None:
        accepted = frozenset(
            Reaction.objects.filter(decision_id=decision.decision_id, person_id=person, status=ReactionStatus.ACCEPTED).values_list("type", flat=True)
        )
    prereq_accepted = prereq_waiting = ()
    next_at = None
    if decision.creative_id is not None and person is not None:
        if row.type == ReactionType.CLICK:
            prereq_accepted, prereq_waiting = _arrivals(_same_person(Reaction.objects.filter(decision_id=decision.decision_id, type=ReactionType.IMPRESSION), decision, person))
            next_at = next_display_at(decision)
        elif row.type == ReactionType.CONVERSION:
            clicks = Reaction.objects.filter(decision_id=decision.decision_id, type=ReactionType.CLICK, source=ReactionSource.SERVER)
            prereq_accepted, prereq_waiting = _arrivals(_same_person(clicks, decision, person))
    ends = campaigns.campaign_end_times([decision.campaign_id]).get(decision.campaign_id) if decision.campaign_id is not None else None
    return RuleInput(
        **common, decision_exists=True, decision_media_id=decision.media_id, ad_was_shown=decision.creative_id is not None,
        audience=decision.audience, decision_subject_id=decision.subject_id, decided_at=decision.decided_at, accepted_types=accepted,
        prereq_accepted=prereq_accepted, prereq_waiting=prereq_waiting, next_display_at=next_at, campaign_ends_at=ends,
    )
