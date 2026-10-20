from django.conf import settings
from django.contrib import admin
from django.urls import include, path

handler400 = "foundation.http.bad_request"
handler403 = "foundation.http.permission_denied"
handler404 = "foundation.http.not_found"
handler500 = "foundation.http.server_error"

urlpatterns = [
    path(settings.ADMIN_URL_PATH + "operator/", include("console.operator.urls")),  # 관리자 운영 화면(서비스를 부른다). 관리자 경로 규칙 아래
    path(settings.ADMIN_URL_PATH, admin.site.urls),  # 경로는 환경변수로 정한다(prod 는 기본값 금지)
    path("api/media/v1/", include("serving_api.urls")),
    path("", include("assets.urls")),
    path("", include("serving_api.root_urls")),  # 클릭 관측 /c/{token}
    path("", include("console.urls")),
]
