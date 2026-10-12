"""루트 경로 공개 주소(최종 사용자 브라우저가 여는 것). `/api/` 아래가 아니라서 서버 간 API 의 CSRF 예외에 들어가지 않는다 — GET 뿐이라 필요 없다."""
from django.urls import path

from . import clicks

urlpatterns = [
    path("c/<str:token>", clicks.follow_click),
]
