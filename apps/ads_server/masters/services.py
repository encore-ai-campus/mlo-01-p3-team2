"""masters 의 규칙. 관리자 전용이며 모든 변경은 감사 로그에 남는다(위협 T23)."""
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from foundation.api import MAX_AMOUNT, Role, clean_text, errors, parse_uuid, record_audit

from .models import BidPolicy, Media, MediaKey, PricingUnit, Slot
from .types import IssuedKey, MediaIdentity, MediaKeyView, MediaView, PolicyView, SlotView


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
        bid_policy_id=row.bid_policy_id, slot_id=row.slot_id, policy_version=row.policy_version, floor=row.floor_amount, base=row.base_amount,
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


def slot_names(slot_ids):
    """슬롯 이름(**표시용**, 바뀔 수 있다)을 질의 한 번으로. 없는·형식이 틀린 ID 는 결과에 없다."""
    valid = []
    for slot_id in slot_ids:
        try:
            valid.append(parse_uuid(slot_id, "게재 위치"))
        except errors.NotFound:
            pass
    return dict(Slot.objects.filter(pk__in=valid).values_list("pk", "name"))


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


# ---------------------------------------------------------------- 매체 키 (C1 인증)

KEY_RE = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}")  # `<key_id hex>.<token_urlsafe(32)>`
MAX_GRACE = timedelta(days=30)
_DUMMY_HASH = hashlib.sha256(b"no such key").hexdigest()  # 없는 키도 같은 비교를 하게 해 응답 시간으로 존재 여부를 알 수 없게 한다


def _now(now=None):
    return now if now is not None else timezone.now()


def _hash_secret(secret):
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _key_view(k, now):
    active = k.revoked_at is None and (k.expires_at is None or k.expires_at > now)
    return MediaKeyView(
        key_id=k.key_id, media_id=k.media_id, label=k.label, created_at=k.created_at, expires_at=k.expires_at,
        revoked_at=k.revoked_at, active=active,
    )


def _issue(actor, media, label, now, action, extra=None):
    secret = secrets.token_urlsafe(32)
    row = MediaKey.objects.create(media=media, secret_hash=_hash_secret(secret), label=label, created_at=now)
    # 감사 로그에는 키 식별자만 남긴다. 키(평문)·해시는 기록하지 않는다
    _audit(actor, action, ("masters.media_key", row.key_id), {"media_id": str(media.media_id), "label": label, **(extra or {})})
    return IssuedKey(key_id=row.key_id, media_id=media.media_id, key=f"{row.key_id.hex}.{secret}", created_at=now, expires_at=None)


def _media_for_key_admin(media_id):
    try:
        return Media.objects.get(pk=parse_uuid(media_id, "매체"))
    except Media.DoesNotExist:
        raise errors.NotFound("매체를 찾을 수 없습니다.")


def issue_media_key(actor, media_id, label="", now=None):
    """새 키를 발급한다. 평문은 반환값에만 있다. 기존 키는 그대로 유효하다."""
    _require_admin(actor)
    now = _now(now)
    label = clean_text(label, "라벨", "/label") if label else ""
    with transaction.atomic():
        return _issue(actor, _media_for_key_admin(media_id), label, now, "masters.media_key_issued")


def rotate_media_key(actor, media_id, grace_seconds, label="", now=None):
    """새 키를 발급하고 **기존 유효 키는 유예 시간 뒤에 만료**시킨다(그동안 두 키가 모두 유효 — 무중단 교체).

    `grace_seconds` 는 0 이상 30일 이하의 정수. 0 이면 기존 키가 바로 만료된다. 이미 더 일찍 만료될 키는 그대로 둔다.
    """
    _require_admin(actor)
    now = _now(now)
    if isinstance(grace_seconds, bool) or not isinstance(grace_seconds, int) or not 0 <= grace_seconds <= MAX_GRACE.total_seconds():
        raise errors.InvalidRequest(errors=[{"pointer": "/grace_seconds", "message": "0 이상 30일(초) 이하의 정수여야 합니다."}])
    label = clean_text(label, "라벨", "/label") if label else ""
    with transaction.atomic():
        media = _media_for_key_admin(media_id)
        deadline = now + timedelta(seconds=grace_seconds)
        older = list(MediaKey.objects.filter(media=media, revoked_at__isnull=True).exclude(expires_at__lte=now))
        for k in older:
            if k.expires_at is None or k.expires_at > deadline:
                MediaKey.objects.filter(pk=k.pk).update(expires_at=deadline)
        issued = _issue(actor, media, label, now, "masters.media_key_rotated", {"grace_seconds": grace_seconds, "previous": [str(k.key_id) for k in older]})
    return issued


def revoke_media_key(actor, key_id, now=None):
    """키를 즉시 폐기한다(유출 대응). 이미 폐기된 키는 변화 없음."""
    _require_admin(actor)
    now = _now(now)
    with transaction.atomic():
        try:
            k = MediaKey.objects.get(key_id=parse_uuid(key_id, "키"))
        except MediaKey.DoesNotExist:
            raise errors.NotFound("키를 찾을 수 없습니다.")
        if k.revoked_at is None:
            MediaKey.objects.filter(pk=k.pk).update(revoked_at=now)
            _audit(actor, "masters.media_key_revoked", ("masters.media_key", k.key_id), {"media_id": str(k.media_id)})


def list_media_keys(actor, media_id, now=None):
    _require_admin(actor)
    now = _now(now)
    return [_key_view(k, now) for k in MediaKey.objects.filter(media_id=parse_uuid(media_id, "매체")).order_by("-created_at")]


def authenticate_media_key(raw_key, now=None):
    """`X-Media-Key` 값을 검증한다. 성공하면 `MediaIdentity`, 아니면 `None`(호출하는 쪽이 401).

    형식이 틀린 값은 DB 를 보지 않고 거절한다. 형식이 맞으면 `key_id` 로 행을 찾고 비밀의 해시를 **상수시간으로 비교**한다
    (없는 키도 더미 해시와 같은 비교를 한다). 폐기·만료된 키는 거절한다. 매체가 비활성이어도 신원은 돌려준다(403 은 호출하는 쪽의 몫).
    """
    now = _now(now)
    if not isinstance(raw_key, str) or not KEY_RE.fullmatch(raw_key):
        return None
    key_hex, secret = raw_key.split(".", 1)
    row = MediaKey.objects.select_related("media").filter(key_id=uuid.UUID(key_hex)).first()
    expected = row.secret_hash if row is not None else _DUMMY_HASH
    matches = hmac.compare_digest(_hash_secret(secret), expected)
    if row is None or not matches:
        return None
    if row.revoked_at is not None or (row.expires_at is not None and row.expires_at <= now):
        return None
    return MediaIdentity(media_id=row.media_id, key_id=row.key_id, media_is_active=row.media.is_active)
