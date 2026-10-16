import uuid
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import HASH_SESSION_KEY, authenticate, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.crypto import constant_time_compare

from .access import require_admin, require_advertiser
from .audit import record_audit
from .errors import Conflict, NotFound
from .models import Role, User
from .validators import clean_class_label, clean_nickname, clean_text, parse_uuid, parse_uuids, validate_username


def create_advertiser(username, password, nickname, class_label):
    """광고주 가입. **역할은 항상 advertiser** 이고 인자로 받지 않는다.

    ValidationError(필드별 메시지)를 던진다. 아이디 중복도 일반적인 문구로 알린다.
    """
    errors = {}
    try:
        validate_username(username)
    except ValidationError as e:
        errors["username"] = e.messages
    try:
        nickname = clean_nickname(nickname)
    except ValidationError as e:
        errors["nickname"] = e.messages
    try:
        class_label = clean_class_label(class_label)
    except ValidationError as e:
        errors["class_label"] = e.messages
    if errors:
        raise ValidationError(errors)

    candidate = User(username=username, nickname=nickname, class_label=class_label, role=Role.ADVERTISER)
    try:
        validate_password(password, candidate)
    except ValidationError as e:
        raise ValidationError({"password": e.messages})

    try:
        with transaction.atomic():
            return User.objects.create_user(
                username, password, nickname=nickname, class_label=class_label, role=Role.ADVERTISER
            )
    except IntegrityError:  # 동시 가입 포함: 유니크 제약이 최종 판정
        raise ValidationError({"username": ["사용할 수 없는 아이디입니다."]})


@dataclass(frozen=True)
class ProfileView:
    """내 정보(C6 `Profile`). 모델이 아니라 이 값만 밖으로 낸다. `is_active` 는 C6 에 없고 관리자 화면 표시용이다(비활성화된 광고주의 캠페인 표시)."""

    user_id: uuid.UUID
    username: str
    nickname: str
    class_label: str
    created_at: datetime
    is_active: bool


def _profile_view(user):
    return ProfileView(user.pk, user.username, user.nickname, user.class_label, user.created_at, user.is_active)


def profiles(user_ids):
    """표시용 사용자 정보 {user_id: ProfileView}(질의 한 번). 없는·형식이 틀린 ID 는 결과에 없다.
    이력의 `changed_by`·캠페인의 `owner_id` 같은 사용자 ID 를 화면에 아이디·닉네임·반으로 보일 때 쓴다."""
    return {u.pk: _profile_view(u) for u in User.objects.filter(pk__in=parse_uuids(user_ids))}


def lock_user(user):
    """사용자 행을 잠근다(`FOR UPDATE`, 트랜잭션 안에서만). 광고주 전체 상한(캠페인·광고그룹·소재 수, 이미지 보유량)을 세는 만들기·이미지 교체가
    **가장 먼저** 잡아 같은 광고주의 쓰기를 줄 세운다 — 잠금 순서는 사용자 → 캠페인 → 광고그룹 → 소재(설계 §10 "캠페인 행 잠금 규약"·"DRD 표 축소" ②, 6-16g).
    계정 경로(프로필·비밀번호 변경·비활성화·관리 사이트 POST)도 사용자 행을 잠그지만 그 뒤에 다른 행을 잡지 않아 순서가 엇갈리지 않는다."""
    User.objects.select_for_update().only("pk").get(pk=user.pk)


def update_profile(user, nickname=None, class_label=None):
    """광고주 내 정보(닉네임·반) 수정(C6 `PATCH /me`). 준 값만 바꾸고 가입과 같은 규칙으로 검증한다. 하나라도 틀리면 아무것도 바꾸지 않는다.

    ValidationError(필드별 메시지)를 던진다. 감사 로그(전·후 값)는 변경과 같은 트랜잭션에 남긴다. 호출한 쪽의 `user` 객체도 새 값으로 맞춘다.
    """
    require_advertiser(user)
    changes, errors = {}, {}
    for field, value, clean in (("nickname", nickname, clean_nickname), ("class_label", class_label, clean_class_label)):
        if value is None:
            continue
        try:
            changes[field] = clean(value)
        except ValidationError as e:
            errors[field] = e.messages
    if errors:
        raise ValidationError(errors)
    if not changes:
        raise ValidationError("바꿀 항목이 없습니다.")
    with transaction.atomic():
        row = User.objects.select_for_update().get(pk=user.pk)
        before = {field: getattr(row, field) for field in changes}
        for field, value in changes.items():
            setattr(row, field, value)
        row.save(update_fields=list(changes))
        record_audit(None, "account.profile_updated", target=row, actor=row, detail={"before": before, "after": changes})
    for field, value in changes.items():
        setattr(user, field, value)
    return _profile_view(row)


