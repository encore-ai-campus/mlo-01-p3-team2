"""게임 요청부터 실제 노출 서비스까지 검사하고 DB·HTTP 경계만 대체한다."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.test import RequestFactory, SimpleTestCase
from django.urls import Resolver404, resolve, reverse

from ad_bridge.game.views import report_impression
from ad_bridge.api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from test.support.impression_fakes import (
    DECISION_ID, SUBJECT_ID, REACTION_ID, PRIVATE_KEY,
    MemoryImpressionStore, received_reaction,
)


SUBJECT_SECRET = "unit-test-subject-secret"
AD_SUBJECT_ID = "d8d3d672-5458-ddcc-c90c-a7844b3aa51a"


class GameImpressionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.path = reverse("ad_bridge:impression", kwargs={"decision_id": DECISION_ID})
        self.store = MemoryImpressionStore(owner=SUBJECT_ID, subject=AD_SUBJECT_ID)
        self.client = Mock()
        self.client.report_impression.side_effect = received_reaction
        self.config = SimpleNamespace(media_key=PRIVATE_KEY, subject_secret=SUBJECT_SECRET)
        self.now = datetime(2026, 10, 11, 21, 0, 0, 123456, tzinfo=timezone(timedelta(hours=9)))
        patches = (
            patch("ad_bridge.game.views.AdsConfig.from_env", return_value=self.config),
            patch("ad_bridge.game.views.AdsClient", return_value=self.client),
            patch("ad_bridge.game.views.timezone.now", return_value=self.now),
            patch("ad_bridge.game.views.impression_store.reserve_impression",
                  side_effect=self.store.reserve_impression),
            patch("ad_bridge.game.views.impression_store.finish_impression",
                  side_effect=self.store.finish_impression),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def request(self, body=None):
        request = self.factory.post(
            self.path, data=json.dumps(body or {}), content_type="application/json"
        )
        request.user = SimpleNamespace(
            is_authenticated=True,
            campus_profile=SimpleNamespace(user_uuid=UUID(SUBJECT_ID)),
        )
        return request

    def report(self, request=None, decision_id=DECISION_ID):
        return report_impression(request or self.request(), decision_id=UUID(decision_id))

    def test_server_identity_time_and_reaction_ignore_browser_forgery(self):
        request = self.request({
            "subject_id": "another-user", "reaction_id": "another-reaction",
            "occurred_at": "2000-01-01T00:00:00Z", "decision_id": "another-decision",
        })
        response = self.report(request)
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        self.client.report_impression.assert_called_once_with(
            decision_id=DECISION_ID, reaction_id=REACTION_ID, subject_id=AD_SUBJECT_ID,
            occurred_at="2026-10-11T12:00:00.123456Z",
        )
        self.assertEqual(payload["reaction_id"], REACTION_ID)
        self.assertNotIn("status", payload)
        self.assertNotIn("reason_code", payload)
        self.assertEqual(payload["delivery_state"], "ACKNOWLEDGED")
        self.assertFalse(payload["duplicate"])
        self.assertNotIn("subject_id", payload)
        self.assertNotIn(PRIVATE_KEY, response.content.decode())
        self.assertNotIn(SUBJECT_SECRET, response.content.decode())
        self.assertNotIn(SUBJECT_ID, response.content.decode())
        self.assertIn("no-store", response["Cache-Control"])

    def test_duplicate_returns_existing_receipt_without_second_http(self):
        first = self.report()
        with patch("ad_bridge.game.views.timezone.now", return_value=self.now + timedelta(minutes=1)):
            second = self.report()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        first_payload, second_payload = json.loads(first.content), json.loads(second.content)
        self.assertTrue(second_payload["duplicate"])
        for name in ("decision_id", "reaction_id", "occurred_at", "delivery_state"):
            self.assertEqual(first_payload[name], second_payload[name])
        self.client.report_impression.assert_called_once()

    def test_report_and_duplicate_hide_judgment_but_keep_it_in_storage(self):
        # 첫 응답과 중복 응답 모두 판정별로 공개 내용이 달라지지 않아야 한다.
        public_payloads = []
        for status, reason in (("RECEIVED", None), ("ACCEPTED", None), ("REJECTED", "private-reason")):
            with self.subTest(status=status):
                self.store.record = None
                self.client.report_impression.side_effect = lambda **payload: replace(
                    received_reaction(**payload), status=status, reason_code=reason,
                )
                first, duplicate = self.report(), self.report()
                self.assertEqual(first.status_code, 201)
                self.assertEqual(duplicate.status_code, 200)
                for response in (first, duplicate):
                    payload = json.loads(response.content)
                    self.assertEqual(set(payload), {
                        "decision_id", "reaction_id", "occurred_at", "delivery_state",
                        "request_id", "duplicate",
                    })
                    self.assertNotIn(status, response.content.decode())
                    self.assertNotIn("private-reason", response.content.decode())
                public_payloads.append((first.content, duplicate.content))
                self.assertEqual(self.store.record.status, status)
                self.assertEqual(self.store.record.reason_code, reason)
        self.assertTrue(all(payloads == public_payloads[0] for payloads in public_payloads))

    def test_secret_rotation_keeps_the_decision_subject(self):
        # 발급 뒤 비밀을 바꿔도 노출에는 저장소의 발급 당시 가명이 사용되어야 한다.
        self.config.subject_secret = "rotated-subject-secret"
        response = self.report()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.report_impression.call_args.kwargs["subject_id"], AD_SUBJECT_ID)
        self.assertEqual(self.store.owner, SUBJECT_ID)
        self.assertNotIn(SUBJECT_ID, response.content.decode())

    def test_anonymous_request_requires_login_without_sending(self):
        request = self.request()
        request.user = SimpleNamespace(is_authenticated=False)
        response = self.report(request)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/?next="))
        self.assertIsNone(self.store.record)
        self.client.report_impression.assert_not_called()

    def test_get_is_rejected_without_sending(self):
        request = self.factory.get(self.path)
        request.user = self.request().user
        self.assertEqual(self.report(request).status_code, 405)
        self.assertIsNone(self.store.record)
        self.client.report_impression.assert_not_called()

    def test_csrf_middleware_rejects_missing_token_and_accepts_matching_token(self):
        # RequestFactory가 생략하는 실제 CSRF 미들웨어 경계를 명시적으로 검사한다.
        middleware = CsrfViewMiddleware(lambda request: HttpResponse())
        missing = self.request()
        middleware.process_request(missing)
        denied = middleware.process_view(missing, report_impression, (), {"decision_id": UUID(DECISION_ID)})
        self.assertEqual(denied.status_code, 403)
        self.client.report_impression.assert_not_called()
        valid = self.request()
        valid.META["HTTP_X_CSRFTOKEN"] = get_token(valid)
        valid.COOKIES[settings.CSRF_COOKIE_NAME] = valid.META["CSRF_COOKIE"]
        middleware.process_request(valid)
        self.assertIsNone(middleware.process_view(valid, report_impression, (), {"decision_id": UUID(DECISION_ID)}))
        self.assertEqual(self.report(valid).status_code, 201)

    def test_foreign_or_unknown_decision_is_404_without_sending(self):
        foreign = self.request()
        foreign.user.campus_profile.user_uuid = UUID("99887766-1234-4234-8234-123456789abc")
        for request, decision_id in (
            (foreign, DECISION_ID),
            (self.request(), "55667788-1234-4234-8234-123456789abc"),
        ):
            with self.subTest(decision_id=decision_id):
                response = self.report(request, decision_id)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(json.loads(response.content)["error"], "decision_not_found")
        self.assertIsNone(self.store.record)
        self.client.report_impression.assert_not_called()

    def test_decision_without_ad_is_409_without_sending(self):
        self.store.has_ad = False
        response = self.report()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)["error"], "no_ad_to_report")
        self.assertIsNone(self.store.record)
        self.client.report_impression.assert_not_called()

    def test_storage_app_missing_returns_503_without_sending(self):
        with patch("ad_bridge.game.views.apps.is_installed", return_value=False):
            response = self.report()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["error"], "ads_storage_not_configured")
        self.client.report_impression.assert_not_called()

    def test_missing_profile_uuid_returns_409_without_sending(self):
        request = self.request()
        request.user.campus_profile = None
        response = self.report(request)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)["error"], "profile_uuid_missing")
        self.client.report_impression.assert_not_called()

    def test_invalid_profile_uuid_returns_503_without_sending(self):
        request = self.request()
        request.user.campus_profile.user_uuid = "nickname-is-not-a-uuid"
        response = self.report(request)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["error"], "ads_invalid_config")
        self.assertNotIn("nickname-is-not-a-uuid", response.content.decode())
        self.client.report_impression.assert_not_called()

    def test_http_failure_returns_state_and_retry_metadata_without_resending(self):
        self.client.report_impression.side_effect = AdsHTTPError(429, request_id="rate-request", retry_after=8)
        first = self.report()
        duplicate = self.report()
        self.assertEqual(first.status_code, 502)
        payload = json.loads(first.content)
        self.assertEqual(payload["delivery_state"], "UNCONFIRMED")
        self.assertEqual(payload["upstream_status"], 429)
        self.assertEqual(payload["retry_after"], 8)
        self.assertEqual(payload["request_id"], "rate-request")
        self.assertEqual(duplicate.status_code, 202)
        self.assertTrue(json.loads(duplicate.content)["duplicate"])
        self.client.report_impression.assert_called_once()

    def test_blocked_http_failure_remains_502_on_duplicate(self):
        self.client.report_impression.side_effect = AdsHTTPError(409)
        first = self.report()
        duplicate = self.report()
        self.assertEqual(first.status_code, 502)
        self.assertEqual(duplicate.status_code, 502)
        self.assertEqual(json.loads(duplicate.content)["delivery_state"], "BLOCKED")
        self.client.report_impression.assert_called_once()

    def test_transport_failure_is_unconfirmed_and_does_not_expose_error_text(self):
        self.client.report_impression.side_effect = AdsTransportError(PRIVATE_KEY)
        response = self.report()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(json.loads(response.content)["delivery_state"], "UNCONFIRMED")
        self.assertNotIn(PRIVATE_KEY, response.content.decode())
        self.assertNotIn(SUBJECT_SECRET, response.content.decode())

    def test_acknowledged_invalid_body_returns_202_without_claiming_acceptance(self):
        self.client.report_impression.side_effect = AdsResponseError(PRIVATE_KEY, acknowledged=True)
        response = self.report()
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload["delivery_state"], "ACKNOWLEDGED")
        self.assertNotIn("status", payload)
        self.assertNotIn("reason_code", payload)
        self.assertEqual(payload["error"], "ads_invalid_response")
        self.assertNotIn(PRIVATE_KEY, response.content.decode())
        self.assertNotIn(SUBJECT_SECRET, response.content.decode())

    def test_reservation_database_failure_is_503_before_http(self):
        self.store.reserve_error = DatabaseError(PRIVATE_KEY)
        response = self.report()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["error"], "ads_storage_unavailable")
        self.assertNotIn(PRIVATE_KEY, response.content.decode())
        self.assertNotIn(SUBJECT_SECRET, response.content.decode())
        self.client.report_impression.assert_not_called()

    def test_database_failure_after_receipt_preserves_uncertainty_and_reservation(self):
        self.store.finish_error = DatabaseError(PRIVATE_KEY)
        response = self.report()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["error"], "ads_storage_unavailable")
        self.assertIn("접수 여부는 확정할 수 없습니다", json.loads(response.content)["message"])
        self.assertNotIn(PRIVATE_KEY, response.content.decode())
        self.assertNotIn(SUBJECT_SECRET, response.content.decode())
        self.assertEqual(self.store.record.delivery_state, "SENDING")
        self.store.finish_error = None
        duplicate = self.report()
        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(json.loads(duplicate.content)["reaction_id"], REACTION_ID)
        self.client.report_impression.assert_called_once()

    def test_route_accepts_uuid_and_rejects_malformed_decision_path(self):
        match = resolve(self.path)
        self.assertIs(match.func, report_impression)
        self.assertEqual(match.kwargs["decision_id"], UUID(DECISION_ID))
        with self.assertRaises(Resolver404):
            resolve(self.path.replace(DECISION_ID, "not-a-uuid"))

