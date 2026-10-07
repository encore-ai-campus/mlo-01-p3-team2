from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(settings.ADMIN_URL_PATH, admin.site.urls),  # 경로는 환경변수로 정한다(prod 는 기본값 금지)
    path("", include("console.urls")),
]