def change_password(user, current_password, new_password, request=None):
    """광고주 비밀번호 변경(C6 `PUT /me/password`). 현재 비밀번호를 확인하고, 새 비밀번호는 가입과 같은 검증을 받는다.

    바꾸면 세션 인증 해시가 바뀌어 **다른 세션은 모두 끝난다**. `request` 를 주면 그 세션만 새 해시·새 세션 키로 유지한다(`update_session_auth_hash`).
    현재 비밀번호가 틀린 시도는 감사 로그에 남는다(변경과 달리 되돌려지지 않게 트랜잭션 밖에서). ValidationError(필드별 메시지)를 던진다.

    **현재 비밀번호 확인은 로그인 잠금(axes)과 같은 계수**다(설계 §10 "비밀번호 변경의 시도 제한", 위협 모델 T43): `request` 가 있으면 `authenticate` 를 거쳐
    로그인과 이 확인의 실패를 (아이디, IP)마다 함께 세고, 5회면 5분 잠금이다. 잠금 중에는 맞는 비밀번호도 거절되고 응답은 axes 미들웨어가 429 로 바꾼다.
    확인 성공은 계수를 초기화하지 않는다(초기화는 로그인 성공에서만 — `AXES_RESET_ON_SUCCESS`). `request` 가 없는 호출(서버 명령·시험)은 잠금 계수 없이 확인한다.
    """
    require_advertiser(user)
    row = User.objects.get(pk=user.pk)
    if request is not None:
        confirmed = authenticate(request, username=row.username, password=current_password or "")
        current_ok = confirmed is not None and confirmed.pk == row.pk
    else:
        current_ok = row.check_password(current_password or "")
    if not current_ok:
        record_audit(request, "account.password_change_rejected", target=row, actor=row)
        raise ValidationError({"current_password": ["현재 비밀번호가 맞지 않습니다."]})
    try:
        validate_password(new_password, row)
    except ValidationError as e:
        raise ValidationError({"new_password": e.messages})
    verified = row
    with transaction.atomic():
        row = User.objects.select_for_update().get(pk=user.pk)
        # 확인한 뒤 계정이 바뀌었으면(비활성화·관리자 초기화·다른 세션의 변경) 저장하지 않는다 — 진행 중이던 요청이 그 조치를 덮고 세션을 이어 가지 못하게(외부 검토 3-1d).
        # 기준은 이 요청을 인증한 세션의 인증 해시(요청이 없으면 현재 비밀번호를 확인한 행)
        basis = request.session.get(HASH_SESSION_KEY, "") if request is not None else verified.get_session_auth_hash()
        if not row.is_active or not constant_time_compare(basis, row.get_session_auth_hash()):
            raise Conflict("계정 상태가 바뀌었습니다. 다시 로그인한 뒤 시도하세요.")
        row.set_password(new_password)
        row.save(update_fields=["password"])
        record_audit(request, "account.password_changed", target=row, actor=row)
    user.password = row.password
    if request is not None:
        update_session_auth_hash(request, row)


# ---------------------------------------------------------------- 관리자: 광고주 계정 (Step 3-1d)

@dataclass(frozen=True)
class AdvertiserAccount:
    """관리자 화면의 광고주 한 명(비밀번호 해시 등은 내지 않는다)."""

    user_id: uuid.UUID
    username: str
    nickname: str
    class_label: str
    is_active: bool
    created_at: datetime
    last_login: datetime | None


def _account(user):
    return AdvertiserAccount(user.pk, user.username, user.nickname, user.class_label, user.is_active, user.created_at, user.last_login)


def list_advertisers(actor):
    """모든 광고주(비활성 포함, 최근 가입순)."""
    require_admin(actor)
    return [_account(u) for u in User.objects.filter(role=Role.ADVERTISER).order_by("-created_at")]


def _advertiser(user_id, lock=False):
    qs = User.objects.filter(role=Role.ADVERTISER)
    try:
        return (qs.select_for_update() if lock else qs).get(pk=parse_uuid(user_id, "광고주"))
    except User.DoesNotExist:
        raise NotFound("광고주를 찾을 수 없습니다.")


def get_advertiser(actor, user_id):
    require_admin(actor)
    return _account(_advertiser(user_id))


def set_advertiser_active(actor, user_id, active, reason=""):
    """광고주 비활성화·다시 활성화(감사 로그 `account.deactivated`·`account.reactivated`). 비활성화는 사유가 필수다.

    비활성 광고주는 로그인할 수 없고 이미 열린 세션도 끝난다(`session_epoch` 를 올려 세션 검증 값이 바뀐다 — 다시 활성화해도 옛 세션은 돌아오지 않는다).
    **광고도 나가지 않는다**: 후보 조회와 공개 이미지가 소유자의 활성 여부를 본다(campaigns). 캠페인 상태는 바꾸지 않으므로 다시 활성화하면 그대로 다시 나간다.
    """
    require_admin(actor)
    active = bool(active)
    reason = clean_text(reason, "사유", "/reason", 200) if not active or reason else ""
    with transaction.atomic():
        row = _advertiser(user_id, lock=True)
        if row.is_active == active:
            raise Conflict("이미 활성 계정입니다." if active else "이미 비활성화된 계정입니다.")
        row.is_active = active
        if not active:
            row.session_epoch += 1  # 열린 세션을 끝낸다 — 다시 활성화해도 옛 쿠키로는 들어오지 못한다
        row.save(update_fields=["is_active", "session_epoch"])
        record_audit(None, "account.reactivated" if active else "account.deactivated", target=row, actor=actor, detail={"reason": reason})
    return _account(row)
