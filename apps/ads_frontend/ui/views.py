"""모든 경로를 받는 뷰 하나(설계 §6.6 "6-15 분리"): 백엔드로 넘기고, 응답을 그대로 돌려준다(화면 데이터를 그리는 일은 6-15c)."""
import http.client
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.views.decorators.http import require_safe

from . import transport

log = logging.getLogger("ui")


def display(request, **kwargs):
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > settings.MAX_BODY_BYTES:  # 백엔드로 흘려보내지 않는다(백엔드의 RequestBodyLimitMiddleware 와 같은 상한)
        return HttpResponse("보낸 내용이 너무 큽니다.", status=413, content_type="text/plain; charset=utf-8")
    try:
        backend = transport.call_backend(request)
    except (OSError, http.client.HTTPException) as e:
        log.error("백엔드에 연결하지 못했다: %s: %s", type(e).__name__, e)
        return HttpResponse("서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.", status=502, content_type="text/plain; charset=utf-8")
    return transport.passthrough(backend)


def not_public(request, **kwargs):
    """매체 API(C1)는 공개하지 않는다 — 게임 백엔드가 백 서버를 내부 주소로 부른다."""
    return HttpResponseNotFound()


@require_safe
def health(request):
    return JsonResponse({"service": "ads-frontend", "status": "ok"})
