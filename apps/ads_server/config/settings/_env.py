"""환경변수 읽기 도우미. 빈 값은 없는 것과 같다. dev·prod 가 쓰고, test 는 접속 값(DB_*·MONGO_*)만 읽는다(base 는 읽지 않는다)."""
import os

from django.core.exceptions import ImproperlyConfigured


def env_str(name, default=None, required=False):
    value = os.environ.get(name)
    if value is None or value == "":
        if required:
            raise ImproperlyConfigured(f"환경변수 {name} 이(가) 필요합니다.")
        return default
    return value


def env_bool(name, default=False):
    value = env_str(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default=0, minimum=None, required=False):
    value = env_str(name, required=required)
    if value is None:
        return default
    try:
        number = int(value)
    except ValueError:
        raise ImproperlyConfigured(f"환경변수 {name} 은(는) 정수여야 합니다.")
    if minimum is not None and number < minimum:
        raise ImproperlyConfigured(f"환경변수 {name} 은(는) {minimum} 이상이어야 합니다.")
    return number


def env_list(name, default=(), required=False):
    value = env_str(name, required=required)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]
