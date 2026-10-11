"""Local Django settings for the campus map and user accounts."""
import os
from pathlib import Path

from .network import local_lan_addresses

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)

# This fallback is for local development. A deployed server must provide its own key.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-campus-local-development")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
default_hosts = ",".join(["localhost", "127.0.0.1", "[::1]", *local_lan_addresses()])
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", default_hosts).split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "campus.apps.CampusConfig",
    "eventing.apps.EventingConfig",
    "community.apps.CommunityConfig",
    "raffle.apps.RaffleConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "accounts.session_policy.CampusSessionPolicyMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "eventing.middleware.PlatformSessionMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
# Live edits must not combine a cached HTML template with newer map scripts.
template_loaders = [
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]
if not DEBUG:
    template_loaders = [("django.template.loaders.cached.Loader", template_loaders)]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "dist"],
        "APP_DIRS": False,
        "OPTIONS": {
            "loaders": template_loaders,
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "accounts.session_policy.session_context",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
# Local prototype: one server process shares presence and movement in memory.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

DATABASE_ENGINE = os.environ.get("DATABASE_ENGINE", "sqlite").strip().lower()
if DATABASE_ENGINE == "mysql":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE", ""),
        "USER": os.environ.get("MYSQL_USER", ""),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
        "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }}
    if not DATABASES["default"]["NAME"] or not DATABASES["default"]["USER"]:
        raise ValueError("MYSQL_DATABASE and MYSQL_USER are required when DATABASE_ENGINE=mysql")
elif DATABASE_ENGINE == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    raise ValueError("DATABASE_ENGINE must be sqlite or mysql")
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "campus:map"
LOGOUT_REDIRECT_URL = "accounts:login"
SESSION_COOKIE_NAME = "campus_sessionid"
CSRF_COOKIE_NAME = "campus_csrftoken"

# Seconds; configure before starting the server. Activity never moves the fixed login deadline.
CAMPUS_LOGIN_MAX_AGE_SECONDS = int(os.environ.get("CAMPUS_LOGIN_MAX_AGE_SECONDS", 8 * 60 * 60))
CAMPUS_LOGIN_IDLE_TIMEOUT_SECONDS = int(os.environ.get("CAMPUS_LOGIN_IDLE_TIMEOUT_SECONDS", 30 * 60))
CAMPUS_LOGIN_WARNING_SECONDS = int(os.environ.get("CAMPUS_LOGIN_WARNING_SECONDS", 60))
CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS = int(os.environ.get("CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS", 15))
if min(CAMPUS_LOGIN_MAX_AGE_SECONDS, CAMPUS_LOGIN_IDLE_TIMEOUT_SECONDS,
       CAMPUS_LOGIN_WARNING_SECONDS, CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS) <= 0:
    raise ValueError("Campus session durations must be positive seconds")
SESSION_COOKIE_AGE = CAMPUS_LOGIN_MAX_AGE_SECONDS
CAMPUS_SESSION_CLEANUP_ENABLED = os.environ.get("CAMPUS_SESSION_CLEANUP_ENABLED", "1") == "1"
CAMPUS_SESSION_CLEANUP_TIME = os.environ.get("CAMPUS_SESSION_CLEANUP_TIME", "04:00")
CAMPUS_SESSION_CLEANUP_STATE = BASE_DIR / "var" / "session-cleanup.json"

# Raffle dates are unset until an administrator chooses them in the campus UI.
CAMPUS_RAFFLE_SCHEDULER_ENABLED = os.environ.get("CAMPUS_RAFFLE_SCHEDULER_ENABLED", "1") == "1"
CAMPUS_RAFFLE_POLL_SECONDS = float(os.environ.get("CAMPUS_RAFFLE_POLL_SECONDS", "1"))
CAMPUS_RAFFLE_ANIMATION_SECONDS = int(os.environ.get("CAMPUS_RAFFLE_ANIMATION_SECONDS", "10"))
if CAMPUS_RAFFLE_POLL_SECONDS <= 0 or not 1 <= CAMPUS_RAFFLE_ANIMATION_SECONDS <= 60:
    raise ValueError("Raffle polling must be positive and animation must be 1~60 seconds")

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATICFILES_DIRS = [("campus", BASE_DIR / "dist")]
STATIC_ROOT = BASE_DIR / "staticfiles"

# The public cafeteria channel changes its profile photo to the current menu.
BOARD_MENU_SOURCE_URL = "https://pf.kakao.com/_xfWxfCxj"
BOARD_MENU_STORAGE_ROOT = BASE_DIR / "var" / "board-menu"
BOARD_MENU_UPDATE_TIME = "10:00"
BOARD_MENU_TIME_ZONE = "Asia/Seoul"

# Raw events are kept in the transactional outbox until a Kafka broker is configured.
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
KAFKA_SECURITY_PROTOCOL = os.environ.get("KAFKA_SECURITY_PROTOCOL", "").strip()
KAFKA_SASL_MECHANISM = os.environ.get("KAFKA_SASL_MECHANISM", "").strip()
KAFKA_SASL_USERNAME = os.environ.get("KAFKA_SASL_USERNAME", "")
KAFKA_SASL_PASSWORD = os.environ.get("KAFKA_SASL_PASSWORD", "")
CAMPUS_RAW_SOURCE = os.environ.get("CAMPUS_RAW_SOURCE", "platform_server_1").strip() or "platform_server_1"
