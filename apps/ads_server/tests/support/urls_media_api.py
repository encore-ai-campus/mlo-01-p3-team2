"""2-2 테스트용 URL 설정: 계약 경로(`/api/media/v1/...`)에 **실제 인증·요청 제한 데코레이터**를 붙인 임시 뷰.

결정·반응의 실제 뷰는 2-3·2-4 에서 같은 데코레이터로 만든다. 여기서는 인증 계층이 계약(401·403·429)을 지키는지만 확인한다.
"""
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.urls import path

from config.urls import handler400, handler403, handler404, handler500  # noqa: F401
from foundation.api import parse_json
from serving_api.auth import media_endpoint


@media_endpoint("decisions")
def create_decision(request):
    parse_json(request)  # 인증 뒤에야 입력을 검증한다
    return JsonResponse({"ok": True, "media_id": str(request.media.media_id)})


@media_endpoint("reads")
def get_decision(request, decision_id):
    return JsonResponse({"ok": True})


@media_endpoint("reactions")
def put_reaction(request, decision_id, reaction_id):
    return JsonResponse({"ok": True})


@media_endpoint("reads")
def get_reaction(request, decision_id, reaction_id):
    return JsonResponse({"ok": True})


@login_not_required
def reaction(request, decision_id, reaction_id):
    view = {"PUT": put_reaction, "GET": get_reaction}.get(request.method)
    if view is None:
        return JsonResponse({"error": "method"}, status=405)
    return view(request, decision_id, reaction_id)


urlpatterns = [
    path("api/media/v1/decisions", create_decision),
    path("api/media/v1/decisions/<uuid:decision_id>", get_decision),
    path("api/media/v1/decisions/<uuid:decision_id>/reactions/<uuid:reaction_id>", reaction),
]
