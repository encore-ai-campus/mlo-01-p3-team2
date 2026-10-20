"""백엔드로 넘기고 받은 응답을 돌려준다(설계 §6.6 "6-15 분리"). 입력·쿠키는 바꾸지 않는다 — 판단(CSRF·로그인·권한·검증)은 백엔드 몫이다."""
import http.client
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse

# 넘기는 요청 헤더. 나머지(Authorization 등)는 넘기지 않는다
FORWARDED = ("Cookie", "Content-Type", "X-CSRFToken", "Origin", "Referer", "Accept", "Accept-Language", "User-Agent",
             "If-None-Match", "If-Modified-Since", "X-Request-ID")
# 옮기지 않는 응답 헤더: 연결마다의 것과 Django 가 다시 정하는 것
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers",
              "transfer-encoding", "upgrade", "content-length", "server", "date"}


@dataclass(frozen=True)
class BackendResponse:
    status: int
    body: bytes
    headers: list  # [(이름, 값)] — Set-Cookie 처럼 같은 이름이 여럿일 수 있다

    def header(self, name):
        return next((v for k, v in self.headers if k.lower() == name.lower()), None)


def call_backend(request):
    """요청을 그대로 백엔드에 보낸다. `Host` 는 사용자가 연 호스트(백엔드의 ALLOWED_HOSTS·CSRF·이동 주소가 같은 호스트를 본다),
    `X-Forwarded-For` 에는 nginx 처럼 받은 상대 주소를 덧붙인다 — 백엔드는 신뢰할 프록시 수로 클라이언트 IP 를 고른다(운영 2: nginx·프론트)."""
    target = urlsplit(settings.BACKEND_URL)
    connection_class = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(target.hostname, target.port, timeout=settings.BACKEND_TIMEOUT)
    headers = {name: request.headers[name] for name in FORWARDED if name in request.headers}
    headers["Host"] = request.get_host()
    remote, forwarded = request.META.get("REMOTE_ADDR", ""), request.headers.get("X-Forwarded-For")
    headers["X-Forwarded-For"] = f"{forwarded}, {remote}" if forwarded else remote
    try:
        connection.request(request.method, request.get_full_path(), body=request.body or None, headers=headers)
        response = connection.getresponse()
        return BackendResponse(response.status, response.read(), response.getheaders())
    finally:
        connection.close()


def copy_headers(response, backend, skip=()):
    for name, value in backend.headers:
        lower = name.lower()
        if lower in HOP_BY_HOP or lower in skip:
            continue
        if lower == "set-cookie":
            response.cookies.load(value)
        else:
            response.headers[name] = value
    return response


def passthrough(backend):
    """백엔드 응답 그대로(Django admin·이미지·클릭 이동·리다이렉트 등). 보안 헤더는 백엔드 것이 살고, 빠진 것만 프론트 미들웨어가 채운다."""
    return copy_headers(HttpResponse(backend.body, status=backend.status), backend)
