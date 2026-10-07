"""API 오류. 뷰에서 던지면 ApiErrorMiddleware 가 `application/problem+json`(RFC 9457)으로 바꾼다.

계약의 `Problem` 스키마(docs/ads-server/contracts/*.openapi.yaml)와 같은 `code`를 쓴다.
"""


class ApiError(Exception):
    status = 500
    code = "internal_error"
    title = "서버 오류가 발생했습니다"

    def __init__(self, detail=None, *, errors=None, retry_after=None):
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = errors  # [{"pointer": "/field", "message": "..."}]
        self.retry_after = retry_after  # 초. 429·503


class InvalidRequest(ApiError):
    status, code, title = 400, "invalid_request", "요청이 올바르지 않습니다"


class Unauthorized(ApiError):
    status, code, title = 401, "unauthorized", "인증이 필요합니다"


class Forbidden(ApiError):
    status, code, title = 403, "forbidden", "권한이 없습니다"


class NotFound(ApiError):
    status, code, title = 404, "not_found", "찾을 수 없습니다"


class Conflict(ApiError):
    status, code, title = 409, "conflict", "요청이 현재 상태와 충돌합니다"


class StaleVersion(Conflict):
    """호출자가 본 버전이 현재와 다르다(입찰·정책의 낙관적 잠금). 새로 불러와 다시 시도한다."""

    code, title = "stale_version", "다른 곳에서 먼저 바뀌었습니다. 새로 불러와 다시 시도하세요"


class PayloadTooLarge(ApiError):
    status, code, title = 413, "payload_too_large", "요청이 너무 큽니다"


class UnsupportedMediaType(ApiError):
    status, code, title = 415, "unsupported_media_type", "지원하지 않는 형식입니다"


class RateLimited(ApiError):
    status, code, title = 429, "rate_limited", "요청이 너무 많습니다"


class Unavailable(ApiError):
    status, code, title = 503, "unavailable", "일시적으로 처리할 수 없습니다"
