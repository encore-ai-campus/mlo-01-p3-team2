"""공통 설정. **환경변수를 읽지 않는다**(dev·prod 가 읽고, test 는 읽지 않는다)."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# dev 에서만 쓰는 임시 키. prod 가 이 값을 쓰면 기동 실패(prod.py).
INSECURE_DEV_KEY = "dev-only-insecure-key-do-not-use-in-production"

DEBUG = False

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "foundation.apps.FoundationConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]

AUTH_USER_MODEL = "foundation.User"

# 시간은 저장·계산 모두 UTC. KST 는 화면 표시 변환에서만 쓴다(foundation 의 `kst` 필터).
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SQLITE_BUSY_TIMEOUT_SECONDS = 5


def sqlite_config(name, wal=True):
    """SQLite 설정 (설계 §6.5).

    - WAL: 읽기와 쓰기가 서로 막지 않는다.
    - synchronous=FULL: 커밋이 디스크에 내려간 뒤에 확인한다. NORMAL 이면 정전 시 마지막 커밋을 잃을 수 있다.
    - timeout: 잠금 대기(busy_timeout). 넘으면 'database is locked' → 수신 단계는 503 으로 변환(Step 2).
    - transaction_mode=IMMEDIATE: 쓰기 트랜잭션을 시작할 때 잠금을 잡아 중간 교착을 피한다.
    """
    init = "PRAGMA synchronous=FULL;"
    if wal:
        init = "PRAGMA journal_mode=WAL; " + init
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(name),
        "OPTIONS": {
            "timeout": SQLITE_BUSY_TIMEOUT_SECONDS,
            "transaction_mode": "IMMEDIATE",
            "init_command": init,
        },
    }


# 로깅 원칙: 요청 본문·비밀번호·세션 키·매체 키는 기록하지 않는다(0-6 에서 필터로 강제).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
