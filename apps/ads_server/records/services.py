"""결정 유스케이스(설계 §4.3~4.4). 후보 조립 → engine → **저장한 뒤에만** 돌려준다(§4.4-12)."""
import random

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from assets.api import asset_url
from engine.api import AdRequest, decide as engine_decide
from foundation.api import errors, parse_uuid
from masters import api as masters

from .assemble import assemble
from .models import Decision
from .types import ChosenView, DecisionView


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
