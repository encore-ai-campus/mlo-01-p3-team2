"""모든 경로를 받는 뷰 하나(설계 §6.6 "6-15 분리"): 백엔드로 넘기고, 화면 데이터면 그리고, 아니면 그대로 돌려준다."""
import http.client
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.views.decorators.http import require_safe

from . import rendering, transport

log = logging.getLogger("ui")

# 그린 HTML 에는 백엔드의 이 헤더들을 옮기지 않는다 — 내용 형식은 HTML, 보안 헤더는 프론트가 같은 값으로 붙인다(CSP 의 nonce 는 이 응답의 것)
NOT_FOR_RENDERED = {"content-type", "content-security-policy", "content-security-policy-report-only", "x-frame-options",
                    "x-content-type-options", "referrer-policy", "cross-origin-opener-policy"}


def display(request, **kwargs):
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > settings.MAX_BODY_BYTES:  # 백엔드로 흘려보내지 않는다(백엔드의 RequestBodyLimitMiddleware 와 같은 상한·문구)
        limit = f"{(settings.MAX_BODY_BYTES - 64 * 1024) / 1024 / 1024:g}MB"
        return error_page(request, 413, "요청이 너무 큽니다", f"보낸 내용이 너무 큽니다. 이미지는 {limit}까지 올릴 수 있습니다.")
    try:
        backend = transport.call_backend(request)
    except (OSError, http.client.HTTPException) as e:
        log.error("백엔드에 연결하지 못했다: %s: %s", type(e).__name__, e)
        return error_page(request, 502, "서버에 연결할 수 없습니다", "잠시 후 다시 시도해 주세요.")
    presentation = presentation_of(backend)
    if presentation is None:
        return transport.passthrough(backend)
    html, _ = rendering.render(request, presentation)
    return transport.copy_headers(HttpResponse(html, status=backend.status), backend, skip=NOT_FOR_RENDERED)


def presentation_of(backend):
    """백엔드 응답이 화면 데이터(`{"presentation": …}`)면 그것, 아니면 None."""
    if not (backend.header("Content-Type") or "").startswith("application/json"):
        return None
    try:
        data = json.loads(backend.body)
    except ValueError:
        return None
    return data.get("presentation") if isinstance(data, dict) else None


def error_page(request, status, title, message):
    """백엔드에 가지 않고 그리는 오류 화면(같은 템플릿)."""
    context = {"status": status, "title": title, "message": message, "user": {"is_authenticated": False}, "messages": []}  # 오류 화면에는 폼이 없다(CSRF 토큰 없음)
    html, _ = rendering.render(request, {"template": "foundation/error.html", "context": context})
    return HttpResponse(html, status=status)


def not_public(request, **kwargs):
    """매체 API(C1)는 공개하지 않는다 — 게임 백엔드가 백 서버를 내부 주소로 부른다."""
    return HttpResponseNotFound()


@require_safe
def health(request):
    return JsonResponse({"service": "ads-frontend", "status": "ok"})
