"""노출 저장소 통합 검사 전용: 외부 DB 대신 새 메모리 SQLite를 쓴다."""

from .django_settings import *  # noqa: F403

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "ad_bridge.apps.AdBridgeConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
