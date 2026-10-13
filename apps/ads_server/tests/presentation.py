"""시험 클라이언트(설계 §6.6 "6-15 분리"): 백엔드의 화면 데이터를 **실제 프론트 렌더러**(apps/ads_frontend/ui/rendering.py)로 그려 HTML 로 바꾼다
— 팀 메타버스의 시험 방식. 그래서 화면 시험의 HTML 단언을 그대로 쓴다. 전달(헤더·쿠키·본문)은 프론트 시험이 따로 본다.

렌더러는 이 프로세스(백엔드 설정)에서 돈다: URL 이름·경로(`{% url %}`·현재 메뉴)와 STATIC_URL 은 두 쪽이 같다(경로 표 시험이 지킨다).
요청은 백엔드가 받은 요청을 쓴다 — 프론트도 같은 경로·질의를 받는다. 보안 헤더는 백엔드 응답의 것(프론트도 같은 값을 붙인다)."""
import json
import sys
from pathlib import Path

from django.conf import settings
from django.template import Context
from django.test import Client

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
                html, context = rendering.render(response.wsgi_request, data["presentation"])
                response.content = html.encode()
                response["Content-Type"] = "text/html; charset=utf-8"
                response.context = Context(context)
                response.presentation = data["presentation"]
        return response
