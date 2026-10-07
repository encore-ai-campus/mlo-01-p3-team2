"""운영 설정. 필수 값이 없거나 개발용 값이면 **기동하지 않는다**."""
from django.core.exceptions import ImproperlyConfigured

from ._env import env_list, env_str
from .base import *  # noqa: F401,F403
from .base import INSECURE_DEV_KEY, sqlite_config

SECRET_KEY = env_str("SECRET_KEY", required=True)
if SECRET_KEY == INSECURE_DEV_KEY or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("SECRET_KEY 는 개발용 값이 아닌 50자 이상의 무작위 문자열이어야 합니다.")

DEBUG = False  # 환경변수로 바꿀 수 없다.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", required=True)

DATABASES = {"default": sqlite_config(env_str("DATABASE_PATH", required=True))}
