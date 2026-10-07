"""테스트 데이터 도우미(작은 함수들). `factory_boy` 는 쓰지 않는다(계획 §6.0-8)."""
import itertools

from foundation.models import User

PW = "Tr0ub4dor-horse-staple"
_counter = itertools.count(1)


def make_admin(username=None):
    return User.objects.create_superuser(username or f"admin_{next(_counter)}", PW, nickname="관리", class_label="-")


def make_advertiser(username=None):
    return User.objects.create_user(username or f"adv_{next(_counter)}", PW, nickname="광고주", class_label="1반")
