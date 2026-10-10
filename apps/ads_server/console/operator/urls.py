"""관리자 경로 아래(`<ADMIN_URL_PATH>operator/`)의 운영 화면. 관리자 경로 규칙(역할 게이트)이 관리자 아닌 사람에게는 404 로 숨긴다."""
from django.urls import path

from . import views

app_name = "operator"
urlpatterns = [
    path("media/", views.media_list, name="media_list"),
    path("media/<str:media_id>/", views.media_detail, name="media_detail"),
    path("media/<str:media_id>/active", views.media_active, name="media_active"),
    path("media/<str:media_id>/slots", views.slot_create, name="slot_create"),
    path("media/<str:media_id>/keys/issue", views.key_issue, name="key_issue"),
    path("media/<str:media_id>/keys/rotate", views.key_rotate, name="key_rotate"),
    path("slots/<str:slot_id>/active", views.slot_active, name="slot_active"),
    path("keys/<str:key_id>/revoke", views.key_revoke, name="key_revoke"),
]
