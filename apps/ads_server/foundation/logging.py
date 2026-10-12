"""로그 위생 (위협 T22): 요청 ID 를 붙이고, 비밀번호·키·토큰이 로그에 남지 않게 가린다.

원칙: **요청 본문·비밀번호·세션 키·X-Media-Key 는 기록하지 않는다.** 코드가 기록하지 않는 것이 1차이고,
이 필터는 실수로 섞여 들어온 값을 마지막으로 가리는 2차 방어선이다.
"""
import contextvars
import logging
import re
import time

request_id_var = contextvars.ContextVar("request_id", default="-")

_SENSITIVE = r"(?:password|passwd|pwd|secret|token|authorization|api[_-]?key|x-media-key|sessionid|csrftoken|csrfmiddlewaretoken)"
_VALUE = r"""(?:(?:Bearer|Basic|Token)\s+\S+|"[^"]*"|'[^']*'|[^\s,;&}\]]+)"""
_PATTERN = re.compile(rf"(?i)(\b{_SENSITIVE}[\"']?\s*[:=]\s*)({_VALUE})")


def redact(text):
    return _PATTERN.sub(r"\1[redacted]", text)


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        rid = request_id_var.get()
        if rid == "-":  # Django 의 요청 요약 줄(4xx·5xx)은 요청 ID 미들웨어가 끝난 뒤에 남는다 — 그 기록에 실린 요청에서 꺼낸다(6-3b)
            rid = getattr(getattr(record, "request", None), "request_id", "-")
        record.request_id = rid
        return True


class UtcFormatter(logging.Formatter):
    """로그 시각을 UTC ISO 8601(`2026-10-12T03:00:00.123Z`)로 적는다(설계 §3 "시각은 UTC(ISO 8601, Z)", 6-3b).
    Django 가 `TIME_ZONE="UTC"` 로 프로세스 시간대를 맞춰 전에도 UTC 였지만 표기가 없어 KST 로 오독할 수 있었다. 프로세스 시간대와 무관하게 UTC 다."""

    converter = time.gmtime
    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03dZ"


class RedactingFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True
