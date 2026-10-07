from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse, Http404
from django.utils.module_loading import import_string
from django.views.decorators.http import condition, require_safe

from .storage import NAME_RE  # noqa: F401  (URL 컨버터와 같은 형식)

CONTENT_TYPES = {"jpg": "image/jpeg", "png": "image/png"}


def _ensure_servable(name):
    """서빙 가능 여부. ASSET_SERVABLE_CHECK(점 경로)가 있으면 그 함수가 거짓일 때 404 — 중단된 소재가 여기서 막힌다.

    assets 는 campaigns 를 import 하지 않는다. 연결은 settings 로 한다(설계 R1·R4).
    """
    from .api import asset_exists

    check = settings.ASSET_SERVABLE_CHECK
    if check and not import_string(check)(name):
        raise Http404
    if not asset_exists(name):
        raise Http404


def _etag(request, name):
    _ensure_servable(name)
    return name.rsplit(".", 1)[0]  # 이름이 내용 해시이므로 그대로 ETag 다


def _asset_headers(view):
    """200 과 304 모두 같은 캐시 정책. 사본은 쓰기 전에 서버에 확인한다(중단이 즉시 반영된다)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "no-cache"
        response["Cross-Origin-Resource-Policy"] = "cross-origin"  # 다른 출처 페이지가 이미지를 삽입할 수 있어야 한다
        return response

    return wrapper


@login_not_required  # 최종 사용자 브라우저가 직접 받는다. 세션을 건드리지 않아 쿠키를 만들지 않는다.
@require_safe
@_asset_headers
@condition(etag_func=_etag)
def serve_asset(request, name):
    from .api import open_asset

    ext = name.rsplit(".", 1)[1]
    return FileResponse(open_asset(name), content_type=CONTENT_TYPES[ext])
