import re
import uuid

from django.conf import settings
from django.utils.cache import add_never_cache_headers

from .errors import ApiError, PayloadTooLarge
from .dberrors import is_transient_lock_error
from .http import problem_response, transient_db_error
from .logging import request_id_var

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class RequestIdMiddleware:
    """요청마다 UUID 를 붙인다. 들어온 `X-Request-ID` 는 **UUID 형식일 때만** 받아들인다(로그·헤더 주입 방지)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_REQUEST_ID", "")
        rid = incoming.lower() if _UUID.fullmatch(incoming) else str(uuid.uuid4())
        request.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response["X-Request-ID"] = rid
        return response


REQUEST_BODY_OVERHEAD = 64 * 1024  # multipart 의 다른 필드·경계 문자열 여유


class RequestBodyLimitMiddleware:
    """선언된 `Content-Length` 가 업로드 상한(`ASSET_MAX_BYTES`) + 여유를 넘으면 **본문을 읽기 전에** 413 으로 끊는다(위협 T16).

    CsrfViewMiddleware 가 `request.POST` 를 읽으면서 multipart 를 파싱하고 임시 파일을 만들기 때문에, 그 앞에서 막아야 한다.
    (업로드 핸들러의 `handle_raw_input` 에서 예외를 던지는 방식은 Django 가 처리하지 못해 500 이 된다.)
    상한 설정 이름만 읽고 `assets` 를 import 하지 않는다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0  # Django 와 같게: 형식이 틀린 길이는 0 으로 본다
        if declared > settings.ASSET_MAX_BYTES + REQUEST_BODY_OVERHEAD:
            return problem_response(request, PayloadTooLarge("요청 본문이 허용 크기를 넘습니다."))
        return self.get_response(request)


class CsrfExemptPrefixesMiddleware:
    """키 인증을 쓰는 서버 간 API(`/api/media/`)만 CSRF 검사에서 뺀다. **예외 목록은 settings 한 곳**이다.

    CsrfViewMiddleware 앞에 둔다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(prefix) for prefix in settings.CSRF_EXEMPT_PREFIXES):
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)


class ApiErrorMiddleware:
    """뷰가 던진 ApiError 를 problem+json 으로 바꾼다. 교착·잠금 대기 초과는 503 + `Retry-After`(화면은 HTML, API 는 problem+json).
    (다른 예외는 Django 핸들러가 처리한다.)"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, ApiError):
            return problem_response(request, exception)
        if is_transient_lock_error(exception):
            return transient_db_error(request)
        return None


class NoStoreMiddleware:
    """기본은 캐시 금지(`private, no-store`). 응답이 이미 Cache-Control 을 정했으면(이미지 서빙 등) 건드리지 않는다.

    인증이 필요한 화면·CSRF 토큰이 든 폼·API 응답이 중간 캐시에 남지 않게 한다(위협 T13).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Cache-Control" not in response.headers:
            add_never_cache_headers(response)
        return response
