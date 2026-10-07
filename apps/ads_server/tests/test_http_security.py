import io
import re
import sys
import subprocess
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured  # noqa: F401
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings, tag
from django.urls import reverse

from config.settings import base
from foundation import errors
from foundation.http import parse_json
from foundation.models import User
from tests.helpers import BASE_DIR, PROD_ENV

PW = "Tr0ub4dor-horse-staple"
URLS = "tests.urls_api"


def json_request(body, content_type="application/json", declare_length=True):
    rf = RequestFactory()
    kwargs = {"content_type": content_type}
    request = rf.post("/x/", data=body, **kwargs)
    request.META["CONTENT_TYPE"] = content_type  # RequestFactory 는 빈 본문이면 Content-Type 을 넣지 않는다
    if not declare_length:
        request.META.pop("CONTENT_LENGTH", None)
    return request


@tag("security")
class SecurityHeaderTests(TestCase):
    def test_security_headers_present(self):
        r = self.client.get(reverse("login"))
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["Referrer-Policy"], "same-origin")
        self.assertEqual(r["Cross-Origin-Opener-Policy"], "same-origin")

    @override_settings(SECURE_HSTS_SECONDS=3600, SECURE_HSTS_INCLUDE_SUBDOMAINS=True, SECURE_SSL_REDIRECT=False)
    def test_hsts_header_is_sent_over_https(self):
        r = self.client.get(reverse("login"), secure=True)
        self.assertEqual(r["Strict-Transport-Security"], "max-age=3600; includeSubDomains")

    def test_prod_enforces_https_settings(self):
        code = "from django.conf import settings as s; print(s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS > 0, s.DEBUG)"
        r = subprocess.run([sys.executable, "-c", code], cwd=BASE_DIR, capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin", "DJANGO_SETTINGS_MODULE": "config.settings.prod", **PROD_ENV})
        self.assertEqual(r.stdout.strip(), "True True False", r.stderr)

    def test_csp_header_policy(self):
        r = self.client.get(reverse("login"))
        policy = {d.split(" ", 1)[0]: d.split(" ", 1)[1] if " " in d else ""
                  for d in (x.strip() for x in r["Content-Security-Policy"].split(";")) if d}
        self.assertEqual(policy["default-src"], "'self'")
        self.assertEqual(policy["script-src"], "'self'")  # 스크립트는 인라인 불가, nonce 도 없다
        # nonce 는 템플릿이 쓸 때만 헤더에 들어간다(admin 목록 화면은 아래 테스트에서 확인).
        self.assertTrue(policy["style-src"].startswith("'self'"))
        self.assertNotIn("unsafe-inline", r["Content-Security-Policy"])
        self.assertEqual(policy["img-src"], "'self' data:")
        self.assertEqual(policy["object-src"], "'none'")
        self.assertEqual(policy["base-uri"], "'self'")
        self.assertEqual(policy["form-action"], "'self'")
        self.assertEqual(policy["frame-ancestors"], "'none'")

    def test_admin_inline_style_gets_csp_nonce(self):
        admin = User.objects.create_superuser("root_csp", PW, nickname="관리", class_label="-")
        self.client.force_login(admin, backend="django.contrib.auth.backends.ModelBackend")
        r = self.client.get("/test-admin/tests_support/ownedthing/")
        self.assertEqual(r.status_code, 200)
        nonce = re.search(r"'nonce-([^']+)'", r["Content-Security-Policy"]).group(1)
        self.assertIn(f'nonce="{nonce}"', r.content.decode())  # 인라인 <style> 에 같은 nonce 가 붙는다

    def test_no_inline_script_or_style_in_templates(self):
        patterns = {
            "인라인 <script>": re.compile(r"<script(?![^>]*\bsrc=)", re.I),
            "<style> 블록": re.compile(r"<style\b", re.I),
            "style= 속성": re.compile(r"\sstyle\s*=", re.I),
            "이벤트 핸들러 속성": re.compile(r"\son[a-z]+\s*=", re.I),
            "javascript: URL": re.compile(r"javascript:", re.I),
        }
        files = [p for app in ("console", "foundation") for p in (BASE_DIR / app).rglob("*.html")]
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for label, rx in patterns.items():
                self.assertIsNone(rx.search(text), f"{path.relative_to(BASE_DIR)}: {label}")


@tag("security")
class CsrfTests(TestCase):
    def setUp(self):
        self.strict = Client(enforce_csrf_checks=True)
        User.objects.create_user("csrf_user", PW, nickname="c", class_label="1")

    def test_csrf_enforced_on_post_views(self):
        self.assertEqual(self.strict.post(reverse("signup"), {"username": "x"}).status_code, 403)
        self.assertEqual(self.strict.post(reverse("login"), {"username": "csrf_user", "password": PW}).status_code, 403)
        self.client.force_login(User.objects.get(username="csrf_user"),
                                backend="django.contrib.auth.backends.ModelBackend")
        strict_logged_in = Client(enforce_csrf_checks=True)
        strict_logged_in.cookies = self.client.cookies
        self.assertEqual(strict_logged_in.post(reverse("logout")).status_code, 403)

    def test_csrf_failure_page_is_html_without_internals(self):
        r = self.strict.post(reverse("signup"), {"username": "x"})
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("CSRF", r.content.decode())

    def test_get_does_not_need_token(self):
        self.assertEqual(self.strict.get(reverse("login")).status_code, 200)

    def test_csrf_exempt_list_is_single_and_exact(self):
        self.assertEqual(base.CSRF_EXEMPT_PREFIXES, ["/api/media/"])

    @override_settings(ROOT_URLCONF=URLS)
    def test_csrf_exempt_only_for_allowlisted_prefixes(self):
        body = '{"a": 1}'
        ok = self.strict.post("/api/media/echo/", body, content_type="application/json")
        self.assertEqual(ok.status_code, 200)  # 허용 목록: CSRF 토큰 없이 통과
        blocked = self.strict.post("/api/other/echo/", body, content_type="application/json")
        self.assertEqual(blocked.status_code, 403)  # 목록 밖: 차단
        self.assertEqual(blocked["Content-Type"], "application/problem+json")


@tag("security")
class ParseJsonTests(SimpleTestCase):
    def assertRejects(self, exc, body, **kw):
        with self.assertRaises(exc, msg=repr(body)[:60]):
            parse_json(json_request(body), **kw)

    def test_valid_object(self):
        self.assertEqual(parse_json(json_request('{"a": 1, "b": [1, 2]}')), {"a": 1, "b": [1, 2]})

    def test_content_type_variants(self):
        self.assertEqual(parse_json(json_request("{}", "application/json; charset=utf-8")), {})
        for bad in ("text/plain", "application/json-evil", "application/x-www-form-urlencoded", ""):
            with self.assertRaises(errors.UnsupportedMediaType, msg=bad):
                parse_json(json_request("{}", bad))

    def test_parse_json_rejects_nan_infinity(self):
        for body in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e999999}'):
            self.assertRejects(errors.InvalidRequest, body)

    def test_parse_json_depth_limit(self):
        deep = '{"a": {"b": {"c": {"d": 1}}}}'  # 깊이 4
        self.assertRejects(errors.InvalidRequest, deep, max_depth=3)
        self.assertEqual(parse_json(json_request(deep), max_depth=4), {"a": {"b": {"c": {"d": 1}}}})
        self.assertRejects(errors.InvalidRequest, '{"a":' + "[" * 5000 + "]" * 5000 + "}")  # 재귀 한도를 넘는 중첩

    def test_parse_json_size_limit(self):
        self.assertRejects(errors.PayloadTooLarge, '{"a": "' + "x" * 100 + '"}', max_bytes=64)
        request = json_request('{"a": "' + "x" * 100 + '"}', declare_length=False)  # Content-Length 가 없어도 막는다
        with self.assertRaises(errors.PayloadTooLarge):
            parse_json(request, max_bytes=64)
        self.assertEqual(parse_json(json_request('{"a": 1}'), max_bytes=64), {"a": 1})

    def test_size_limit_does_not_read_whole_body(self):
        body = ('{"a": "' + "x" * 100_000 + '"}').encode()
        request = json_request("{}", declare_length=False)
        request._stream = io.BytesIO(body)  # 읽은 위치를 확인할 수 있는 스트림
        with self.assertRaises(errors.PayloadTooLarge):
            parse_json(request, max_bytes=64)
        self.assertEqual(request._stream.tell(), 65)  # 한도 + 1 바이트까지만 읽었다

    def test_parse_json_non_object_rejected(self):
        for body in ("[]", "1", '"str"', "null", "true"):
            self.assertRejects(errors.InvalidRequest, body)

    def test_empty_and_invalid_encodings_and_duplicates(self):
        self.assertRejects(errors.InvalidRequest, "")
        self.assertRejects(errors.InvalidRequest, b"\xff\xfe{}")
        self.assertRejects(errors.InvalidRequest, '{"a": 1, "a": 2}')
        self.assertRejects(errors.InvalidRequest, "{")
        self.assertRejects(errors.InvalidRequest, "1" * 5000)  # 파이썬 정수 변환 한도


