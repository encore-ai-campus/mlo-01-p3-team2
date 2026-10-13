"""시험 클라이언트(설계 §6.6 "6-15 분리"): 백엔드의 화면 데이터를 **실제 프론트 렌더러**(apps/ads_frontend/ui/rendering.py)로 그려 HTML 로 바꾼다
— 팀 메타버스의 시험 방식. 그래서 화면 시험의 HTML 단언을 그대로 쓴다. 전달(헤더·쿠키·본문)은 프론트 시험이 따로 본다.

렌더러는 이 프로세스(백엔드 설정)에서 돈다: URL 이름·경로(`{% url %}`·현재 메뉴)와 STATIC_URL 은 두 쪽이 같다(경로 표 시험이 지킨다).
요청은 **프론트처럼 따로 만든 요청**(같은 메서드·경로·질의, 백엔드의 세션·CSRF 상태는 없음)이다 — 백엔드가 받은 요청으로 그리면
프론트 쪽에서만 생기는 결함(예: 렌더러가 프론트 요청으로 CSRF 토큰을 새로 만들어 백엔드의 토큰을 덮음)을 놓친다. 보안 헤더는 백엔드 응답의 것."""
import json
import sys
from pathlib import Path

from django.conf import settings
from django.template import Context
from django.test import Client, RequestFactory
from django.urls import Resolver404, resolve

FRONTEND = Path(settings.BASE_DIR).parent / "ads_frontend"
if str(FRONTEND) not in sys.path:
    sys.path.append(str(FRONTEND))  # 뒤에 붙인다 — 백엔드의 같은 이름 패키지(config 등)를 가리지 않게

from ui import rendering  # noqa: E402


class PresentationClient(Client):
    def request(self, **request):
        response = super().request(**request)
        if response.get("Content-Type", "").startswith("application/json"):
            data = json.loads(response.content)
            if isinstance(data, dict) and "presentation" in data:
                html, context = rendering.render(frontend_request(response.wsgi_request), data["presentation"])
                response.content = html.encode()
                response["Content-Type"] = "text/html; charset=utf-8"
                response.context = Context(context)
                response.presentation = data["presentation"]
        return response


def frontend_request(backend_request):
    """프론트가 받는 것과 같은 요청(메서드·경로·질의·이름 경로). 쿠키·세션·CSRF 상태는 프론트에 없다."""
    request = RequestFactory().generic(backend_request.method, backend_request.get_full_path())
    if hasattr(backend_request, "_csp_nonce"):  # 프론트는 자기 CSP 미들웨어의 nonce 를 쓴다 — 시험에서는 이 응답의 CSP 헤더(백엔드 것)와 맞춘다
        request._csp_nonce = backend_request._csp_nonce
    try:
        request.resolver_match = resolve(request.path_info)  # 프론트의 경로 표 = 백엔드의 이름(test_frontend_sync)
    except Resolver404:
        request.resolver_match = None
    return request
