"""로그 위생 (위협 T22): 요청 ID 를 붙이고, 비밀번호·키·토큰이 로그에 남지 않게 가린다.

원칙: **요청 본문·비밀번호·세션 키·X-Media-Key 는 기록하지 않는다.** 코드가 기록하지 않는 것이 1차이고,
이 필터는 실수로 섞여 들어온 값을 마지막으로 가리는 2차 방어선이다.
"""
import contextvars
import logging
import re

request_id_var = contextvars.ContextVar("request_id", default="-")

_SENSITIVE = r"(?:password|passwd|pwd|secret|token|authorization|api[_-]?key|x-media-key|sessionid|csrftoken|csrfmiddlewaretoken)"
_VALUE = r"""(?:(?:Bearer|Basic|Token)\s+\S+|"[^"]*"|'[^']*'|[^\s,;&}\]]+)"""
_PATTERN = re.compile(rf"(?i)(\b{_SENSITIVE}[\"']?\s*[:=]\s*)({_VALUE})")


def redact(text):
    return _PATTERN.sub(r"\1[redacted]", text)


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


class RedactingFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True
