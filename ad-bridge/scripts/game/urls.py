"""게임 서버에 제공하는 광고 요청·노출 알림 경로."""

from django.urls import path

from .views import report_impression, request_decision, reaction_result


app_name = "ad_bridge"
urlpatterns = [
    path("decisions/<uuid:decision_id>/result/", reaction_result, name="result"),
    path("decision/", request_decision, name="decision"),
    path("decisions/<uuid:decision_id>/impression/", report_impression, name="impression"),
]
