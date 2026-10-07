"""C1 인증·요청 제한(설계 §3, 위협 T10). **인증은 입력 검증보다 먼저**, 요청 제한은 인증 뒤(매체를 알아야 하므로)다.

| 상황 | 응답 |
|---|---|
| 키 없음·형식 오류·모르는 키·폐기·만료 | 401 + `WWW-Authenticate: MediaKey realm="ads-media-api"` |
| 유효한 키지만 매체가 비활성 | 403 |
| 매체·경로군의 버킷 소진 | 429 + `Retry-After` |

401 에서는 키가 틀린 이유(없는 키/틀린 비밀/폐기/만료)를 구분해 알리지 않는다. 이 데코레이터는 CSRF 예외 접두사(`/api/media/`)와 함께
쓰이며, 세션을 쓰지 않으므로 쿠키를 만들지 않는다.
"""
import logging
import re
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_not_required

from foundation.api import errors
from masters import api as masters

from .throttle import buckets

logger = logging.getLogger(__name__)

CHALLENGE = 'MediaKey realm="ads-media-api"'
GROUPS = ("decisions", "reactions", "reads")
_KEY_ID = re.compile(r"[0-9a-f]{32}")


def _unauthorized():
    return errors.Unauthorized("유효한 X-Media-Key 가 필요합니다.", headers={"WWW-Authenticate": CHALLENGE})


def authenticate(request):
    raw = request.headers.get("X-Media-Key", "").strip()
    identity = masters.authenticate_media_key(raw) if raw else None
    if identity is None:
        prefix = raw.split(".", 1)[0]  # 공개 식별자만 기록한다(비밀 부분은 절대 기록하지 않는다)
        logger.warning("매체 키 거절 key_id=%s", prefix if _KEY_ID.fullmatch(prefix) else "-")
        raise _unauthorized()
    if not identity.media_is_active:
        raise errors.Forbidden("이 매체는 비활성입니다.")
    return identity


def media_endpoint(group):
    """C1 엔드포인트 데코레이터. 성공하면 `request.media`(`MediaIdentity`)를 채운다. `group` 은 요청 제한 경로군이다."""
    assert group in GROUPS, group

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            identity = authenticate(request)
            rate, burst = settings.MEDIA_RATE_LIMITS[group]
            wait = buckets.take((identity.media_id, group), rate, burst)
            if wait is not None:
                raise errors.RateLimited("요청이 너무 많습니다.", retry_after=wait)
            request.media = identity
            return view(request, *args, **kwargs)

        return login_not_required(wrapper)  # 공개 뷰 표시(세션 로그인이 아니라 키로 인증한다)

    return decorator
