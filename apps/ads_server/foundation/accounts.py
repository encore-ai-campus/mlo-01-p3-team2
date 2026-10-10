import uuid
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .access import require_advertiser
from .audit import record_audit
from .models import Role, User
from .validators import clean_class_label, clean_nickname, parse_uuids, validate_username


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
    """내 정보(C6 `Profile`). 모델이 아니라 이 값만 밖으로 낸다."""

    user_id: uuid.UUID
    username: str
    nickname: str
    class_label: str
    created_at: datetime


def _profile_view(user):
    return ProfileView(user.pk, user.username, user.nickname, user.class_label, user.created_at)


def usernames(user_ids):
    """표시용 아이디(질의 한 번). 없는·형식이 틀린 ID 는 결과에 없다. 이력의 `changed_by` 같은 사용자 ID 를 화면에 보일 때 쓴다."""
    return dict(User.objects.filter(pk__in=parse_uuids(user_ids)).values_list("pk", "username"))


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
    """
    require_advertiser(user)
    row = User.objects.get(pk=user.pk)
    if not row.check_password(current_password or ""):
        record_audit(request, "account.password_change_rejected", target=row, actor=row)
        raise ValidationError({"current_password": ["현재 비밀번호가 맞지 않습니다."]})
    try:
        validate_password(new_password, row)
    except ValidationError as e:
        raise ValidationError({"new_password": e.messages})
    with transaction.atomic():
        row = User.objects.select_for_update().get(pk=user.pk)
        row.set_password(new_password)
        row.save(update_fields=["password"])
        record_audit(request, "account.password_changed", target=row, actor=row)
    user.password = row.password
    if request is not None:
        update_session_auth_hash(request, row)
