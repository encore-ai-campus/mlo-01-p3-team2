"""GET 계약은 가짜 HTTP 응답으로 검사한다."""
import io
import json
import unittest
from email.message import Message
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from ad_bridge import AdsClient, AdsConfig, AdsHTTPError, AdsResponseError, AdsTransportError
from test.support.impression_fakes import DECISION_ID, REACTION_ID, SUBJECT_ID, OCCURRED_AT


class ResultClientTests(unittest.TestCase):
    def setUp(self):
        self.client = AdsClient(AdsConfig("http://localhost:8001/api/media/v1", "test-key", 5))
        self.client._opener = Mock()
        self.body = dict(decision_id=DECISION_ID, reaction_id=REACTION_ID, subject_id=SUBJECT_ID,
                         type="IMPRESSION", occurred_at=OCCURRED_AT, received_at=OCCURRED_AT,
                         status="RECEIVED", reason_code=None)

    def response(self, *, status=200, raw=None, content_type="application/json"):
        response = io.BytesIO(json.dumps(self.body).encode() if raw is None else raw)
        response.status = status
        response.headers = Message()
        response.headers["Content-Type"] = content_type
        self.client._opener.open.return_value = response

    def lookup(self):
        return self.client.get_reaction(decision_id=DECISION_ID, reaction_id=REACTION_ID)

    def test_request(self):
        self.response()
        self.assertEqual(self.lookup().status, "RECEIVED")
        request = self.client._opener.open.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.full_url, f"http://localhost:8001/api/media/v1/decisions/{DECISION_ID}/reactions/{REACTION_ID}")
        self.assertEqual(request.get_header("X-media-key"), "test-key")
        self.assertEqual(self.client._opener.open.call_args.kwargs, {"timeout": 5.0})
        self.client._opener.open.assert_called_once()

    def test_states(self):
        for state in ("RECEIVED", "ACCEPTED", "REJECTED"):
            with self.subTest(state=state):
                self.body.update(status=state, reason_code="future_reason", extra="ignored")
                self.response()
                result = self.lookup()
                self.assertEqual(result.status, state)
                self.assertEqual(result.reason_code, "future_reason")

    def test_uuid(self):
        with self.assertRaises(ValueError):
            self.client.get_reaction(decision_id="invalid", reaction_id=REACTION_ID)
        self.client._opener.open.assert_not_called()

    def test_schema(self):
        original = self.body.copy()
        variants = [{k: v for k, v in original.items() if k != field} for field in original]
        variants += [original | {field: value} for field, value in (
            ("decision_id", SUBJECT_ID), ("reaction_id", SUBJECT_ID), ("type", "CLICK"),
            ("status", "UNKNOWN"), ("occurred_at", "bad"), ("subject_id", "bad"), ("reason_code", 3))]
        for body in variants:
            with self.subTest(body=body):
                self.body = body
                self.response()
                with self.assertRaises(AdsResponseError) as caught:
                    self.lookup()
                self.assertFalse(caught.exception.acknowledged)

    def test_response(self):
        for options in ({"status": 201}, {"raw": b"bad"}, {"raw": b"x" * (1024*1024+1)},
                        {"content_type": "text/html"}):
            with self.subTest(options=list(options)):
                self.response(**options)
                with self.assertRaises(AdsResponseError) as caught:
                    self.lookup()
                self.assertFalse(caught.exception.acknowledged)

    def test_http_error(self):
        for status in (301, 401, 403, 404, 429, 503):
            with self.subTest(status=status):
                headers = Message()
                headers["Retry-After"] = "7"
                self.client._opener.open.reset_mock()
                self.client._opener.open.side_effect = HTTPError("http://ads.test", status, "error", headers, io.BytesIO(b"{}"))
                with self.assertRaises(AdsHTTPError) as caught:
                    self.lookup()
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.retry_after, 7)
                self.client._opener.open.assert_called_once()

    def test_transport(self):
        self.client._opener.open.side_effect = URLError("private")
        with self.assertRaises(AdsTransportError) as caught:
            self.lookup()
        self.assertNotIn("private", str(caught.exception))
        self.client._opener.open.assert_called_once()

    def test_secret(self):
        self.body["reason_code"] = "test-key"
        self.response()
        self.assertNotIn("test-key", self.lookup().reason_code)
