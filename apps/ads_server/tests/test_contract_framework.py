"""계약 검사기 **자체**의 시험. 검사기가 틀린 응답을 실제로 잡는지(공회전하지 않는지) 확인한다.

특히 `format` 검사가 켜져 있어야 한다: 의존성이 빠지면 `jsonschema` 는 잘못된 UUID·시각·URI 를 조용히 통과시킨다.
"""
import json
from dataclasses import dataclass, field

from django.test import SimpleTestCase, tag

from tests.contract_support import Contract

REQUEST_ID = "11111111-2222-4333-8444-555555555555"
DECISION = {
    "decision_id": "7d3e5f60-1a2b-4c3d-8e4f-5a6b7c8d9e0f",
    "slot_id": "5b1c9a52-6c1e-4d0b-9a1e-0b6b2f6d8f10",
    "slot_name": "lobby-banner",
    "audience": "individual",
    "decided_at": "2026-10-07T03:21:45Z",
    "ad": {
        "creative_id": "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d", "title": "가을 학습 스터디 모집",
        "image_url": "https://ads.internal.example/assets/" + "a" * 64 + ".png", "redirect_url": "https://example.com/study",
    },
}


@dataclass
class Fake:
    status_code: int
    body: object = None
    headers: dict = field(default_factory=dict)

    @property
    def content(self):
        return b"" if self.body is None else (self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode())


def ok_201(**over):
    headers = {"Content-Type": "application/json", "X-Request-ID": REQUEST_ID, "Location": "/api/media/v1/decisions/" + DECISION["decision_id"]}
    headers.update(over.pop("headers", {}))
    return Fake(201, over.pop("body", DECISION), headers)


