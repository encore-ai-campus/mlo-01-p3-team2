"""외부 서버 없이 요청 형식·오류·키 보호·계약 응답 처리를 확인한다."""

import copy
import io
import json
import unittest
from email.message import Message
from http.client import IncompleteRead
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from uuid import UUID

from ad_bridge import AdsClient, AdsConfig, AdsHTTPError, AdsResponseError, AdsTransportError

SLOT = "5b1c9a52-6c1e-4d0b-9a1e-0b6b2f6d8f10"
SUBJECT = "0f8b2c1d-3e44-4a55-8f66-7a77b88c99d0"
REQUEST_ID = "3b1c9a52-6c1e-4d0b-9a1e-0b6b2f6d8f11"
BODY = {
    "decision_id": "7d3e5f60-1a2b-4c3d-8e4f-5a6b7c8d9e0f", "slot_id": SLOT,
    "slot_name": "테스트 배너", "audience": "individual", "decided_at": "2026-10-11T10:00:00.123Z",
    "ad": {"creative_id": "1d3e5f60-1a2b-4c3d-8e4f-5a6b7c8d9e0f", "title": "광고 제목",
           "image_url": "http://localhost:8001/assets/test.png", "redirect_url": "https://example.com",
           "click_url": "http://localhost:8001/c/token"},
}


def headers(content_type="application/json", **extra):
    result = Message()
    result["Content-Type"] = content_type
    result["X-Request-ID"] = REQUEST_ID
    for name, value in extra.items():
        result[name] = value
    return result


def response(body=None, status=201, content_type="application/json"):
    result = io.BytesIO(json.dumps(BODY if body is None else body).encode("utf-8"))
    result.status = status
    result.headers = headers(content_type)
    return result


