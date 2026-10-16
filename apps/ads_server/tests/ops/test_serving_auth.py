"""C1 인증·요청 제한(2-2). 실제 데코레이터를 붙인 임시 뷰(tests/support/urls_media_api.py)에 계약 경로로 요청하고, 응답을 계약에 대조한다."""
import uuid
from unittest import mock

from django.db import OperationalError
from django.test import Client, TestCase, override_settings, tag

from masters import api as masters
from serving_api.auth import CHALLENGE
from serving_api.throttle import buckets
from tests.support.contract_support import Contract, ProviderContractMixin, cookie_problems
from tests.support.factories import make_admin
from tests.support.cases import Cases

BASE = "/api/media/v1"
DID, RID = uuid.uuid4(), uuid.uuid4()
# (계약 경로, 메서드, 실제 URL, 요청 제한 경로군)
OPERATIONS = [
    ("/decisions", "post", f"{BASE}/decisions", "decisions"),
    ("/decisions/{decision_id}", "get", f"{BASE}/decisions/{DID}", "reads"),
    ("/decisions/{decision_id}/reactions/{reaction_id}", "put", f"{BASE}/decisions/{DID}/reactions/{RID}", "reactions"),
    ("/decisions/{decision_id}/reactions/{reaction_id}", "get", f"{BASE}/decisions/{DID}/reactions/{RID}", "reads"),
]


class FakeClock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


@override_settings(ROOT_URLCONF="tests.support.urls_media_api")
class MediaApiBase(ProviderContractMixin, TestCase):
    contract = Contract("serving")

    def setUp(self):
        self.admin = make_admin()
        self.media = masters.create_media(self.admin, "메타버스")
        self.key = masters.issue_media_key(self.admin, self.media.media_id).key
        self.clock = FakeClock()
        buckets.reset()
        buckets.clock = self.clock
        self.addCleanup(self.restore_clock)

    @staticmethod
    def restore_clock():
        import time

        buckets.clock = time.monotonic
        buckets.reset()

    def call(self, method, url, key="USE", body=None, content_type="application/json", **extra):
        headers = dict(extra)
        if key == "USE":
            key = self.key
        if key is not None:
            headers["HTTP_X_MEDIA_KEY"] = key
        send = getattr(self.client, method)
        if method in ("post", "put"):
            data = '{"slot_id": "x"}' if body is None else body
            return send(url, data=data, content_type=content_type, **headers)
        return send(url, **headers)


