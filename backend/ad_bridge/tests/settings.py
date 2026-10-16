"""운영 환경변수와 분리한 광고 브리지 전용 메모리 DB 설정."""

from django.urls import include, path

SECRET_KEY = "ad-bridge-isolated-tests-only"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ALLOWED_HOSTS = ["testserver"]
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "ad_bridge.apps.AdBridgeConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
ROOT_URLCONF = __name__
urlpatterns = [path("api/ads/", include("ad_bridge.game.urls"))]
MIDDLEWARE = []
LOGIN_URL = "/login/"
