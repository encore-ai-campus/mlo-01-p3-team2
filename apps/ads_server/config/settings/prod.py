"""운영 설정. 필수 값이 없거나 개발용 값이면 **기동하지 않는다**."""
from django.core.exceptions import ImproperlyConfigured

from config.access_map import build_access_map, validate_admin_path

from ._env import env_bool, env_int, env_list, env_str
from .base import *  # noqa: F401,F403
from .base import INSECURE_DEV_KEY, mongo_config, mysql_config

SECRET_KEY = env_str("SECRET_KEY", required=True)
if SECRET_KEY == INSECURE_DEV_KEY or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("SECRET_KEY 는 개발용 값이 아닌 50자 이상의 무작위 문자열이어야 합니다.")

DEBUG = False  # 환경변수로 바꿀 수 없다.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# 앞단 nginx 뒤라 필수이고 1 이상이다(설계 §10 "배포 구성", 6-5c). 기본값을 두지 않는다 — 1 을 기본으로 두면 Django 포트가 nginx 밖에 열렸을 때 X-Forwarded-For 위조가 그대로 통한다
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", required=True, minimum=1)
ADMIN_URL_PATH = validate_admin_path(env_str("ADMIN_URL_PATH", required=True))  # 기본값 admin/ 금지

# --- HTTPS (TLS 종단은 인프라 소관) ---
SECURE_SSL_REDIRECT = env_bool("SSL_REDIRECT", True)
# 리버스 프록시가 TLS 를 종단하고 X-Forwarded-Proto 를 **덮어써서** 넘길 때만 켠다(아니면 헤더 위조로 HTTPS 로 속일 수 있다).
if env_bool("BEHIND_TLS_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env_int("HSTS_SECONDS", 3600)  # 처음엔 짧게. 안정되면 늘린다(되돌리기 어렵다).
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
# W021(프리로드 미설정)은 **의도적으로 끈다**: 이 서버는 내부 서비스이고 브라우저 프리로드 목록 등록은 되돌리기 어렵다.
# 공개 도메인으로 서비스하게 되면 그때 켜고 이 항목을 지운다.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", default=[])  # 예: https://ads.example.com
ACCESS_MAP = build_access_map(ADMIN_URL_PATH)

MEDIA_ROOT = env_str("MEDIA_ROOT", required=True)  # 코드·정적 파일 경로 밖. 웹서버가 직접 서빙하지 않는다.
ASSET_PUBLIC_BASE_URL = env_str("ASSET_PUBLIC_BASE_URL", required=True)  # 결정 응답의 image_url·click_url 에 쓰는 광고 서버의 공개 주소
ASSET_SERVABLE_CHECK = "campaigns.api.is_asset_servable"  # 중단·종료된 캠페인의 이미지는 404 (campaigns 가 판정, assets 는 모른다)
SIGNUP_GRANT_POINTS = env_int("SIGNUP_GRANT_POINTS", 50_000)
BUDGET_DAY_OFFSET_HOURS = env_int("BUDGET_DAY_OFFSET_HOURS", 0)
ASSET_MAX_BYTES = env_int("ASSET_MAX_BYTES", 2 * 1024 * 1024)
STATIC_ROOT = env_str("STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", required=True)

DATABASES = {"default": mysql_config(
    env_str("DB_NAME", required=True),
    env_str("DB_USER", required=True),
    env_str("DB_PASSWORD", required=True),
    env_str("DB_HOST", required=True),
    env_int("DB_PORT", 3306),
    env_str("DB_ISOLATION_LEVEL", default="read committed"),  # 측정으로 확정한 값(base.mysql_config). 바꿔 비교할 때만 쓴다
)}

# 이벤트 저장소(MongoDB `ad_events`). 웹은 MongoDB 를 쓰지 않으므로 MONGO_HOSTS 가 없어도 기동한다(None — 웹 노드에 MongoDB 비밀번호를 두지 않는다).
# 중계(relay_events)는 설정이 없으면 바로 멈춘다(설계 §10 "이벤트 저장소 설정", 6-3e — Step 4 에서 필수로 바꾸려던 계획을 바꿨다).
EVENT_STORE = mongo_config(
    env_list("MONGO_HOSTS"),
    env_str("MONGO_DB", default="ads_events"),
    env_str("MONGO_USER"),
    env_str("MONGO_PASSWORD"),
    env_str("MONGO_AUTH_SOURCE", default="admin"),
    env_str("MONGO_REPLICA_SET"),
) if env_list("MONGO_HOSTS") else None
