"""프론트의 전달과 통과(설계 §6.6 "6-15 분리"): 입력·쿠키는 그대로 백엔드로, 백엔드 응답은 그대로 브라우저로. 실제 HTTP 로 가짜 백엔드를 띄워 본다."""
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import NoReverseMatch, reverse


class FakeBackend(BaseHTTPRequestHandler):
    """받은 요청을 기록하고 정해 둔 응답을 돌려준다."""

    seen = []
    reply = (200, [("Content-Type", "text/plain")], b"ok")
    routes = {}  # 경로마다 다른 응답(없으면 reply)

    def _handle(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        FakeBackend.seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
        status, headers, payload = FakeBackend.routes.get(self.path.split("?")[0], FakeBackend.reply)
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_HEAD = _handle

    def log_message(self, *args):
        pass


class BackendCase(SimpleTestCase):
    """가짜 백엔드를 띄우고 프론트가 그쪽으로 넘기게 한다."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.backend = override_settings(BACKEND_URL=f"http://127.0.0.1:{cls.server.server_port}")
        cls.backend.enable()

    @classmethod
    def tearDownClass(cls):
        cls.backend.disable()
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def setUp(self):
        FakeBackend.seen = []
        FakeBackend.reply = (200, [("Content-Type", "text/plain")], b"ok")
        FakeBackend.routes = {}


class TransportTests(BackendCase):
    def test_the_request_goes_to_the_backend_unchanged_with_the_forwarded_address_appended(self):
        r = self.client.get("/advertiser/campaigns/?page=2", HTTP_COOKIE="sessionid=abc; csrftoken=t", HTTP_X_CSRFTOKEN="t",
                            HTTP_AUTHORIZATION="Bearer x", HTTP_X_FORWARDED_FOR="203.0.113.7", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(r.status_code, 200)
        (seen,) = FakeBackend.seen
        self.assertEqual((seen["method"], seen["path"]), ("GET", "/advertiser/campaigns/?page=2"))
        self.assertEqual(seen["headers"]["Cookie"], "sessionid=abc; csrftoken=t")
        self.assertEqual(seen["headers"]["X-CSRFToken"], "t")
        self.assertEqual(seen["headers"]["Host"], "testserver")  # 사용자가 연 호스트 그대로
        self.assertEqual(seen["headers"]["X-Forwarded-For"], "203.0.113.7, 127.0.0.1")  # nginx 처럼 상대 주소를 덧붙인다
        self.assertNotIn("Authorization", seen["headers"])  # 넘기는 헤더는 정해 둔 것만
        self.client.get("/", REMOTE_ADDR="10.0.0.9")
        self.assertEqual(FakeBackend.seen[-1]["headers"]["X-Forwarded-For"], "10.0.0.9")

    def test_an_upload_body_is_forwarded_byte_for_byte(self):
        body = b"--b\r\nContent-Disposition: form-data; name=\"new-image\"; filename=\"x.png\"\r\n\r\n\x89PNG\x00\xff\r\n--b--\r\n"
        self.client.generic("POST", "/advertiser/creatives/", body, content_type="multipart/form-data; boundary=b")
        (seen,) = FakeBackend.seen
        self.assertEqual((seen["body"], seen["headers"]["Content-Type"]), (body, "multipart/form-data; boundary=b"))

    def test_the_response_comes_back_unchanged_and_only_missing_security_headers_are_added(self):
        FakeBackend.reply = (302, [("Location", "/accounts/login/"), ("Set-Cookie", "sessionid=new; HttpOnly; Path=/; SameSite=Lax"),
                                   ("Set-Cookie", "csrftoken=t2; Path=/; SameSite=Lax"), ("Content-Security-Policy", "default-src 'self'; style-src 'nonce-abc'"),
                                   ("Cache-Control", "no-store"), ("Connection", "close"), ("X-Request-ID", "6f1c2b0e-0f6a-4d0e-9b8a-7c1d2e3f4a5b")], b"")
        r = self.client.post("/accounts/logout/")
        self.assertEqual((r.status_code, r["Location"], r["Cache-Control"]), (302, "/accounts/login/", "no-store"))
        self.assertEqual((r.cookies["sessionid"].value, r.cookies["csrftoken"].value), ("new", "t2"))
        self.assertTrue(r.cookies["sessionid"]["httponly"])
        self.assertEqual(r["Content-Security-Policy"], "default-src 'self'; style-src 'nonce-abc'")  # 백엔드 것을 덮지 않는다(관리 사이트의 nonce)
        self.assertEqual((r["X-Content-Type-Options"], r["X-Frame-Options"]), ("nosniff", "DENY"))  # 빠진 것은 채운다
        self.assertEqual(r["X-Request-ID"], "6f1c2b0e-0f6a-4d0e-9b8a-7c1d2e3f4a5b")
        self.assertFalse(r.has_header("Connection"))

    def test_binary_responses_pass_through(self):
        FakeBackend.reply = (200, [("Content-Type", "image/png"), ("ETag", '"x"')], b"\x89PNG\x00\xff")
        r = self.client.get("/assets/abc.png", HTTP_IF_NONE_MATCH='"y"')
        self.assertEqual((r.content, r["Content-Type"], r["ETag"]), (b"\x89PNG\x00\xff", "image/png", '"x"'))
        self.assertEqual(FakeBackend.seen[0]["headers"]["If-None-Match"], '"y"')

    def test_the_media_api_is_not_public(self):
        self.assertEqual(self.client.post("/api/media/v1/decisions", {}).status_code, 404)
        self.assertEqual(FakeBackend.seen, [])

    def test_a_body_over_the_limit_is_not_sent_to_the_backend(self):
        """백엔드로 흘려보내지 않고 백엔드와 같은 문구의 413 화면을 그린다(시험 설정의 상한 = 업로드 2MB + multipart 여유)."""
        r = self.client.generic("POST", "/advertiser/creatives/", b"x" * (settings.MAX_BODY_BYTES + 1), content_type="application/octet-stream")
        self.assertContains(r, "이미지는 2MB까지 올릴 수 있습니다.", status_code=413)
        self.assertEqual(FakeBackend.seen, [])

    def test_an_unreachable_backend_is_502(self):
        with override_settings(BACKEND_URL="http://127.0.0.1:9"):
            self.assertEqual(self.client.get("/advertiser/").status_code, 502)

    def test_health_does_not_need_the_backend(self):
        self.assertEqual(self.client.get("/health/").json(), {"service": "ads-frontend", "status": "ok"})
        self.assertEqual(FakeBackend.seen, [])


class RouteTests(SimpleTestCase):
    def test_named_routes_are_the_backends_paths(self):
        """템플릿의 {% url %} 이 백엔드와 같은 주소를 만든다(두 쪽이 같은지는 백엔드 시험이 경로 표 전체로 본다)."""
        self.assertEqual(reverse("campaign_detail", args=["c1"]), "/advertiser/campaigns/c1/")
        self.assertEqual(reverse("operator:media_list"), "/dev-admin/operator/media/")
        self.assertEqual(reverse("admin:index"), "/dev-admin/")
        self.assertEqual(reverse("login"), "/accounts/login/")

    def test_every_url_name_in_the_templates_resolves(self):
        """템플릿이 거는 {% url %} 이름은 모두 프론트의 경로 표에 있다 — 없으면 그 화면이 프론트에서만 500 이다(6-22: 운영 화면 광고주 상세의
        '비밀번호 초기화'. 백엔드 시험은 백엔드의 URL 설정으로 그려 잡지 못했다)."""
        missing = []
        for template in (Path(settings.BASE_DIR) / "ui/templates").rglob("*.html"):
            for name in re.findall(r"\{%\s*url\s+['\"]([^'\"]+)['\"]", template.read_text(encoding="utf-8")):
                if not any(self.resolves(name, n) for n in range(4)):  # 인자 수는 화면마다 다르다(0~3)
                    missing.append(f"{template.name}: {name}")
        self.assertEqual(missing, [])

    @staticmethod
    def resolves(name, count):
        try:
            reverse(name, args=["x"] * count)
            return True
        except NoReverseMatch:
            return False


@override_settings(WHITENOISE_USE_FINDERS=True)
class StaticTests(SimpleTestCase):
    def test_the_console_and_admin_static_files_are_served_by_the_frontend(self):
        for path, kind in (("/static/console/app.css", "text/css"), ("/static/console/confirm.js", "text/javascript"), ("/static/admin/css/base.css", "text/css")):
            r = self.client.get(path)
            self.assertEqual((r.status_code, r["Content-Type"].split(";")[0], r["X-Content-Type-Options"]), (200, kind, "nosniff"), path)


class RenderingTests(BackendCase):
    """화면 데이터를 받으면 그린다(설계 §6.6 "6-15 분리"). 백엔드의 쿠키·캐시 헤더는 옮기고, 보안 헤더는 이 응답의 것(CSP nonce)이다."""

    def presentation(self, template, context, status=200, headers=()):
        import json

        body = json.dumps({"presentation": {"template": template, "context": {"user": {"is_authenticated": False}, "messages": [],
                                                                                "csrf_token": "", **context}}}).encode()
        FakeBackend.reply = (status, [("Content-Type", "application/json"), *headers], body)

    def test_screen_data_is_drawn_with_the_backends_cookies_and_status(self):
        self.presentation("foundation/error.html", {"status": 404, "title": "없는 화면", "message": "찾을 수 없습니다."}, status=404,
                          headers=[("Set-Cookie", "sessionid=s; HttpOnly; Path=/"), ("Cache-Control", "private, no-store"),
                                   ("Content-Security-Policy", "default-src 'self'; style-src 'self' 'nonce-backend'")])
        r = self.client.get("/advertiser/nowhere/")
        self.assertEqual((r.status_code, r["Content-Type"]), (404, "text/html; charset=utf-8"))
        self.assertContains(r, "<h1>없는 화면</h1>", status_code=404)
        self.assertEqual((r.cookies["sessionid"].value, r["Cache-Control"]), ("s", "private, no-store"))
        self.assertNotIn("nonce-backend", r["Content-Security-Policy"])  # 백엔드 응답의 nonce 가 아니라 이 응답의 CSP

    def test_the_operator_layout_speaks_korean_without_the_admin_app(self):
        """운영 화면은 Django admin 의 템플릿을 상속한다 — 그 문구의 번역(admin 앱의 locale)을 프론트가 직접 읽는다."""
        self.presentation("operator/_base.html", {
            "title": "매체", "site_header": "광고 서버 관리", "site_title": "광고 서버", "site_url": "/", "has_permission": True, "is_popup": False,
            "is_nav_sidebar_enabled": False, "available_apps": [],
            "user": {"is_authenticated": True, "is_active": True, "is_staff": True, "get_username": "admin", "has_usable_password": True},
            "csrf_token": "token-from-the-backend",
        })
        r = self.client.get("/dev-admin/operator/media/")
        self.assertContains(r, "로그아웃")
        self.assertContains(r, 'name="csrfmiddlewaretoken" value="token-from-the-backend"')  # 백엔드가 준 토큰 그대로 — 프론트가 새로 만들지 않는다
        import re

        nonce = re.search(r"'nonce-([^']+)'", r["Content-Security-Policy"]).group(1)
        self.assertContains(r, f'nonce="{nonce}"')  # 관리 템플릿의 <link>·<script> 는 이 응답의 CSP nonce
        self.assertContains(r, 'href="/dev-admin/"')  # {% url 'admin:index' %}