@tag("security")
@override_settings(ROOT_URLCONF=URLS)
class ErrorResponseTests(TestCase):
    def setUp(self):
        self.c = Client(raise_request_exception=False)

    def test_malformed_inputs_never_500(self):
        bodies = [b"", b"{", b"null", b"[]", b"\xff\xfe", b'{"a": NaN}', b'{"a": 1e999999}', b"{" * 20000,
                  b'{"a":' + b"[" * 100000, b'{"a": "' + b"x" * 200000 + b'"}', b'{"a":1,"a":2}', b"1" * 6000,
                  b'{"\x00": 1}', "{\"a\": \"\ud800\"}".encode("utf-8", "surrogatepass")]
        for body in bodies:
            r = self.c.post("/api/media/echo/", body, content_type="application/json")
            self.assertLess(r.status_code, 500, repr(body)[:60])
            self.assertGreaterEqual(r.status_code, 400, repr(body)[:60])
            self.assertEqual(r["Content-Type"], "application/problem+json", repr(body)[:60])
        for ctype in ("text/plain", "application/xml", "multipart/form-data; boundary=x"):
            r = self.c.post("/api/media/echo/", b"{}", content_type=ctype)
            self.assertLess(r.status_code, 500, ctype)

    def test_api_errors_are_problem_json(self):
        expected = {"invalid": 400, "unauthorized": 401, "forbidden": 403, "not_found": 404, "conflict": 409,
                    "too_large": 413, "unsupported": 415, "rate": 429, "unavailable": 503,
                    "http404": 404, "denied": 403, "boom": 500}
        for kind, status in expected.items():
            r = self.c.get(f"/api/other/raise/{kind}/")
            self.assertEqual(r.status_code, status, kind)
            self.assertEqual(r["Content-Type"], "application/problem+json", kind)
            body = r.json()
            self.assertEqual(body["status"], status)
            for key in ("type", "title", "code"):
                self.assertIn(key, body, kind)
            self.assertTrue(body["type"].startswith("/problems/"))
            self.assertNotIn("secret-internal-detail", r.content.decode(), kind)
            self.assertNotIn("Traceback", r.content.decode(), kind)

    def test_retry_after_and_errors_list(self):
        self.assertEqual(self.c.get("/api/other/raise/rate/")["Retry-After"], "7")
        self.assertEqual(self.c.get("/api/other/raise/unavailable/")["Retry-After"], "3")
        body = self.c.get("/api/other/raise/invalid/").json()
        self.assertEqual(body["errors"], [{"pointer": "/x", "message": "m"}])
        self.assertEqual(body["detail"], "bad")

    def test_error_pages_do_not_leak_internals(self):
        for kind, status in (("boom", 500), ("http404", 404), ("denied", 403)):
            r = self.c.get(f"/boom/{kind}/")
            self.assertEqual(r.status_code, status)
            text = r.content.decode()
            self.assertNotIn("secret-internal-detail", text)
            self.assertNotIn("Traceback", text)
            self.assertIn("text/html", r["Content-Type"])


