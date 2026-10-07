"""로컬 개발 설정. 환경변수(.env 포함)를 읽는다."""
from config.access_map import build_access_map, validate_admin_path

from ._env import env_bool, env_int, env_list, env_str
from .base import *  # noqa: F401,F403
from .base import BASE_DIR, INSECURE_DEV_KEY, sqlite_config

SECRET_KEY = env_str("SECRET_KEY", default=INSECURE_DEV_KEY)
DEBUG = env_bool("DJANGO_DEBUG", False)
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)
ADMIN_URL_PATH = validate_admin_path(env_str("ADMIN_URL_PATH", default="dev-admin/"), allow_default=True)
ACCESS_MAP = build_access_map(ADMIN_URL_PATH)

MEDIA_ROOT = env_str("MEDIA_ROOT", default=BASE_DIR / "media")
ASSET_PUBLIC_BASE_URL = env_str("ASSET_PUBLIC_BASE_URL", default="http://127.0.0.1:8001")
ASSET_MAX_BYTES = env_int("ASSET_MAX_BYTES", 2 * 1024 * 1024)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])

DATABASES = {"default": sqlite_config(env_str("DATABASE_PATH", default=BASE_DIR / "db.sqlite3"))}