@tag("security")
class AuthenticationTests(Cases, MediaApiBase):
    def case_missing_or_invalid_key_is_401_with_challenge_and_identical_bodies(self):
        key_hex, secret = self.key.split(".")
        bad = {
            "none": None, "empty": "", "blank": "   ", "garbage": "garbage", "unknown key_id": uuid.uuid4().hex + "." + secret,
            "wrong secret": key_hex + "." + ("A" if secret[0] != "A" else "B") + secret[1:], "truncated": self.key[:-3],
        }
        bodies = set()
        for label, key in bad.items():
            for contract_path, method, url, _group in OPERATIONS:
                response = self.call(method, url, key=key)
                self.assertEqual(response.status_code, 401, (label, method, url))
                self.assertEqual(response["WWW-Authenticate"], CHALLENGE)
                self.assertEqual(response["Content-Type"], "application/problem+json")
                self.assertContract(self.contract, contract_path, method, response)  # 상태·헤더·본문이 계약대로
            bodies.add(response.json()["detail"])
        self.assertEqual(len(bodies), 1)  # 어떤 이유로 거절됐는지 알리지 않는다

    def case_revoked_and_expired_keys_are_401(self):
        revoked = masters.issue_media_key(self.admin, self.media.media_id)
        masters.revoke_media_key(self.admin, revoked.key_id)
        self.assertEqual(self.call("get", f"{BASE}/decisions/{DID}", key=revoked.key).status_code, 401)
        old = self.key
        masters.rotate_media_key(self.admin, self.media.media_id, grace_seconds=0)  # 옛 키는 바로 만료
        self.assertEqual(self.call("get", f"{BASE}/decisions/{DID}", key=old).status_code, 401)

    def case_inactive_media_with_a_valid_key_is_403_and_with_a_bad_key_is_401(self):
        masters.set_media_active(self.admin, self.media.media_id, False)
        for contract_path, method, url, _group in OPERATIONS:
            blocked = self.call(method, url)
            self.assertEqual(blocked.status_code, 403, (method, url))
            self.assertNotIn("WWW-Authenticate", blocked.headers)
            self.assertContract(self.contract, contract_path, method, blocked)
            self.assertEqual(self.call(method, url, key="nope").status_code, 401)  # 키가 틀리면 비활성 여부를 알리지 않는다
        masters.set_media_active(self.admin, self.media.media_id, True)
        self.assertEqual(self.call("get", f"{BASE}/decisions/{DID}").status_code, 200)

    def case_authentication_precedes_input_validation(self):
        """인증은 입력 검증보다 먼저다: 키가 없으면 본문이 깨졌어도 잘못된 형식이어도 401 이다."""
        for key, expected in ((None, 401), ("nope", 401), ("USE", None)):
            for label, kwargs in {
                "invalid json": dict(body="{not json"), "wrong content type": dict(body="x", content_type="text/plain"), "empty": dict(body=""),
            }.items():
                response = self.call("post", f"{BASE}/decisions", key=key, **kwargs)
                if expected:
                    self.assertEqual(response.status_code, expected, label)
                else:
                    self.assertIn(response.status_code, (400, 415), label)  # 키가 맞아야 비로소 입력을 검증한다

    def case_valid_key_reaches_the_view_with_the_media_identity(self):
        response = self.call("post", f"{BASE}/decisions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["media_id"], str(self.media.media_id))

    def case_both_keys_work_during_rotation_and_use_the_same_bucket(self):
        new = masters.rotate_media_key(self.admin, self.media.media_id, grace_seconds=3600).key
        for key in (self.key, new):
            self.assertEqual(self.call("get", f"{BASE}/decisions/{DID}", key=key).status_code, 200)

    def case_no_csrf_token_needed_and_no_cookies_ever(self):
        client = Client(enforce_csrf_checks=True)  # /api/media/ 는 CSRF 예외다(키 인증 서버 간 API)
        responses = [
            client.post(f"{BASE}/decisions", data='{"a": 1}', content_type="application/json", HTTP_X_MEDIA_KEY=self.key),
            client.post(f"{BASE}/decisions", data="{}", content_type="application/json"),  # 401
        ]
        masters.set_media_active(self.admin, self.media.media_id, False)
        responses.append(client.get(f"{BASE}/decisions/{DID}", HTTP_X_MEDIA_KEY=self.key))  # 403
        self.assertEqual([r.status_code for r in responses], [200, 401, 403])
        for response in responses:
            self.assertEqual(cookie_problems(response), [])

    def case_rejected_key_log_has_the_public_id_but_never_the_secret(self):
        key_hex, secret = self.key.split(".")
        with self.assertLogs("serving_api.auth", "WARNING") as logs:
            wrong = key_hex + "." + ("B" if secret[0] == "A" else "A") + secret[1:]  # 첫 글자가 반드시 달라진다
            self.assertNotEqual(wrong, self.key)
            self.assertEqual(self.call("get", f"{BASE}/decisions/{DID}", key=wrong).status_code, 401)
            self.assertEqual(self.call("get", f"{BASE}/decisions/{DID}", key="SECRET-LOOKING-VALUE-123").status_code, 401)
        text = "\n".join(logs.output)
        self.assertIn(key_hex, text)  # 어느 키가 거절됐는지 공개 식별자로 추적한다
        self.assertNotIn(secret[1:], text)
        self.assertNotIn("SECRET-LOOKING", text)  # 형식이 틀린 값은 아예 기록하지 않는다
        self.assertIn("key_id=-", text)

    def test_authentication(self):
        self.run_cases()


@tag("security")
class StorageFailureTests(Cases, MediaApiBase):
    """키 저장소(DB)가 잠기거나 끊기면 500 이 아니라 **503 + Retry-After** 다(계약 C1 공통 응답)."""

    def assert_unavailable(self, method, contract_path, url):
        response = self.call(method, url)
        self.assertEqual(response.status_code, 503, (method, url))
        self.assertEqual(response["Content-Type"], "application/problem+json")
        self.assertEqual(response.json()["code"], "unavailable")
        self.assertEqual(response["Retry-After"], "1")
        self.assertTrue(response["X-Request-ID"])
        self.assertContract(self.contract, contract_path, method, response)

    def case_key_lookup_failure_is_503_on_every_operation_and_the_view_never_runs(self):
        with mock.patch("serving_api.auth.masters.authenticate_media_key", side_effect=OperationalError("database is locked")), \
                mock.patch("tests.support.urls_media_api.parse_json") as view_ran:
            for contract_path, method, url, _group in OPERATIONS:
                self.assert_unavailable(method, contract_path, url)
            view_ran.assert_not_called()
        self.assertEqual(self.call("get", f"{BASE}/decisions/{DID}").status_code, 200)  # 복구되면 바로 정상

    def case_storage_failure_inside_the_view_is_503_too(self):
        with mock.patch("tests.support.urls_media_api.parse_json", side_effect=OperationalError("disk I/O error")):
            self.assert_unavailable("post", "/decisions", f"{BASE}/decisions")

    def case_a_failed_lookup_consumes_no_token_and_other_errors_are_not_turned_into_503(self):
        with mock.patch("serving_api.auth.masters.authenticate_media_key", side_effect=OperationalError("locked")):
            for _ in range(10):
                self.call("get", f"{BASE}/decisions/{DID}")
        self.assertEqual(buckets.take((self.media.media_id, "reads"), 1, 1), None)  # 한 번도 쓰지 않았다
        with mock.patch("tests.support.urls_media_api.parse_json", side_effect=ValueError("bug")), \
                self.assertRaises(ValueError):
            Client(raise_request_exception=True).post(
                f"{BASE}/decisions", data="{}", content_type="application/json", HTTP_X_MEDIA_KEY=self.key
            )  # 프로그래밍 오류는 가리지 않는다(일괄 503 금지)

    def test_serving_auth_storage_failure(self):
        self.run_cases()


@tag("security")
@override_settings(MEDIA_RATE_LIMITS={"decisions": (2, 3), "reactions": (4, 5), "reads": (1, 2)})
class RateLimitTests(Cases, MediaApiBase):
    def hit(self, method, url, **kw):
        return self.call(method, url, **kw)

    def case_burst_then_429_with_retry_after_and_refill(self):
        url = f"{BASE}/decisions"
        self.assertEqual([self.hit("post", url).status_code for _ in range(3)], [200, 200, 200])
        blocked = self.hit("post", url)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], "1")
        self.assertContract(self.contract, "/decisions", "post", blocked)  # Problem(status=429) + Retry-After 정수
        self.assertEqual(blocked.json()["code"], "rate_limited")
        self.clock.now += 1.0  # 초당 2개 충전
        self.assertEqual([self.hit("post", url).status_code for _ in range(3)], [200, 200, 429])

    def case_every_operation_returns_a_contract_conforming_429(self):
        for contract_path, method, url, group in OPERATIONS:
            buckets.reset()
            burst = {"decisions": 3, "reactions": 5, "reads": 2}[group]
            for _ in range(burst):
                self.assertEqual(self.hit(method, url).status_code, 200)
            blocked = self.hit(method, url)
            self.assertEqual(blocked.status_code, 429, (method, url))
            self.assertContract(self.contract, contract_path, method, blocked)

    def case_buckets_are_per_media_and_per_group(self):
        other = masters.create_media(self.admin, "다른 매체")
        other_key = masters.issue_media_key(self.admin, other.media_id).key
        [self.hit("post", f"{BASE}/decisions") for _ in range(3)]
        self.assertEqual(self.hit("post", f"{BASE}/decisions").status_code, 429)
        self.assertEqual(self.hit("post", f"{BASE}/decisions", key=other_key).status_code, 200)  # 다른 매체는 영향 없음
        self.assertEqual(self.hit("get", f"{BASE}/decisions/{DID}").status_code, 200)  # 같은 매체의 다른 경로군도 영향 없음
        self.assertEqual(self.hit("put", f"{BASE}/decisions/{DID}/reactions/{RID}").status_code, 200)
        self.assertEqual(self.hit("get", f"{BASE}/decisions/{DID}").status_code, 200)  # 조회 버킷(버스트 2)의 두 번째
        self.assertEqual(self.hit("get", f"{BASE}/decisions/{DID}").status_code, 429)  # 조회 버킷만 따로 소진
        self.assertEqual(self.hit("put", f"{BASE}/decisions/{DID}/reactions/{RID}").status_code, 200)  # 반응 버킷은 그대로

    def case_rotating_the_key_keeps_the_same_bucket(self):
        [self.hit("post", f"{BASE}/decisions") for _ in range(3)]
        new = masters.rotate_media_key(self.admin, self.media.media_id, grace_seconds=3600).key
        self.assertEqual(self.hit("post", f"{BASE}/decisions", key=new).status_code, 429)  # 새 키로 한도를 우회할 수 없다

    def case_unauthenticated_and_forbidden_requests_consume_no_tokens(self):
        for _ in range(20):
            self.assertEqual(self.hit("post", f"{BASE}/decisions", key="nope").status_code, 401)
        masters.set_media_active(self.admin, self.media.media_id, False)
        for _ in range(20):
            self.assertEqual(self.hit("post", f"{BASE}/decisions").status_code, 403)
        masters.set_media_active(self.admin, self.media.media_id, True)
        self.assertEqual([self.hit("post", f"{BASE}/decisions").status_code for _ in range(3)], [200, 200, 200])  # 버스트가 그대로 남아 있다

    def case_throttle_runs_after_authentication_but_before_input_validation(self):
        [self.hit("post", f"{BASE}/decisions") for _ in range(3)]
        broken = self.hit("post", f"{BASE}/decisions", body="{not json")
        self.assertEqual(broken.status_code, 429)  # 한도를 넘으면 본문을 읽기 전에 거절
        self.assertEqual(self.hit("post", f"{BASE}/decisions", key="nope", body="{not json").status_code, 401)

    def case_default_limits_match_the_contract_numbers(self):
        text = Contract("serving").spec["info"]["description"]
        from config.settings import base

        for group, (rate, burst) in base.MEDIA_RATE_LIMITS.items():
            self.assertIn(str(rate), text, group)
            self.assertIn(str(burst), text, group)
        self.assertEqual(base.MEDIA_RATE_LIMITS, {"decisions": (150, 300), "reactions": (450, 600), "reads": (150, 300)})

    def test_rate_limit(self):
        self.run_cases()
