"""실제 광고 서버 없이 노출 PUT 한 번의 계약·멱등 값·오류 처리를 확인한다."""

import io
import json
import unittest
from email.message import Message
from http.client import IncompleteRead
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from uuid import UUID

from ad_bridge import AdsClient, AdsConfig, AdsHTTPError, AdsResponseError, AdsTransportError, Reaction

DECISION = "7d3e5f60-1a2b-4c3d-8e4f-5a6b7c8d9e0f"
REACTION = "c0ffee00-1111-4222-8333-444455556666"
SUBJECT = "0f8b2c1d-3e44-4a55-8f66-7a77b88c99d0"
REQUEST_ID = "3b1c9a52-6c1e-4d0b-9a1e-0b6b2f6d8f11"
OCCURRED_AT = "2026-10-11T10:00:00.123Z"
BODY = {
    "reaction_id": REACTION, "decision_id": DECISION, "subject_id": None, "type": "IMPRESSION",
    "occurred_at": OCCURRED_AT, "received_at": "2026-10-11T10:00:01Z",
    "status": "RECEIVED", "reason_code": None,
}


def _headers(content_type="application/json"):
    result = Message()
    result["Content-Type"] = content_type
    result["X-Request-ID"] = REQUEST_ID
    return result


def _response(body=None, *, status=201, raw=None, content_type="application/json"):
    result = io.BytesIO(json.dumps(BODY if body is None else body).encode("utf-8") if raw is None else raw)
    result.status = status
    result.headers = _headers(content_type)
    return result


