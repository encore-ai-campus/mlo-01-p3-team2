"""환경변수 읽기 도우미. 설정 파일 중 dev·prod 만 사용한다(base·test 는 환경변수를 읽지 않는다)."""
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
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=(), required=False):
    value = env_str(name, required=required)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]
