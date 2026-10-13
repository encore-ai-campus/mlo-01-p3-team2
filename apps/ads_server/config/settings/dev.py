"""로컬 개발 설정. 환경변수(.env 포함)를 읽는다."""
from config.access_map import build_access_map, validate_admin_path

from ._env import env_bool, env_int, env_list, env_str
from .base import *  # noqa: F401,F403
from .base import BASE_DIR, INSECURE_DEV_KEY, mongo_config, mysql_config

SECRET_KEY = env_str("SECRET_KEY", default=INSECURE_DEV_KEY)
DEBUG = env_bool("DJANGO_DEBUG", False)
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)
ADMIN_URL_PATH = validate_admin_path(env_str("ADMIN_URL_PATH", default="dev-admin/"), allow_default=True)
ACCESS_MAP = build_access_map(ADMIN_URL_PATH)

MEDIA_ROOT = env_str("MEDIA_ROOT", default=BASE_DIR / "media")
ASSET_PUBLIC_BASE_URL = env_str("ASSET_PUBLIC_BASE_URL", default="http://127.0.0.1:8001")
ASSET_SERVABLE_CHECK = "campaigns.api.is_asset_servable"  # 중단·종료된 캠페인의 이미지는 404 (campaigns 가 판정, assets 는 모른다)
SIGNUP_GRANT_POINTS = env_int("SIGNUP_GRANT_POINTS", 50_000)
BUDGET_DAY_OFFSET_HOURS = env_int("BUDGET_DAY_OFFSET_HOURS", 0)
ASSET_MAX_BYTES = env_int("ASSET_MAX_BYTES", 2 * 1024 * 1024)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])

DATABASES = {"default": mysql_config(
    env_str("DB_NAME", default="ads_server"),
    env_str("DB_USER", required=True),
    env_str("DB_PASSWORD", required=True),
    env_str("DB_HOST", default="127.0.0.1"),
    env_int("DB_PORT", 3306),
    env_str("DB_ISOLATION_LEVEL", default="read committed"),  # 측정으로 확정한 값(base.mysql_config). 바꿔 비교할 때만 쓴다
)}

# 이벤트 저장소(MongoDB `ad_events`). 웹은 쓰지 않고 중계·내보내기 명령이 쓴다(설계 §10 "이벤트 저장소 설정"). 확인은 `manage.py check_event_store`.
EVENT_STORE = mongo_config(
    env_list("MONGO_HOSTS", default=["127.0.0.1:27017"]),
    env_str("MONGO_DB", default="ads_events"),
    env_str("MONGO_USER"),
    env_str("MONGO_PASSWORD"),
    env_str("MONGO_AUTH_SOURCE", default="admin"),
    env_str("MONGO_REPLICA_SET"),
)