@tag("security")
class ContractCheckerTests(SimpleTestCase):
    contract = Contract("serving")

    def problems(self, response, path="/decisions", method=None):
        method = method or ("get" if path.startswith("/assets") else "post")
        return self.contract.response_problems(path, method, response)

    def test_a_conforming_response_passes(self):
        self.assertEqual(self.problems(ok_201()), [])
        no_ad = {**DECISION, "ad": None}
        self.assertEqual(self.problems(ok_201(body=no_ad)), [])

    def test_status_header_media_type_and_body_are_all_checked(self):
        cases = {
            "undocumented status": (Fake(418, None, {"X-Request-ID": REQUEST_ID}), "문서에 없는 상태 코드"),
            "wrong media type": (ok_201(headers={"Content-Type": "text/html"}), "미디어 타입"),
            "missing request id": (ok_201(headers={"X-Request-ID": None}), "X-Request-ID"),
            "missing location on 201": (ok_201(headers={"Location": None}), "Location"),
            "malformed request id": (ok_201(headers={"X-Request-ID": "not-a-uuid"}), "X-Request-ID"),
            "body not json": (ok_201(body=b"<html>"), "JSON"),
        }
        for label, (response, needle) in cases.items():
            response.headers = {k: v for k, v in response.headers.items() if v is not None}
            found = self.problems(response)
            self.assertTrue(any(needle in p for p in found), (label, found))

    def test_format_checks_are_really_enabled(self):
        """잘못된 UUID·시각·URI 가 조용히 통과하면 안 된다(format 검사 의존성이 빠진 경우를 잡는다)."""
        bad_bodies = {
            "uuid": {**DECISION, "decision_id": "7d3e5f60-1a2b-4c3d-8e4f-5a6b7c8d9e0"},
            "uuid without hyphens": {**DECISION, "slot_id": "5b1c9a526c1e4d0b9a1e0b6b2f6d8f10"},
            "date-time (no T)": {**DECISION, "decided_at": "2026-10-07 03:21:45Z"},
            "date-time (not UTC)": {**DECISION, "decided_at": "2026-10-07T12:21:45+09:00"},
            "date-time (impossible)": {**DECISION, "decided_at": "2026-13-45T25:61:61Z"},
            "uri (image_url)": {**DECISION, "ad": {**DECISION["ad"], "image_url": "not a uri"}},
            "uri (redirect_url)": {**DECISION, "ad": {**DECISION["ad"], "redirect_url": "http://[bad"}},
        }
        for label, body in bad_bodies.items():
            found = self.problems(ok_201(body=body))
            self.assertTrue(found, f"{label}: 잘못된 값이 통과했다")

    def test_structural_violations_are_caught(self):
        extra = {**DECISION, "unexpected": 1}
        missing = {k: v for k, v in DECISION.items() if k != "slot_name"}
        wrong_type = {**DECISION, "slot_name": 5}
        no_ad_key = {k: v for k, v in DECISION.items() if k != "ad"}
        no_audience = {k: v for k, v in DECISION.items() if k != "audience"}  # v1.1: 응답이 슬롯 성격을 빠뜨리면 계약 위반
        bad_audience = {**DECISION, "audience": "everyone"}
        for label, body in {"extra property": extra, "missing slot_name": missing, "wrong type": wrong_type, "missing ad": no_ad_key,
                            "missing audience": no_audience, "unknown audience": bad_audience}.items():
            self.assertTrue(self.problems(ok_201(body=body)), label)

    def test_retry_after_must_be_present_and_an_integer_on_429_and_503(self):
        problem = {"type": "/problems/rate_limited", "title": "t", "status": 429, "code": "rate_limited", "request_id": REQUEST_ID}
        good = Fake(429, problem, {"Content-Type": "application/problem+json", "X-Request-ID": REQUEST_ID, "Retry-After": "2"})
        self.assertEqual(self.problems(good), [])
        for header in (None, "soon", "-1", "1.5"):
            headers = {"Content-Type": "application/problem+json", "X-Request-ID": REQUEST_ID}
            if header is not None:
                headers["Retry-After"] = header
            self.assertTrue(self.problems(Fake(429, problem, headers)), header)

    def test_binary_and_empty_responses(self):
        image = Fake(200, b"\x89PNG\r\n", {
            "Content-Type": "image/png", "ETag": "abc", "Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "cross-origin",
        })
        self.assertEqual(self.problems(image, "/assets/{asset_name}"), [])
        self.assertTrue(self.problems(Fake(200, None, image.headers), "/assets/{asset_name}"))  # 본문 없음
        wrong_cache = Fake(200, b"x", {**image.headers, "Cache-Control": "max-age=3600"})
        self.assertTrue(self.problems(wrong_cache, "/assets/{asset_name}"))  # const: no-cache
        self.assertEqual(self.problems(Fake(304, None, {"ETag": "abc", "Cache-Control": "no-cache"}), "/assets/{asset_name}"), [])
        self.assertTrue(self.problems(Fake(304, None, {}), "/assets/{asset_name}"))  # 304 에도 ETag·Cache-Control

    def test_problem_status_must_match_the_http_status(self):
        """RFC 9457 §3.1.2: 본문 status 가 HTTP 상태와 다르면 클라이언트와 로그가 서로 다른 오류로 읽는다."""
        def problem(status, body_status):
            body = {"type": f"/problems/x", "title": "t", "status": body_status, "code": "unavailable", "request_id": REQUEST_ID}
            headers = {"Content-Type": "application/problem+json", "X-Request-ID": REQUEST_ID, "Retry-After": "1"}
            return Fake(status, body, headers)

        self.assertEqual(self.problems(problem(503, 503)), [])
        for http, body in ((503, 400), (429, 200)):
            found = self.problems(problem(http, body))
            self.assertTrue(any("status" in f and "다르다" in f for f in found), (http, body, found))

    def test_401_must_carry_a_media_key_challenge(self):
        def unauthorized(challenge):
            headers = {"Content-Type": "application/problem+json", "X-Request-ID": REQUEST_ID}
            if challenge is not None:
                headers["WWW-Authenticate"] = challenge
            body = {"type": "/problems/unauthorized", "title": "t", "status": 401, "code": "unauthorized", "request_id": REQUEST_ID}
            return Fake(401, body, headers)

        self.assertEqual(self.problems(unauthorized('MediaKey realm="ads-media-api"')), [])  # 정상 값
        for label, challenge in {"missing": None, "empty": "", "wrong scheme": 'Basic realm="x"', "no realm": "MediaKey", "bare": "ads-media-api"}.items():
            found = self.problems(unauthorized(challenge))
            self.assertTrue(found, label)
            self.assertTrue(any("WWW-Authenticate" in f for f in found), (label, found))

    def test_statuses_that_forbid_a_body_are_checked(self):
        self.assertEqual(self.problems(Fake(304, None, {"ETag": "abc", "Cache-Control": "no-cache"}), "/assets/{asset_name}"), [])
        found = self.problems(Fake(304, b"unexpected body", {"ETag": "abc", "Cache-Control": "no-cache"}), "/assets/{asset_name}")
        self.assertTrue(any("본문이 없어야" in f for f in found), found)

    def test_retry_after_accepts_only_ascii_digits(self):
        problem = {"type": "/problems/rate_limited", "title": "t", "status": 429, "code": "rate_limited", "request_id": REQUEST_ID}
        for value in ("٣", "３", "²", "1_0"):  # 아라비아-인도·전각·위첨자 숫자, 밑줄
            headers = {"Content-Type": "application/problem+json", "X-Request-ID": REQUEST_ID, "Retry-After": value}
            self.assertTrue(self.problems(Fake(429, problem, headers)), value)

    def test_named_schema_helper_rejects_bad_values(self):
        self.assertEqual(self.contract.named_schema_errors("Uuid", "7d3e5f60-1a2b-4c3d-8e4f-5a6b7c8d9e0f"), [])
        for bad in ("x", 5, None, "7d3e5f60-1a2b-4c3d-8e4f-5a6b7c8d9e0"):
            self.assertTrue(self.contract.named_schema_errors("Uuid", bad), bad)
        self.assertEqual(self.contract.named_schema_errors("DateTimeUtc", "2026-10-07T03:21:45Z"), [])
        self.assertTrue(self.contract.named_schema_errors("DateTimeUtc", "2026-10-07T03:21:45+09:00"))
