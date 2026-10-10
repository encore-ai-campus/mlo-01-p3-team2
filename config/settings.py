"""Local Django settings for the campus map and user accounts."""
import os
from pathlib import Path

from .network import local_lan_addresses

BASE_DIR = Path(__file__).resolve().parent.parent

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
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
# Local prototype: one server process shares presence and movement in memory.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
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
