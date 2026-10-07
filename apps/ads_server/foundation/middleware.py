from django.conf import settings
from django.utils.cache import add_never_cache_headers

from .errors import ApiError
from .http import problem_response


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
    """뷰가 던진 ApiError 를 problem+json 으로 바꾼다. (다른 예외는 Django 핸들러가 처리한다.)"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, ApiError):
            return problem_response(request, exception)
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