class ImpressionClientTests(unittest.TestCase):
    def setUp(self):
        self.config = AdsConfig("http://localhost:8001/api/media/v1", "unit-test-secret", 5)
        self.opener = Mock()
        with patch("ad_bridge.api.client.build_opener", return_value=self.opener) as factory:
            self.client = AdsClient(self.config)
        self.redirect_handler = factory.call_args.args[0]
        self.opener.open.return_value = _response()

    def _report(self, **changes):
        values = {"decision_id": DECISION, "reaction_id": REACTION, "occurred_at": OCCURRED_AT}
        return self.client.report_impression(**(values | changes))

    def test_first_report_puts_only_impression_and_fixed_time(self):
        result = self._report(decision_id=UUID(DECISION), reaction_id=REACTION.upper())
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url,
                         f"http://localhost:8001/api/media/v1/decisions/{DECISION}/reactions/{REACTION}")
        self.assertEqual(request.method, "PUT")
        self.assertEqual(request.get_header("X-media-key"), self.config.media_key)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(json.loads(request.data), {"type": "IMPRESSION", "occurred_at": OCCURRED_AT})
        self.assertEqual(self.opener.open.call_args.kwargs, {"timeout": 5.0})
        self.opener.open.assert_called_once()
        self.assertIsInstance(result, Reaction)
        self.assertEqual(result.reaction_id, REACTION)
        self.assertEqual(result.status, "RECEIVED")
        self.assertEqual(result.request_id, REQUEST_ID)
        self.assertIsNone(result.subject_id)

    def test_explicit_same_report_accepts_200_and_preserves_request_bytes(self):
        # 다시 보낼 때 호출자가 같은 감지 기록을 전달하면 경로와 본문이 바뀌지 않는다.
        self.opener.open.side_effect = [_response(), _response(status=200)]
        first = self._report()
        second = self._report()
        first_request, second_request = [call.args[0] for call in self.opener.open.call_args_list]
        self.assertEqual(first, second)
        self.assertEqual(first_request.full_url, second_request.full_url)
        self.assertEqual(first_request.data, second_request.data)
        self.assertEqual(self.opener.open.call_count, 2)

    def test_subject_is_normalized_and_sent_when_supplied(self):
        self.opener.open.return_value = _response(BODY | {"subject_id": SUBJECT})
        result = self._report(subject_id=SUBJECT.upper())
        self.assertEqual(result.subject_id, SUBJECT)
        self.assertEqual(json.loads(self.opener.open.call_args.args[0].data),
                         {"type": "IMPRESSION", "occurred_at": OCCURRED_AT, "subject_id": SUBJECT})

    def test_invalid_uuids_are_rejected_before_network(self):
        for field in ("decision_id", "reaction_id", "subject_id"):
            for value in ("", "../reactions/other", REACTION.replace("-", ""), 123, True):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self._report(**{field: value})
        self.opener.open.assert_not_called()

    def test_invalid_utc_times_are_rejected_before_network(self):
        for value in (None, 123, "2026-10-11", "2026-10-11T10:00:00", "2026-10-11T10:00:00+00:00",
                      "2026-02-30T10:00:00Z", "2026-10-11T25:00:00Z", "2026-10-11T10:00:00.1234567Z"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self._report(occurred_at=value)
        self.opener.open.assert_not_called()

    def test_same_time_with_different_fraction_precision_is_accepted(self):
        self.opener.open.return_value = _response(BODY | {"occurred_at": "2026-10-11T10:00:00.123000Z"})
        self.assertEqual(self._report().occurred_at, "2026-10-11T10:00:00.123000Z")
        # 응답 표기를 따라 요청 본문을 변경하지 않는다.
        self.assertEqual(json.loads(self.opener.open.call_args.args[0].data)["occurred_at"], OCCURRED_AT)

    def test_known_states_new_fields_and_unknown_reason_are_accepted(self):
        for state in ("RECEIVED", "ACCEPTED", "REJECTED"):
            with self.subTest(state=state):
                reason = "future_rejection_reason" if state == "REJECTED" else None
                self.opener.open.return_value = _response(BODY | {
                    "status": state, "reason_code": reason, "new_field": {"value": 1},
                })
                result = self._report()
                self.assertEqual(result.status, state)
                self.assertEqual(result.reason_code, reason)

    def test_every_required_response_field_is_checked(self):
        for field in BODY:
            with self.subTest(field=field):
                body = {key: value for key, value in BODY.items() if key != field}
                self.opener.open.return_value = _response(body)
                with self.assertRaises(AdsResponseError) as caught:
                    self._report()
                self.assertTrue(caught.exception.acknowledged)

    def test_wrong_response_types_and_dates_are_rejected(self):
        for field, value in (("reaction_id", []), ("decision_id", "invalid"), ("subject_id", "invalid"),
                             ("type", "CLICK"), ("occurred_at", None),
                             ("received_at", "2026-02-30T10:00:00Z"), ("status", "UNKNOWN"),
                             ("reason_code", {"nested": "value"})):
            with self.subTest(field=field, value=value):
                self.opener.open.return_value = _response(BODY | {field: value})
                with self.assertRaises(AdsResponseError) as caught:
                    self._report()
                self.assertTrue(caught.exception.acknowledged)

    def test_response_ids_subject_and_time_must_match_request(self):
        for field, value in (("reaction_id", SUBJECT), ("decision_id", SUBJECT), ("subject_id", SUBJECT),
                             ("occurred_at", "2026-10-11T10:00:00.124Z")):
            with self.subTest(field=field):
                self.opener.open.return_value = _response(BODY | {field: value})
                with self.assertRaises(AdsResponseError) as caught:
                    self._report()
                self.assertTrue(caught.exception.acknowledged)
        self.opener.open.return_value = _response()
        with self.assertRaises(AdsResponseError):
            self._report(subject_id=SUBJECT)

    def test_http_failures_preserve_status_without_retry(self):
        for status in (400, 401, 403, 409, 413, 415, 429, 503):
            with self.subTest(status=status):
                self.opener.open.reset_mock()
                hdr = _headers()
                hdr["Retry-After"] = "7"
                self.opener.open.side_effect = HTTPError("http://localhost", status, "failure", hdr,
                                                        io.BytesIO(b'{"code":"test_failure"}'))
                with self.assertRaises(AdsHTTPError) as caught:
                    self._report()
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.code, "test_failure")
                self.assertEqual(caught.exception.request_id, REQUEST_ID)
                self.assertEqual(caught.exception.retry_after, 7)
                self.opener.open.assert_called_once()

    def test_transport_failure_before_acknowledgement_does_not_retry(self):
        for error in (URLError(self.config.media_key), TimeoutError(self.config.media_key),
                      IncompleteRead(b"partial")):
            with self.subTest(error=type(error).__name__):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = error
                with self.assertRaises(AdsTransportError) as caught:
                    self._report()
                self.assertNotIn(self.config.media_key, str(caught.exception))
                self.opener.open.assert_called_once()

    def test_malformed_json_after_2xx_retains_acknowledgement(self):
        for raw in (b"not-json", b"\xff", b"[]", b"null", b"{}", b"{" * 1200):
            with self.subTest(raw=raw[:20]):
                self.opener.open.reset_mock()
                self.opener.open.return_value = _response(raw=raw)
                with self.assertRaises(AdsResponseError) as caught:
                    self._report()
                self.assertTrue(caught.exception.acknowledged)
                self.assertEqual(caught.exception.request_id, REQUEST_ID)
                self.opener.open.assert_called_once()

    def test_body_read_failure_after_2xx_retains_acknowledgement(self):
        for error in (IncompleteRead(b"partial"), TimeoutError(), ConnectionResetError()):
            with self.subTest(error=type(error).__name__):
                self.opener.open.reset_mock()
                reply = _response(status=200)
                reply.read = Mock(side_effect=error)
                self.opener.open.return_value = reply
                with self.assertRaises(AdsResponseError) as caught:
                    self._report()
                self.assertTrue(caught.exception.acknowledged)
                self.assertEqual(caught.exception.request_id, REQUEST_ID)
                self.opener.open.assert_called_once()

    def test_bad_content_type_or_oversized_body_retains_acknowledgement(self):
        for reply in (_response(content_type="text/html"), _response(raw=b"x" * (1024 * 1024 + 1))):
            with self.subTest(content_type=reply.headers["Content-Type"]):
                self.opener.open.return_value = reply
                with self.assertRaises(AdsResponseError) as caught:
                    self._report()
                self.assertTrue(caught.exception.acknowledged)

    def test_unexpected_2xx_is_acknowledged_but_not_a_valid_reaction(self):
        for status in (202, 204):
            with self.subTest(status=status):
                self.opener.open.return_value = _response(status=status)
                with self.assertRaises(AdsResponseError) as caught:
                    self._report()
                self.assertTrue(caught.exception.acknowledged)
        self.assertFalse(AdsResponseError("미접수 응답 오류").acknowledged)

    def test_reflected_media_key_is_removed_from_result_and_http_metadata(self):
        reply = _response(BODY | {"status": "REJECTED", "reason_code": f"future_{self.config.media_key}"})
        reply.headers.replace_header("X-Request-ID", self.config.media_key)
        self.opener.open.return_value = reply
        result = self._report()
        self.assertEqual(result.reason_code, "future_[REDACTED]")
        self.assertNotIn(self.config.media_key, repr(result))
        hdr = _headers()
        hdr.replace_header("X-Request-ID", self.config.media_key)
        raw = json.dumps({"code": self.config.media_key, "detail": self.config.media_key}).encode()
        self.opener.open.side_effect = HTTPError("http://localhost", 409, "failure", hdr, io.BytesIO(raw))
        with self.assertRaises(AdsHTTPError) as caught:
            self._report()
        self.assertNotIn(self.config.media_key, str(vars(caught.exception)))
        self.assertNotIn(self.config.media_key, str(caught.exception))

    def test_redirect_is_blocked_without_following_or_retrying(self):
        # 다른 호스트로 키가 전달되는 urllib 자동 리다이렉트를 차단한다.
        self.assertIsNone(self.redirect_handler.redirect_request(
            None, None, 302, "redirect", _headers(), "https://other.example/"))
        self.opener.open.side_effect = HTTPError("http://localhost", 302, "redirect", _headers(), io.BytesIO())
        with self.assertRaises(AdsHTTPError) as caught:
            self._report()
        self.assertEqual(caught.exception.status, 302)
        self.opener.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
