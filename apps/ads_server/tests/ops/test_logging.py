import io
import logging
import uuid

from django.test import Client, SimpleTestCase, TestCase, override_settings, tag
from django.urls import reverse

from foundation.logging import redact
from foundation.models import User
from tests.support.factories import PW


class capture_console:
    """프로젝트 LOGGING 설정의 console 핸들러 출력을 가로챈다(필터·포맷까지 실제 설정 그대로).

    verbose=True 이면 axes·django.request 로거를 잠시 DEBUG 로 올려, 테스트 설정이 낮춰 둔 로그도 실제로 만들어지게 한다.
    """

    def __init__(self, verbose=False):
        self.verbose = verbose

    def __enter__(self):
        self.handler = logging.getHandlerByName("console")
        self.buffer = io.StringIO()
        self.old = self.handler.setStream(self.buffer)
        self.levels = {}
        if self.verbose:
            for name in ("axes", "django.request", "django.security"):
                lg = logging.getLogger(name)
                self.levels[name] = lg.level
                lg.setLevel(logging.DEBUG)
        return self.buffer

    def __exit__(self, *exc):
        for name, level in self.levels.items():
            logging.getLogger(name).setLevel(level)
        self.handler.setStream(self.old)


@tag("security")
class RequestIdTests(TestCase):
    def test_every_response_has_a_request_id(self):
        r = self.client.get(reverse("login"))
        uuid.UUID(r["X-Request-ID"])
        self.assertNotEqual(self.client.get(reverse("login"))["X-Request-ID"], r["X-Request-ID"])

    def test_valid_incoming_id_is_accepted_and_invalid_is_ignored(self):
        mine = str(uuid.uuid4())
        self.assertEqual(self.client.get(reverse("login"), HTTP_X_REQUEST_ID=mine)["X-Request-ID"], mine)
        for bad in ("not-a-uuid", "abc\r\nInjected: 1", "x" * 500, mine + "extra", "<script>"):
            got = self.client.get(reverse("login"), HTTP_X_REQUEST_ID=bad)["X-Request-ID"]
            self.assertNotEqual(got, bad)
            uuid.UUID(got)

    def test_error_responses_also_carry_the_request_id(self):
        r = self.client.get("/no/such/page/")
        self.assertEqual(r.status_code, 404)
        uuid.UUID(r["X-Request-ID"])

    @override_settings(ROOT_URLCONF="tests.support.urls_api")
    def test_request_id_in_log_lines_and_problem_body(self):
        mine = str(uuid.uuid4())
        r = Client(raise_request_exception=False).get("/api/other/raise/invalid/", HTTP_X_REQUEST_ID=mine)
        self.assertEqual(r.json()["request_id"], mine)  # problem+json 본문에도 같은 요청 ID
        self.assertEqual(r["X-Request-ID"], mine)

    @override_settings(ROOT_URLCONF="tests.support.urls_api")
    def test_log_lines_emitted_inside_a_request_carry_its_id(self):
        mine = str(uuid.uuid4())
        with capture_console() as buf:
            Client().get("/logs/hello/", HTTP_X_REQUEST_ID=mine)
        self.assertIn(f"[{mine}] hello from the view", buf.getvalue())


@tag("security")
class RedactionTests(SimpleTestCase):
    def test_redact_patterns(self):
        cases = {
            "login failed password=hunter2 for user": "hunter2",
            'payload {"password": "hunter2", "a": 1}': "hunter2",
            "headers {'X-Media-Key': 'topsecretkey'}": "topsecretkey",
            "Authorization: Bearer abc.def.ghi": "abc.def.ghi",
            "cookie sessionid=abcdef123456; other=1": "abcdef123456",
            "csrfmiddlewaretoken=zzzzTOKENzzzz&x=1": "zzzzTOKENzzzz",
            "api_key=KEY123": "KEY123",
        }
        for text, secret in cases.items():
            out = redact(text)
            self.assertNotIn(secret, out, text)
            self.assertIn("[redacted]", out, text)

    def test_ordinary_messages_are_untouched(self):
        for text in ("user logged in", "keyword=abc", "passwords are hashed", "GET /accounts/login/ 200"):
            self.assertEqual(redact(text), text)

    def test_filter_applies_to_console_handler(self):
        with capture_console() as buf:
            logging.getLogger("tests.redact").warning("oops password=%s", "hunter2-marker")
            logging.getLogger("tests.redact").warning({"password": "dict-marker"}.__repr__())
        self.assertNotIn("hunter2-marker", buf.getvalue())
        self.assertNotIn("dict-marker", buf.getvalue())
        self.assertIn("[redacted]", buf.getvalue())


@tag("security")
class NoSecretsInLogsTests(TestCase):
    def test_logs_never_contain_password_or_keys(self):
        User.objects.create_user("log_user1", PW, nickname="l", class_label="1")
        wrong = "Wr0ng-LOGMARKER-pw-424242"
        key = "MEDIA-KEY-LOGMARKER-777"
        with capture_console(verbose=True) as buf:
            for _ in range(3):
                self.client.post(reverse("login"), {"username": "log_user1", "password": wrong}, REMOTE_ADDR="10.30.0.1",
                                 HTTP_X_MEDIA_KEY=key)
            self.client.post(reverse("signup"), {"username": "log_user2", "password": wrong, "password_confirm": wrong,
                                                 "nickname": "n", "class_label": "1"}, REMOTE_ADDR="10.30.0.2")
        everything = buf.getvalue()
        self.assertIn("AXES", everything)  # 로그가 실제로 만들어졌다(검사가 공회전이 아니다)
        for marker in (wrong, key, PW):
            self.assertNotIn(marker, everything)
