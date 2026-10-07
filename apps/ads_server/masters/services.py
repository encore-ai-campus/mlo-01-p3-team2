"""masters 의 규칙. 관리자 전용이며 모든 변경은 감사 로그에 남는다(위협 T23)."""
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Subquery

from foundation.api import MAX_AMOUNT, Role, clean_text, errors, parse_uuid, record_audit

from .models import BidPolicy, Media, PricingUnit, Slot
from .types import MediaView, PolicyView, SlotView


def _require_admin(actor):
    if not (getattr(actor, "is_authenticated", False) and actor.is_active and actor.role == Role.ADMIN):
        raise errors.Forbidden("관리자만 할 수 있습니다.")


def _validate_policy(floor, base, cap):
    problems = []
    for pointer, value in (("/floor", floor), ("/base", base), ("/cap", cap)):
        if isinstance(value, bool) or not isinstance(value, int) or not (0 < value <= MAX_AMOUNT):
            problems.append({"pointer": pointer, "message": f"1 이상 {MAX_AMOUNT} 이하의 정수여야 합니다."})
    if problems:
        raise errors.InvalidRequest(errors=problems)
    if not floor <= base <= cap:
        raise errors.InvalidRequest(errors=[{"pointer": "/base", "message": "하한 ≤ 기준가 ≤ 상한이어야 합니다."}])


def _policy_view(row):
    return PolicyView(
        slot_id=row.slot_id, policy_version=row.policy_version, floor=row.floor_amount, base=row.base_amount,
        cap=row.cap_amount, changed_by=row.changed_by, changed_at=row.changed_at, reason=row.reason,
    )


def _slot_view(slot, policy):
    return SlotView(
        slot_id=slot.slot_id, media_id=slot.media_id, media_name=slot.media.name, media_is_active=slot.media.is_active, name=slot.name,
        pricing_unit=slot.pricing_unit, is_active=slot.is_active, policy=_policy_view(policy),
    )


def _media_view(media):
    return MediaView(media_id=media.media_id, name=media.name, is_active=media.is_active, created_at=media.created_at)


def _audit(actor, action, target, detail=None):
    record_audit(None, action, target=target, actor=actor, detail=detail)


def _current_policies():
    """슬롯마다 최대 버전 행 하나. 질의 한 번으로 슬롯·매체까지 가져온다."""
    latest = BidPolicy.objects.filter(slot=OuterRef("slot")).order_by("-policy_version").values("policy_version")[:1]
    return BidPolicy.objects.select_related("slot", "slot__media").filter(policy_version=Subquery(latest))


def _get_slot(slot_id):
    try:
        return Slot.objects.select_related("media").get(pk=parse_uuid(slot_id, "게재 위치"))
    except Slot.DoesNotExist:
        raise errors.NotFound("게재 위치를 찾을 수 없습니다.")


def create_media(actor, name):
    _require_admin(actor)
    name = clean_text(name, "매체 이름", "/name")
    try:
        with transaction.atomic():
            media = Media.objects.create(name=name)
            _audit(actor, "masters.media_created", ("masters.media", media.media_id), {"name": name})
    except IntegrityError:
        raise errors.Conflict("같은 이름의 매체가 이미 있습니다.")
    return _media_view(media)


def set_media_active(actor, media_id, active):
    _require_admin(actor)
    media_id = parse_uuid(media_id, "매체")
    with transaction.atomic():
        if not Media.objects.filter(pk=media_id).update(is_active=bool(active)):
            raise errors.NotFound("매체를 찾을 수 없습니다.")
        _audit(actor, "masters.media_active_changed", ("masters.media", media_id), {"active": bool(active)})


def create_slot(actor, media_id, name, pricing_unit, floor, base, cap, reason):
    """슬롯과 최초 정책(버전 1)을 한 트랜잭션에 만든다. 따라서 모든 슬롯은 항상 현재 정책을 가진다."""
    _require_admin(actor)
    name = clean_text(name, "게재 위치 이름", "/name")
    reason = clean_text(reason, "사유", "/reason", 200)
    if pricing_unit not in PricingUnit.values:
        raise errors.InvalidRequest(errors=[{"pointer": "/pricing_unit", "message": f"{', '.join(PricingUnit.values)} 중 하나여야 합니다."}])
    _validate_policy(floor, base, cap)
    try:
        with transaction.atomic():
            media = Media.objects.get(pk=parse_uuid(media_id, "매체"))
            slot = Slot.objects.create(media=media, name=name, pricing_unit=pricing_unit)
            policy = BidPolicy.objects.create(
                slot=slot, policy_version=1, floor_amount=floor, base_amount=base, cap_amount=cap,
                changed_by=actor.pk, reason=reason,
            )
            _audit(actor, "masters.slot_created", ("masters.slot", slot.slot_id),
                   {"name": name, "pricing_unit": pricing_unit, "floor": floor, "base": base, "cap": cap, "reason": reason})
    except Media.DoesNotExist:
        raise errors.NotFound("매체를 찾을 수 없습니다.")
    except IntegrityError:
        raise errors.Conflict("이 매체에 같은 이름의 게재 위치가 이미 있습니다.")
    slot.media = media
    return _slot_view(slot, policy)


