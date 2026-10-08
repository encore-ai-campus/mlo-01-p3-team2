"""결정 유스케이스(설계 §4.3~4.4). 후보 조립 → engine → **저장한 뒤에만** 돌려준다(§4.4-12)."""
import random

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from assets.api import asset_url
from engine.api import AdRequest, decide as engine_decide
from foundation.api import errors, is_unique_violation, parse_uuid
from masters import api as masters

from .assemble import assemble
from .models import Decision, Reaction
from .types import ChosenView, DecisionView, ReactionView


def _now(now=None):
    return now if now is not None else timezone.now()


def _view(d):
    chosen = None
    if d.creative_id is not None:
        s = d.snapshot
        chosen = ChosenView(
            owner_id=d.owner_id, campaign_id=d.campaign_id, ad_group_id=d.ad_group_id, creative_id=d.creative_id,
            pricing_unit=d.pricing_unit, bid_amount=d.bid_amount, applied_amount=d.applied_amount, bid_version=d.bid_version,
            policy_version=d.policy_version, bid_id=d.bid_id, bid_policy_id=d.bid_policy_id, title=s["title"], redirect_url=s["redirect_url"], image_name=s["image_name"],
            image_url=asset_url(s["image_name"]),
        )
    return DecisionView(
        decision_id=d.decision_id, media_id=d.media_id, slot_id=d.slot_id, subject_id=d.subject_id, decided_at=d.decided_at,
        chosen=chosen, selection_policy=d.selection_policy, trace=d.trace, candidate_count=d.candidate_count,
        rejected_counts=d.rejected_counts,
    )


def decide(media_id, slot_id, subject_id=None, context=None, now=None, rng=None):
    """광고 한 건을 고르고 결정으로 저장한다. 후보가 없어도(광고 없음) 한 건으로 남긴다.

    저장이 실패하면 예외가 그대로 나가 `decision_id` 가 응답으로 나가지 않는다.

    계약 C1의 응답 규칙(DRD D-1): **없는 슬롯·다른 매체의 슬롯은 404**(구분해 알리지 않는다), **매체가 비활성이면 403**(결정 없음),
    **활성 매체의 비활성 슬롯은 광고 없음으로 기록**한다. `context` 는 호출한 쪽(경계)이 검증한 값을 그대로 저장한다.
    """
    now = _now(now)
    media_id, slot_id = parse_uuid(media_id, "매체"), parse_uuid(slot_id, "게재 위치")
    try:
        slot = masters.get_slot(slot_id)
    except errors.NotFound:
        slot = None
    if slot is None or slot.media_id != media_id:
        raise errors.NotFound("게재 위치를 찾을 수 없습니다.")  # 다른 매체의 슬롯은 없는 것과 같다
    if not slot.media_is_active:
        raise errors.Forbidden("이 매체는 비활성입니다.")
    candidates, facts_by_creative = assemble(slot, now) if slot.is_active else ([], {})  # 꺼진 슬롯: 후보 없이 '광고 없음'으로 기록
    result = engine_decide(
        candidates, AdRequest(slot_id=slot_id, now=now, subject_id=subject_id), rng or random.Random(),  # nosec B311 — 동점 광고를 고르게 노출하려는 추첨이다. 보안 값(키·토큰)을 만들지 않는다
        policy=settings.ADS_SELECTION_POLICY, filters=tuple(settings.ADS_ENGINE_FILTERS),
    )
    chosen = result.selection.chosen
    trace = result.selection.trace if slot.is_active else {**result.selection.trace, "slot_inactive": True}
    values = {}
    if chosen is not None:
        fact = facts_by_creative[chosen.creative_id]
        values = dict(
            owner_id=fact.owner_id, campaign_id=chosen.campaign_id, ad_group_id=chosen.ad_group_id, creative_id=chosen.creative_id,
            pricing_unit=chosen.pricing_unit, bid_amount=chosen.bid_amount, applied_amount=chosen.applied_amount,
            bid_version=chosen.bid_version, policy_version=chosen.policy_version,
            bid_id=fact.bid_id, bid_policy_id=slot.policy.bid_policy_id,  # 판정에 쓴 바로 그 버전 행
            snapshot={"title": fact.title, "redirect_url": fact.redirect_url, "image_name": fact.image_name},
        )
    with transaction.atomic():
        decision = Decision.objects.create(
            media_id=media_id, slot_id=slot_id, subject_id=subject_id, context=context or {}, decided_at=now,
            selection_policy=result.selection.trace.get("policy", settings.ADS_SELECTION_POLICY),
            trace=trace, candidate_count=result.considered, rejected_counts=result.rejected, **values,
        )
    return _view(decision)


