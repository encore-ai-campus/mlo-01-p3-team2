"""0-4 테스트용 URL 설정: 키 인증 API 접두사(CSRF 예외)와 일반 접두사의 동작을 비교한다."""
import logging

from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponse, JsonResponse
from django.core.exceptions import PermissionDenied
from django.urls import path

from config.urls import handler400, handler403, handler404, handler500  # noqa: F401
from foundation import errors
from foundation.api import parse_json


@login_not_required
def echo(request):
    return JsonResponse(parse_json(request))


@login_not_required
def small_echo(request):
    return JsonResponse(parse_json(request, max_bytes=64, max_depth=3))


@login_not_required
def raise_error(request, kind):
    exc = {
        "invalid": errors.InvalidRequest("bad", errors=[{"pointer": "/x", "message": "m"}]),
        "unauthorized": errors.Unauthorized(), "forbidden": errors.Forbidden(), "not_found": errors.NotFound(),
        "conflict": errors.Conflict(), "too_large": errors.PayloadTooLarge(),
        "unsupported": errors.UnsupportedMediaType(), "rate": errors.RateLimited(retry_after=7),
        "unavailable": errors.Unavailable(retry_after=3),
    }.get(kind)
    if exc:
        raise exc
    if kind == "http404":
        raise Http404("secret-internal-detail")
    if kind == "denied":
        raise PermissionDenied("secret-internal-detail")
    raise RuntimeError("secret-internal-detail")


@login_not_required
def cache_header(request):
    response = HttpResponse("img")
    response["Cache-Control"] = "no-cache"
    return response


@login_not_required
def log_hello(request, msg):
    logging.getLogger("tests").warning("%s from the view", msg)
    return HttpResponse("ok")


urlpatterns = [
    path("logs/<str:msg>/", log_hello),
    path("api/media/echo/", echo),
    path("api/other/echo/", echo),
    path("api/media/small/", small_echo),
    path("api/other/raise/<str:kind>/", raise_error),
    path("boom/<str:kind>/", raise_error),
    path("cacheable/", cache_header),
]
