from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import Role, User
from .validators import clean_class_label, clean_nickname, validate_username


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
