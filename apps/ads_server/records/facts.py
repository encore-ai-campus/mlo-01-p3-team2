"""반응 판정에 쓰는 사실을 모은다(읽기 전용). **판정은 하지 않는다** — 규칙(`records/rules/`)이 이 사실만 보고 정한다.

판정 단위의 사람: 개인(`individual`) 슬롯은 결정의 `subject_id` 하나, 일괄(`shared`) 슬롯은 보고에 실린 사람이다(없으면 `None` —
`subject` 규칙이 `subject_required` 로 거부한다). 질의는 필요한 만큼만 한다: 결정 1, 캠페인 종료 1, 인정된 유형 1, (클릭) 노출 상태 1·교체 신호(이후 결정의 첫 노출) 1, (전환) 클릭 상태 1.

**판정 사실로 읽는 모든 반응은 `scoped_reactions` 를 거친다**(설계 §10 "판정 사실의 범위"). 접수는 존재를 알리지 않으려고 남의 결정에 대한 보고도 저장하므로,
범위가 없으면 다른 매체의 보고가 이 결정의 판정을 바꾼다. 범위는 **접수 때 정해지는 값**(`media_id`·보고된 `subject_id`)으로만 건다 — 판정 상태로 거르면 처리 순서에 따라 결과가 흔들린다.
`tests/boundaries/test_judgment_scope.py` 가 이 파일의 `Reaction.objects` 가 `scoped_reactions` 안에만 있음을 소스로 확인한다.
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


def scoped_reactions(decision, decision_ids=None):
    """판정 사실로 읽을 수 있는 반응의 **유일한 입구**: 결정 소유 매체가 보낸 반응으로 한정한다.

    - `decision_ids` 가 없으면 이 결정의 반응, 있으면 그 결정들(같은 표시 단위의 이후 결정 등)의 반응이다. 어느 쪽이든 `media_id` 는 결정의 매체다.
    - 개인 슬롯은 보고된 사람이 없거나 결정의 사람과 같은 것만 쓴다(다른 사람이라고 보고한 반응은 이 사람의 판정에 쓰지 않는다).
      일괄 슬롯은 보고된 사람이 사람마다 다르므로 여기서 거르지 않는다(필요한 쪽이 `_of_person` 으로 좁힌다).
    """
    qs = Reaction.objects.filter(media_id=decision.media_id)
    qs = qs.filter(decision_id=decision.decision_id) if decision_ids is None else qs.filter(decision_id__in=decision_ids)
    if decision.audience == masters.Audience.INDIVIDUAL:
        qs = qs.filter(Q(subject_id__isnull=True) | Q(subject_id=decision.subject_id))
    return qs


def _of_person(qs, decision, person):
    """일괄 슬롯의 반응을 판정 단위의 사람으로 좁힌다(개인 슬롯은 `scoped_reactions` 가 이미 좁혔다)."""
    return qs.filter(subject_id=person) if decision.audience == masters.Audience.SHARED else qs


def _arrivals(qs):
    """앞 단계 후보 반응의 수신 시각: (인정된 것들, 처리 전인 것들, 근거 목록 둘). 거부된 것은 없는 것과 같다 — 질의 한 번.

    근거 목록은 판정 근거(`basis`)에 남길 `inbox_id`·수신 시각이다. **인정된 것**은 (결정, 사람, 유형)당 인정 1건 유일 제약 때문에 최대 하나라 상한 없이 항상 남기고,
    **처리 전인 것**은 매체가 얼마든지 보낼 수 있으므로 `BASIS_LIST_MAX` 개까지만 남기고 총 개수를 따로 센다.
    """
    accepted, waiting, accepted_refs, waiting_refs = [], [], [], []
    for inbox_id, status, received_at in qs.filter(status__in=[ReactionStatus.ACCEPTED, ReactionStatus.RECEIVED]).order_by("received_at", "inbox_id").values_list(
        "inbox_id", "status", "received_at",
    ):
        ref = {"inbox_id": str(inbox_id), "received_at": received_at.isoformat()}
        if status == ReactionStatus.ACCEPTED:
            accepted.append(received_at)
            accepted_refs.append(ref)
        else:
            waiting.append(received_at)
            waiting_refs.append(ref)
    return tuple(sorted(accepted)), tuple(sorted(waiting)), accepted_refs, waiting_refs


BASIS_LIST_MAX = 20


def _evidence(accepted_refs, waiting_refs, signal):
    """판정 근거(`basis`)에 남길 출처. 키는 항상 같다(없으면 `None`·빈 목록)."""
    return {
        "prerequisite_accepted": accepted_refs[0] if accepted_refs else None,  # 인정된 앞 단계 반응(유일 제약으로 최대 1개)
        "prerequisites_waiting": waiting_refs[:BASIS_LIST_MAX], "prerequisites_waiting_count": len(waiting_refs), "prerequisites_waiting_limit": BASIS_LIST_MAX,
        "display_signal": None if signal is None else {"received_at": signal[0].isoformat(), "inbox_id": str(signal[1])},
    }


def display_signal(decision):
    """이 광고가 화면에서 교체된 신호: 같은 표시 단위의 **이후 결정 중 처음으로 노출이 도착한 반응**의 `(received_at, inbox_id)`. 없으면 `None` = 아직 표시 중.

    표시 단위는 개인 슬롯이면 (슬롯, 사람), 일괄 슬롯이면 슬롯이다(같은 매체의 누구의 노출이든 교체 신호). 노출은 **판정 결과와 무관하게 접수된 것**을 쓴다.
    결정이 만들어진 시각은 쓰지 않는다: 매체가 새 결정의 응답을 받지 못해 화면에 적용하지 못했다면 기존 광고는 계속 보이는데, 생성 시각을
    쓰면 그 광고의 클릭이 `display_ended` 로 거부된다. 노출이 없는 이후 결정은 무시한다 — 끝내 노출이 오지 않으면 "결정 후 300초" 상한이 막는다.
    다른 매체가 보낸 노출, 개인 슬롯에서 다른 사람이라고 보고된 노출은 신호가 아니다(`scoped_reactions`). 질의 한 번(이후 결정을 부분 질의로 묶는다).
    """
    later = Decision.objects.filter(slot_id=decision.slot_id, subject_id=decision.subject_id) if decision.subject_id else Decision.objects.filter(
        slot_id=decision.slot_id, subject_id__isnull=True,
    )
    later = later.filter(Q(decided_at__gt=decision.decided_at) | Q(decided_at=decision.decided_at, decision_id__gt=decision.decision_id))
    first = scoped_reactions(decision, later.values("decision_id")).filter(type=ReactionType.IMPRESSION).order_by("received_at", "inbox_id").values_list("received_at", "inbox_id").first()
    return first


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
            evidence=_evidence([], [], None),
        )
    person = person_of(decision, row.subject_id)
    accepted = frozenset()
    if person is not None:
        accepted = frozenset(
            scoped_reactions(decision).filter(person_id=person, status=ReactionStatus.ACCEPTED).values_list("type", flat=True)
        )
    prereq_accepted = prereq_waiting = ()
    accepted_refs, waiting_refs, signal = [], [], None
    if decision.creative_id is not None and person is not None:
        if row.type == ReactionType.CLICK:
            prereq_accepted, prereq_waiting, accepted_refs, waiting_refs = _arrivals(_of_person(scoped_reactions(decision).filter(type=ReactionType.IMPRESSION), decision, person))
            signal = display_signal(decision)
        elif row.type == ReactionType.CONVERSION:
            clicks = scoped_reactions(decision).filter(type=ReactionType.CLICK, source=ReactionSource.SERVER)
            prereq_accepted, prereq_waiting, accepted_refs, waiting_refs = _arrivals(_of_person(clicks, decision, person))
    ends = campaigns.campaign_end_times([decision.campaign_id]).get(decision.campaign_id) if decision.campaign_id is not None else None
    return RuleInput(
        **common, decision_exists=True, decision_media_id=decision.media_id, ad_was_shown=decision.creative_id is not None,
        audience=decision.audience, decision_subject_id=decision.subject_id, decided_at=decision.decided_at, accepted_types=accepted,
        prereq_accepted=prereq_accepted, prereq_waiting=prereq_waiting, next_display_at=None if signal is None else signal[0], campaign_ends_at=ends,
        evidence=_evidence(accepted_refs, waiting_refs, signal),
    )