class DecisionClientTests(unittest.TestCase):
    def setUp(self):
        self.config = AdsConfig("http://localhost:8001/api/media/v1/", "unit-test-secret", 5)
        self.opener = Mock()
        with patch("ad_bridge.api.client.build_opener", return_value=self.opener):
            self.client = AdsClient(self.config)
        self.opener.open.return_value = response()

    def test_personal_request_uses_config_and_only_pseudonymous_ids(self):
        result = self.client.create_decision(UUID(SLOT), SUBJECT.upper())
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:8001/api/media/v1/decisions")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("X-media-key"), self.config.media_key)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(self.opener.open.call_args.kwargs, {"timeout": 5.0})
        self.assertEqual(json.loads(request.data), {"slot_id": SLOT, "subject_id": SUBJECT})
        self.assertEqual(result.request_id, REQUEST_ID)
        self.assertEqual(result.ad.title, "광고 제목")
        self.assertNotIn(self.config.media_key, repr(result))
        self.assertNotIn(self.config.media_key, repr(self.config))

    def test_no_ad_and_new_fields_are_supported(self):
        body = {**BODY, "ad": None, "future_field": {"value": 1}}
        self.opener.open.return_value = response(body)
        result = self.client.create_decision(SLOT, SUBJECT)
        self.assertIsNone(result.ad)
        self.assertEqual(result.decision_id, BODY["decision_id"])
        body = copy.deepcopy(BODY)
        body["ad"]["future_field"] = True
        self.opener.open.return_value = response(body)
        self.assertEqual(self.client.create_decision(SLOT, SUBJECT).ad.title, "광고 제목")

    def test_shared_omits_subject_and_keeps_click_template(self):
        body = copy.deepcopy(BODY)
        body["audience"] = "shared"
        body["ad"]["click_url"] += "?s={subject_id}"
        self.opener.open.return_value = response(body)
        result = self.client.create_decision(SLOT)
        self.assertEqual(json.loads(self.opener.open.call_args.args[0].data), {"slot_id": SLOT})
        self.assertIn("{subject_id}", result.ad.click_url)

    def test_bad_input_is_rejected_before_network_access(self):
        for slot, subject in [("banner", SUBJECT), (SLOT, "nickname"), (SLOT.replace("-", ""), SUBJECT), (SLOT, "")]:
            with self.subTest(slot=slot, subject=subject), self.assertRaises(ValueError):
                self.client.create_decision(slot, subject)
        self.opener.open.assert_not_called()

    def test_http_failures_are_exposed_without_retry(self):
        for status, code in [(400, "invalid_request"), (401, "unauthorized"), (403, "forbidden"),
                             (404, "not_found"), (429, "rate_limited"), (503, "unavailable")]:
            with self.subTest(status=status):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = HTTPError("http://localhost", status, "failure",
                    headers("application/problem+json", **{"Retry-After": "3"}), io.BytesIO(json.dumps({"code": code}).encode()))
                with self.assertRaises(AdsHTTPError) as caught:
                    self.client.create_decision(SLOT, SUBJECT)
                self.assertEqual((caught.exception.status, caught.exception.code), (status, code))
                self.assertEqual(caught.exception.request_id, REQUEST_ID)
                self.assertEqual(caught.exception.retry_after, 3)
                self.opener.open.assert_called_once()

    def test_non_json_http_failure_keeps_status_and_redacts_metadata(self):
        hdr = headers(**{"Retry-After": "invalid"})
        hdr.replace_header("X-Request-ID", self.config.media_key)
        self.opener.open.side_effect = HTTPError("http://localhost", 502, "bad gateway", hdr, io.BytesIO(b"<html>error</html>"))
        with self.assertRaises(AdsHTTPError) as caught:
            self.client.create_decision(SLOT, SUBJECT)
        self.assertEqual(caught.exception.status, 502)
        self.assertIsNone(caught.exception.code)
        self.assertIsNone(caught.exception.retry_after)
        self.assertNotIn(self.config.media_key, str(vars(caught.exception)))

    def test_timeout_connection_and_truncated_response_do_not_retry(self):
        for error in [TimeoutError("secret details"), URLError("secret details"), IncompleteRead(b"partial")]:
            with self.subTest(error=type(error).__name__):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = error
                with self.assertRaises(AdsTransportError) as caught:
                    self.client.create_decision(SLOT, SUBJECT)
                self.assertNotIn("secret details", str(caught.exception))
                self.opener.open.assert_called_once()

    def test_invalid_success_status_or_content_type_is_not_no_ad(self):
        for status, content_type in [(200, "application/json"), (204, "application/json"), (201, "text/html")]:
            self.opener.open.return_value = response(status=status, content_type=content_type)
            with self.subTest(status=status, content_type=content_type), self.assertRaises(AdsResponseError):
                self.client.create_decision(SLOT, SUBJECT)

    def test_missing_wrong_or_mismatched_required_fields(self):
        cases = [[], {}, {**BODY, "slot_id": SUBJECT}, {**BODY, "audience": "shared"},
                 {**BODY, "ad": []}, {**BODY, "decided_at": "2026-99-11T10:00:00Z"},
                 {**BODY, "decided_at": "2026-10-11T10:00:00+09:00"}]
        for field in BODY:
            body = copy.deepcopy(BODY)
            del body[field]
            cases.append(body)
        for field in BODY["ad"]:
            body = copy.deepcopy(BODY)
            del body["ad"][field]
            cases.append(body)
        for body in cases:
            self.opener.open.return_value = response(body)
            with self.subTest(body=body), self.assertRaises(AdsResponseError) as caught:
                self.client.create_decision(SLOT, SUBJECT)
            self.assertEqual(caught.exception.request_id, REQUEST_ID)

    def test_invalid_json_oversized_response_and_unsafe_urls_are_rejected(self):
        for raw in [b"{", b"\xff", b"x" * (1024 * 1024 + 1)]:
            result = response()
            result.seek(0)
            result.truncate()
            result.write(raw)
            result.seek(0)
            self.opener.open.return_value = result
            with self.assertRaises(AdsResponseError):
                self.client.create_decision(SLOT, SUBJECT)
        for field, url in [("click_url", "javascript:alert(1)"), ("image_url", "file:///tmp/ad"),
                           ("redirect_url", "http://example.com")]:
            body = copy.deepcopy(BODY)
            body["ad"][field] = url
            self.opener.open.return_value = response(body)
            with self.assertRaises(AdsResponseError):
                self.client.create_decision(SLOT, SUBJECT)


if __name__ == "__main__":
    unittest.main()
