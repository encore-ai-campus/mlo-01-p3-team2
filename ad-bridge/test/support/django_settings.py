"""게임 광고 요청 어댑터만 DB 없이 검사하는 Django 설정."""

from django.urls import include, path

SECRET_KEY = "ad-bridge-game-adapter-test-only"
ALLOWED_HOSTS = ["testserver"]
ROOT_URLCONF = __name__
urlpatterns = [path("api/ads/", include("ad_bridge.game.urls"))]
LOGIN_URL = "/login/"
USE_TZ = True
# 로그인 리다이렉트가 Django 인증 폼을 import한다. DB 조회는 테스트에서 금지한다.
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "ad_bridge.apps.AdBridgeConfig"]
DATABASES = {}
MIDDLEWARE = []

