import io
import re
import sys
import os
import subprocess

from django.conf import settings
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings, tag
from django.urls import reverse

from config.settings import base
from foundation import errors
from foundation.http import parse_json
from foundation.models import User
from tests.support.factories import PW
from tests.support.helpers import BASE_DIR, PROD_ENV, run_python

URLS = "tests.support.urls_api"


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

    def test_prod_leaves_https_to_the_front_proxy_but_keeps_secure_cookies(self):
        """6-5d(설계 §10 "배포 구성"): TLS·80→443·HSTS 는 앞단 nginx 몫이라 prod 는 HTTPS 리다이렉트·HSTS·X-Forwarded-Proto 신뢰를 두지 않는다.
        예전 환경값(`SSL_REDIRECT`·`BEHIND_TLS_PROXY`·`HSTS_SECONDS`)이 남아 있어도 읽지 않는다. 브라우저 구간은 HTTPS 라 쿠키는 Secure 그대로다(옛 값이 없어도)."""
        code = ("from django.conf import settings as s; "
                "print(s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS, s.SECURE_PROXY_SSL_HEADER, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.DEBUG)")
        for old in ({"SSL_REDIRECT": "1", "BEHIND_TLS_PROXY": "1", "HSTS_SECONDS": "3600"}, {}):
            r = run_python(code, "config.settings.prod", {**PROD_ENV, **old})
            self.assertEqual(r.stdout.strip(), "False 0 None True True False", (old, r.stderr))

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
        files += (BASE_DIR.parent / "ads_frontend/ui/templates").rglob("*.html")  # 6-15 뒤 우리 화면의 템플릿은 프론트에 있다(6-16i, R23)
        self.assertGreater(len(files), 25)  # 백엔드 1(관리자 첫 화면) + 프론트 29
        for path in files:
            text = path.read_text(encoding="utf-8")
            for label, rx in patterns.items():
                self.assertIsNone(rx.search(text), f"{path.relative_to(BASE_DIR.parent)}: {label}")


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

    def login_post_from_the_https_front(self):
        """앞단 nginx 가 TLS 를 끝내 Django 는 HTTP 로 받지만, 브라우저는 https 출처(`Origin`)를 싣는다."""
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("login"))
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        return client.post(reverse("login"), {"username": "csrf_user", "password": PW, "csrfmiddlewaretoken": token}, HTTP_ORIGIN="https://testserver")

    def test_a_login_post_from_the_https_front_needs_the_trusted_origin(self):
        """6-5d(설계 §10 "배포 구성"): Django 는 요청을 HTTP 로 알아 브라우저의 https 출처와 맞지 않는다 — 그래서 prod 는 `CSRF_TRUSTED_ORIGINS` 가 필수다."""
        with override_settings(CSRF_TRUSTED_ORIGINS=[]):
            self.assertEqual(self.login_post_from_the_https_front().status_code, 403)
        with override_settings(CSRF_TRUSTED_ORIGINS=["https://testserver"]):
            self.assertEqual(self.login_post_from_the_https_front().status_code, 302)  # 로그인 성공

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

    def test_parse_json_limits_numbers_to_the_javascript_safe_range_at_any_depth(self):
        """6-2c: 정수·실수 모두 ±(2^53−1), 중첩 객체·배열 안에서도. 범위 밖은 형식 오류와 다른 문구의 400 이다(더 큰 수는 문자열로 보내라고 알린다)."""
        huge = "1" + "0" * 400  # MySQL JSON 의 double 도 넘는 값(전에는 저장 오류 3140 → 503)
        for body in (
            '{"a": 9007199254740992}', '{"a": -9007199254740992}', '{"a": 18446744073709551617}', '{"a": %s}' % huge, '{"a": -%s}' % huge,
            '{"a": 12345678901234567}', '{"a": %s}' % ("9" * 5000), '{"a": 9007199254740992.0}', '{"a": -1e300}', '{"a": [{"b": [1, 9007199254740992]}]}', '{"a": {"b": -9007199254740992}}',
        ):
            with self.assertRaises(errors.InvalidRequest, msg=body[:60]) as caught:
                parse_json(json_request(body))
            self.assertIn("9007199254740991", caught.exception.detail)
        body = '{"a": 9007199254740991, "b": -9007199254740991, "c": [0, -0, 1.5, -0.25, 1e-300, 9007199254740991.0], "d": {"e": "18446744073709551617"}}'
        self.assertEqual(parse_json(json_request(body)), {
            "a": 2**53 - 1, "b": -(2**53 - 1), "c": [0, 0, 1.5, -0.25, 1e-300, float(2**53 - 1)], "d": {"e": "18446744073709551617"},
        })

    def test_parse_json_rejects_unpaired_surrogates_but_keeps_valid_pairs(self):
        """`\\ud800` 같은 짝 없는 서로게이트는 JSON 문법상 유효하지만 UTF-8 로 쓸 수 없다 → 키·값·중첩 어디서든 400(500 이 되지 않는다)."""
        for body in ('{"a": "\\ud800"}', '{"a": "\\udfff"}', '{"\\ud800": 1}', '{"a": [{"b": ["x\\udc00"]}]}', '{"a": {"\\ud83d": 1}}'):
            with self.assertRaises(errors.InvalidRequest, msg=body):
                parse_json(json_request(body))
        self.assertEqual(parse_json(json_request('{"a": "\\ud83d\\ude00", "😀": ["😀"]}')), {"a": "😀", "😀": ["😀"]})

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
            # MySQL 에서는 모델 검사가 서버 정보를 읽으려고 실제로 연결한다. 접속 값만 시험 DB 것을 넘긴다.
            env={"PATH": "/usr/bin:/bin", "DJANGO_SETTINGS_MODULE": "config.settings.prod", **PROD_ENV,
                 **{k: v for k, v in os.environ.items() if k.startswith("DB_")}},
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("WARNINGS", r.stdout + r.stderr)