def get_decision(media_id, decision_id):
    """결정 조회. **그 결정을 만든 매체만** 볼 수 있고, 아니면 없는 것과 같다(404)."""
    try:
        d = Decision.objects.get(decision_id=parse_uuid(decision_id, "결정"), media_id=parse_uuid(media_id, "매체"))
    except (Decision.DoesNotExist, errors.NotFound):  # 형식이 틀린 ID·없는 결정·다른 매체의 결정은 같은 응답이다
        raise errors.NotFound("결정을 찾을 수 없습니다.")
    return _view(d)


# ---------------------------------------------------------------- 반응 수신함 (C1 PUT /reactions)

def _reaction_view(r):
    return ReactionView(
        reaction_id=r.reaction_id, decision_id=r.decision_id, type=r.type, occurred_at=r.occurred_at, received_at=r.received_at,
        status=r.status, reason_code=r.reason_code,
    )


def receive_reaction(media_id, decision_id, reaction_id, reaction_type, occurred_at, raw, now=None):
    """반응을 수신함에 저장한다. 반환: `(ReactionView, created)`. **호출한 쪽이 바깥 트랜잭션을 열고, 커밋된 뒤에만 2xx 를 보낸다.**

    멱등(최소 한 번 전달 + 중복 제거): (매체, `reaction_id`) 가 같고 내용(결정·유형·감지 시각)도 같으면 처음 행을 돌려주고(`created=False`),
    내용이 다르면 409. 다른 매체가 같은 `reaction_id` 를 써도 충돌하지 않는다. 결정이 있는지·내 것인지는 **여기서 묻지 않는다** —
    일단 받고 처리 단계가 거부한다(접수한 반응은 지우지 않는다).
    입력(유형·시각·UUID 형식)은 경계가 검증해서 넘긴다.
    """
    now = _now(now)
    media_id, decision_id, reaction_id = parse_uuid(media_id, "매체"), parse_uuid(decision_id, "결정"), parse_uuid(reaction_id, "반응")
    wanted = (decision_id, reaction_type, occurred_at)

    def existing():
        return Reaction.objects.filter(media_id=media_id, reaction_id=reaction_id).first()

    def same_or_conflict(row):
        if (row.decision_id, row.type, row.occurred_at) != wanted:
            raise errors.Conflict("같은 reaction_id 로 다른 내용이 이미 접수되었습니다.")
        return _reaction_view(row), False

    row = existing()
    if row is not None:  # 재시도(가장 흔한 경로)는 쓰기 없이 끝난다
        return same_or_conflict(row)
    try:
        with transaction.atomic():  # 안전망: 동시에 같은 키가 들어오면 유일 제약이 한쪽만 통과시킨다
            row = Reaction.objects.create(
                media_id=media_id, reaction_id=reaction_id, decision_id=decision_id, type=reaction_type, occurred_at=occurred_at,
                received_at=now, raw=raw,
            )
    except IntegrityError as error:
        if not is_unique_violation(error):  # 유일 제약이 아닌 이유(CHECK 등)는, 같은 키의 행이 있어도 숨기지 않는다
            raise
        row = existing()
        if row is None:
            raise
        return same_or_conflict(row)
    return _reaction_view(row), True


def get_reaction(media_id, decision_id, reaction_id):
    """반응 조회. **이 매체가 보고했고 이 결정 아래에 있는 것만** 보이고, 아니면 없는 것과 같다(404)."""
    try:
        r = Reaction.objects.get(
            media_id=parse_uuid(media_id, "매체"), decision_id=parse_uuid(decision_id, "결정"), reaction_id=parse_uuid(reaction_id, "반응")
        )
    except (Reaction.DoesNotExist, errors.NotFound):
        raise errors.NotFound("반응을 찾을 수 없습니다.")
    return _reaction_view(r)