def _add_version(actor, slot_id, floor, base, cap, reason, expected_version):
    """`expected_version` 이 현재와 다르면 StaleVersion. 호출한 쪽이 바깥 트랜잭션을 연다."""
    slot = _get_slot(slot_id)
    current = BidPolicy.objects.filter(slot=slot).order_by("-policy_version").first()
    if current.policy_version != expected_version:
        raise errors.StaleVersion(f"현재 버전은 {current.policy_version} 입니다.")
    try:
        with transaction.atomic():
            policy = BidPolicy.objects.create(
                slot=slot, policy_version=current.policy_version + 1, floor_amount=floor, base_amount=base,
                cap_amount=cap, changed_by=actor.pk, reason=reason,
            )
    except IntegrityError:  # 다른 DB 로 옮겼을 때의 안전망(SQLite 는 쓰기가 직렬이라 위 검사가 먼저 막는다)
        raise errors.StaleVersion()
    _audit(actor, "masters.policy_added", ("masters.slot", slot.slot_id),
           {"version": policy.policy_version, "floor": floor, "base": base, "cap": cap, "reason": reason,
            "previous": {"floor": current.floor_amount, "base": current.base_amount, "cap": current.cap_amount}})
    return _policy_view(policy)


def add_policy_version(actor, slot_id, floor, base, cap, reason, expected_version):
    _require_admin(actor)
    reason = clean_text(reason, "사유", "/reason", 200)
    _validate_policy(floor, base, cap)
    with transaction.atomic():
        return _add_version(actor, slot_id, floor, base, cap, reason, expected_version)


def add_policy_version_bulk(actor, expected_versions, floor, base, cap, reason):
    """같은 값을 여러 슬롯에 새 버전으로. `expected_versions` = {slot_id: 본 버전}. 하나라도 어긋나면 전부 취소."""
    _require_admin(actor)
    reason = clean_text(reason, "사유", "/reason", 200)
    _validate_policy(floor, base, cap)
    if not expected_versions:
        raise errors.InvalidRequest(errors=[{"pointer": "/slots", "message": "슬롯을 하나 이상 고르세요."}])
    with transaction.atomic():
        return [
            _add_version(actor, slot_id, floor, base, cap, reason, version)
            for slot_id, version in expected_versions.items()
        ]


def set_slot_active(actor, slot_id, active):
    _require_admin(actor)
    slot_id = parse_uuid(slot_id, "게재 위치")
    with transaction.atomic():
        if not Slot.objects.filter(pk=slot_id).update(is_active=bool(active)):
            raise errors.NotFound("게재 위치를 찾을 수 없습니다.")
        _audit(actor, "masters.slot_active_changed", ("masters.slot", slot_id), {"active": bool(active)})


def get_slot(slot_id):
    try:
        row = _current_policies().filter(slot_id=parse_uuid(slot_id, "게재 위치")).get()
    except BidPolicy.DoesNotExist:
        raise errors.NotFound("게재 위치를 찾을 수 없습니다.")
    return _slot_view(row.slot, row)


def list_slots(active_only=True, media_id=None):
    qs = _current_policies()
    if active_only:
        qs = qs.filter(slot__is_active=True, slot__media__is_active=True)
    if media_id is not None:
        qs = qs.filter(slot__media_id=parse_uuid(media_id, "매체"))
    return [_slot_view(row.slot, row) for row in qs.order_by("slot__media__name", "slot__name")]


def get_slots_with_policy(slot_ids):
    """여러 슬롯의 현재 정책을 **질의 한 번**으로(결정 조립용). 없는 ID 는 결과에 없다."""
    valid = []
    for slot_id in slot_ids:
        try:
            valid.append(parse_uuid(slot_id, "게재 위치"))
        except errors.NotFound:
            pass  # 형식이 틀린 ID 는 없는 것과 같다
    rows = _current_policies().filter(slot_id__in=valid)
    return {row.slot_id: _slot_view(row.slot, row) for row in rows}