@tag("security")
class NoStoreTests(TestCase):
    def test_authenticated_pages_are_no_store(self):
        User.objects.create_user("store_user", PW, nickname="s", class_label="1")
        self.client.post(reverse("login"), {"username": "store_user", "password": PW})
        for path in ("/advertiser/", reverse("login")):
            r = self.client.get(path)
            self.assertIn("no-store", r["Cache-Control"], path)
            self.assertIn("private", r["Cache-Control"], path)

    @override_settings(ROOT_URLCONF=URLS)
    def test_explicit_cache_control_is_preserved(self):
        r = self.client.get("/cacheable/")
        self.assertEqual(r["Cache-Control"], "no-cache")  # 이미지 서빙(0-5) 같은 응답이 정한 값은 덮어쓰지 않는다

    @override_settings(ROOT_URLCONF=URLS)
    def test_api_responses_are_no_store(self):
        r = Client(raise_request_exception=False).get("/api/other/raise/conflict/")
        self.assertIn("no-store", r["Cache-Control"])


@tag("security")
class DeployCheckTests(SimpleTestCase):
    def test_check_deploy_has_no_warnings(self):
        r = subprocess.run(
            [sys.executable, "-m", "django", "check", "--deploy", "--fail-level", "WARNING"],
            cwd=BASE_DIR, capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "DJANGO_SETTINGS_MODULE": "config.settings.prod", **PROD_ENV},
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("WARNINGS", r.stdout + r.stderr)
