"""DB나 광고 서버 없이 실제 Django 요청 경계와 브리지 호출을 검사한다."""

import json
import os
import io
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from ad_bridge import AdsConfig
from ad_bridge.game.views import request_decision, report_impression, reaction_result, _subject_id, _owner_id
from ad_bridge.api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from ad_bridge.api.types import Ad, Decision


SLOT_ID = "aabbccdd-1234-4234-8234-123456789abc"
SUBJECT_ID = UUID("11223344-1234-4234-8234-123456789abc")
DECISION_ID = "22334455-1234-4234-8234-123456789abc"
MEDIA_KEY = "server-only-media-key"
SUBJECT_SECRET = "unit-test-subject-secret"
AD_SUBJECT_ID = UUID("d8d3d672-5458-ddcc-c90c-a7844b3aa51a")


@override_settings(ADS_SLOT_ID=SLOT_ID)
class GameAdapterTests(SimpleTestCase):
    def setUp(self):
        # DB는 저장소 전용 검사에서 확인한다. 여기서는 사용자/결정 전달 경계를 검증한다.
        storage_patch = patch("ad_bridge.game.views.decision_store.remember_decision")
        self.remember_decision = storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.config = AdsConfig("http://ads.test/api/media/v1", MEDIA_KEY, 5, subject_secret=SUBJECT_SECRET)
        environment = patch.dict(os.environ, {
            "ADS_API_BASE_URL": self.config.base_url, "ADS_MEDIA_KEY": MEDIA_KEY,
            "ADS_API_TIMEOUT": "5", "ADS_SUBJECT_SECRET": SUBJECT_SECRET,
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.factory = RequestFactory()
        self.path = reverse("ad_bridge:decision")
        self.ad = Ad(
            creative_id="33445566-1234-4234-8234-123456789abc",
            title="게임 테스트 광고",
            image_url="http://ads.test/assets/test.png",
            redirect_url="https://example.com/landing",
            click_url="http://ads.test/c/signed-token",
        )
        self.decision = Decision(
            decision_id=DECISION_ID,
            slot_id=SLOT_ID,
            slot_name="테스트 슬롯",
            audience="individual",
            decided_at="2026-10-11T12:00:00Z",
            ad=self.ad,
            request_id="request-test-1",
        )

    def request(self, body=None):
        request = self.factory.post(
            self.path, data=json.dumps(body or {}), content_type="application/json"
        )
        request.user = SimpleNamespace(
            is_authenticated=True,
            campus_profile=SimpleNamespace(user_uuid=SUBJECT_ID),
        )
        return request

    def test_success_uses_server_identity_and_returns_only_public_fields(self):
        # 브라우저가 슬롯·사용자를 바꿔 보내도 서버 설정과 로그인 프로필만 사용한다.
        request = self.request({"slot_id": "forged-slot", "subject_id": "forged-user"})
        config = self.config
        with patch("ad_bridge.game.views.AdsConfig.from_env", return_value=self.config) as config_class, patch(
            "ad_bridge.game.views.AdsClient"
        ) as client_class:
            config_class.return_value = config
            client_class.return_value.create_decision.return_value = self.decision
            self.assertEqual(self.path, "/api/ads/decision/")
            self.assertIs(resolve(self.path).func, request_decision)
            response = request_decision(request)
            config_class.assert_called_once_with()
            client_class.assert_called_once_with(config)
            client_class.return_value.create_decision.assert_called_once_with(
                slot_id=SLOT_ID, subject_id=AD_SUBJECT_ID
            )
        self.assertEqual(response.status_code, 201)
        self.remember_decision.assert_called_once_with(self.decision, AD_SUBJECT_ID, owner_id=SUBJECT_ID)
        payload = json.loads(response.content)
        self.assertEqual(payload, {
            "decision_id": DECISION_ID,
            "slot_id": SLOT_ID,
            "audience": "individual",
            "decided_at": "2026-10-11T12:00:00Z",
            "request_id": "request-test-1",
            "ad": {
                "creative_id": self.ad.creative_id,
                "title": self.ad.title,
                "image_url": self.ad.image_url,
                "click_url": self.ad.click_url,
            },
        })
        for private_value in (MEDIA_KEY, str(SUBJECT_ID), self.ad.redirect_url):
            self.assertNotIn(private_value, response.content.decode())
        self.assertIn("no-store", response["Cache-Control"])

    def test_no_ad_is_a_successful_decision(self):
        with patch("ad_bridge.game.views.AdsConfig.from_env", return_value=self.config), patch(
            "ad_bridge.game.views.AdsClient"
        ) as client_class:
            client_class.return_value.create_decision.return_value = Decision(
                decision_id=DECISION_ID, slot_id=SLOT_ID, slot_name="테스트 슬롯",
                audience="individual", decided_at="2026-10-11T12:00:00Z",
                ad=None, request_id=None,
            )
            response = request_decision(self.request())
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(json.loads(response.content)["ad"])

    def test_decision_storage_failure_does_not_return_an_untracked_ad(self):
        self.remember_decision.side_effect = DatabaseError("private database detail")
        with patch("ad_bridge.game.views.AdsConfig.from_env", return_value=self.config), patch(
            "ad_bridge.game.views.AdsClient"
        ) as client_class:
            client_class.return_value.create_decision.return_value = self.decision
            response = request_decision(self.request())
            client_class.return_value.create_decision.assert_called_once()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["error"], "ads_storage_unavailable")
        self.assertNotIn("ad", json.loads(response.content))
        self.assertNotIn("private database detail", response.content.decode())

    def test_authentication_and_post_are_required_before_upstream_call(self):
        with patch("ad_bridge.game.views.AdsClient") as client_class:
            anonymous = self.request()
            anonymous.user = SimpleNamespace(is_authenticated=False)
            response = request_decision(anonymous)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith("/login/?next="))

            get_request = self.factory.get(self.path)
            get_request.user = self.request().user
            self.assertEqual(request_decision(get_request).status_code, 405)
            client_class.assert_not_called()

    def test_csrf_middleware_rejects_missing_token_and_accepts_matching_token(self):
        # RequestFactory는 미들웨어를 실행하지 않으므로 실제 CSRF 검사를 직접 거친다.
        middleware = CsrfViewMiddleware(lambda request: HttpResponse())
        missing = self.request()
        middleware.process_request(missing)
        response = middleware.process_view(missing, request_decision, (), {})
        self.assertEqual(response.status_code, 403)

        valid = self.request()
        valid.META["HTTP_X_CSRFTOKEN"] = get_token(valid)
        valid.COOKIES[settings.CSRF_COOKIE_NAME] = valid.META["CSRF_COOKIE"]
        middleware.process_request(valid)
        self.assertIsNone(middleware.process_view(valid, request_decision, (), {}))

    def test_missing_slot_or_profile_does_not_call_upstream(self):
        with patch("ad_bridge.game.views.AdsClient") as client_class:
            with override_settings(ADS_SLOT_ID=""):
                response = request_decision(self.request())
            self.assertEqual(response.status_code, 503)
            self.assertEqual(json.loads(response.content)["error"], "ads_not_configured")

            for profile in (None, SimpleNamespace(user_uuid=None)):
                with self.subTest(profile=profile):
                    request = self.request()
                    request.user.campus_profile = profile
                    response = request_decision(request)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(
                        json.loads(response.content)["error"], "profile_uuid_missing"
                    )
            client_class.assert_not_called()

    def test_invalid_environment_or_uuid_is_a_configuration_error(self):
        for failure_stage in ("config", "decision"):
            with self.subTest(failure_stage=failure_stage), patch(
                "ad_bridge.game.views.AdsConfig.from_env", return_value=self.config
            ) as config_class, patch("ad_bridge.game.views.AdsClient") as client_class:
                failure = ValueError("invalid private configuration")
                if failure_stage == "config":
                    config_class.side_effect = failure
                else:
                    client_class.return_value.create_decision.side_effect = failure
                response = request_decision(self.request())
            self.assertEqual(response.status_code, 503)
            self.assertEqual(json.loads(response.content)["error"], "ads_invalid_config")
            self.assertNotIn("invalid private configuration", response.content.decode())

    def test_upstream_http_error_preserves_status_and_request_id(self):
        with patch("ad_bridge.game.views.AdsConfig.from_env", return_value=self.config), patch(
            "ad_bridge.game.views.AdsClient"
        ) as client_class:
            client_class.return_value.create_decision.side_effect = AdsHTTPError(
                404, code="not_found", request_id="upstream-request-404"
            )
            response = request_decision(self.request())
            client_class.return_value.create_decision.assert_called_once()
        self.assertEqual(response.status_code, 502)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"], "ads_http_error")
        self.assertEqual(payload["upstream_status"], 404)
        self.assertEqual(payload["request_id"], "upstream-request-404")

    def test_transport_and_invalid_response_fail_safely_without_retry(self):
        cases = (
            (AdsTransportError(MEDIA_KEY), "ads_unreachable"),
            (AdsResponseError(MEDIA_KEY), "ads_invalid_response"),
        )
        for failure, expected_error in cases:
            with self.subTest(expected_error=expected_error), patch(
                "ad_bridge.game.views.AdsConfig.from_env", return_value=self.config
            ), patch("ad_bridge.game.views.AdsClient") as client_class:
                client_class.return_value.create_decision.side_effect = failure
                response = request_decision(self.request())
                client_class.return_value.create_decision.assert_called_once()
            self.assertEqual(response.status_code, 502)
            self.assertEqual(json.loads(response.content)["error"], expected_error)
            self.assertNotIn(MEDIA_KEY, response.content.decode())

    def test_actual_client_rejects_invalid_server_uuids_before_http(self):
        # 요청 함수를 통째로 대체하지 않아 실제 UUID 검증까지 연결되는지 확인한다.
        config = AdsConfig("http://ads.test/api/media/v1", MEDIA_KEY, 5, subject_secret="unit-test-subject-secret")
        with patch("ad_bridge.game.views.AdsConfig.from_env", return_value=config), patch(
            "ad_bridge.api.client.build_opener"
        ) as build_opener:
            for slot_id, subject_id in (("not-a-slot", SUBJECT_ID), (SLOT_ID, "nickname")):
                with self.subTest(slot_id=slot_id), override_settings(ADS_SLOT_ID=slot_id):
                    request = self.request()
                    request.user.campus_profile.user_uuid = subject_id
                    response = request_decision(request)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(json.loads(response.content)["error"], "ads_invalid_config")
            build_opener.return_value.open.assert_not_called()

    def test_actual_client_sends_each_logged_in_profile_to_the_configured_endpoint(self):
        config = AdsConfig("http://ads.test/api/media/v1", MEDIA_KEY, 5, subject_secret="unit-test-subject-secret")
        opener = Mock()
        with patch("ad_bridge.game.views.AdsConfig.from_env", return_value=config), patch(
            "ad_bridge.api.client.build_opener", return_value=opener
        ):
            # 사용자별 UUID가 서로 섞이지 않고 매번 현재 로그인 프로필에서 선택되어야 한다.
            for subject_id, expected_subject in ((SUBJECT_ID, str(AD_SUBJECT_ID)),
                    (UUID("99887766-1234-4234-8234-123456789abc"), "ba123227-029b-4392-d1d6-4443da7790d6")):
                body = {
                    "decision_id": DECISION_ID, "slot_id": SLOT_ID, "slot_name": "테스트 슬롯",
                    "audience": "individual", "decided_at": "2026-10-11T12:00:00Z", "ad": None,
                }
                upstream = io.BytesIO(json.dumps(body).encode())
                upstream.status = 201
                upstream.headers = Message()
                upstream.headers["Content-Type"] = "application/json"
                opener.open.return_value = upstream
                request = self.request({"subject_id": "forged-user"})
                request.user.campus_profile.user_uuid = subject_id
                result = request_decision(request)
                self.assertEqual(result.status_code, 201)
                outgoing = opener.open.call_args.args[0]
                self.assertEqual(outgoing.full_url, "http://ads.test/api/media/v1/decisions")
                self.assertEqual(outgoing.method, "POST")
                self.assertEqual(json.loads(outgoing.data), {
                    "slot_id": SLOT_ID, "subject_id": expected_subject,
                })
                self.assertNotIn(str(subject_id), outgoing.data.decode())
                self.assertNotIn(SUBJECT_SECRET, outgoing.data.decode())
                self.assertEqual(outgoing.get_header("X-media-key"), MEDIA_KEY)
                self.assertEqual(opener.open.call_args.kwargs, {"timeout": 5.0})
                self.assertNotIn(MEDIA_KEY, result.content.decode())
            self.assertEqual(opener.open.call_count, 2)

    def test_subject_pseudonym_is_stable_and_normalizes_uuid_input(self):
        # 고정 벡터로 접두사·해시·앞 16바이트 및 UUID 정규화 규칙을 함께 검증한다.
        for value in (SUBJECT_ID, str(SUBJECT_ID), str(SUBJECT_ID).upper(), SUBJECT_ID.hex):
            user = self.request().user
            user.campus_profile.user_uuid = value
            self.assertEqual(_subject_id(_owner_id(user), subject_secret=SUBJECT_SECRET), AD_SUBJECT_ID)
        self.assertNotEqual(_subject_id(_owner_id(self.request().user), subject_secret="other-secret"), AD_SUBJECT_ID)

    def test_missing_or_invalid_subject_secret_blocks_all_game_calls(self):
        # 세 경로 모두 가명 비밀 오류에서 DB 조회와 외부 요청 전에 중단한다.
        for secret in (None, "", " private-secret ", "private-secret\n"):
            with self.subTest(secret_type=type(secret).__name__), patch.dict(os.environ), patch(
                "ad_bridge.game.views.AdsClient"
            ) as client_class, patch("ad_bridge.game.views.impression_store.get_impression") as lookup:
                if secret is None:
                    os.environ.pop("ADS_SUBJECT_SECRET", None)
                else:
                    os.environ["ADS_SUBJECT_SECRET"] = secret
                for view, args in ((request_decision, ()), (report_impression, (DECISION_ID,)),
                                   (reaction_result, (DECISION_ID,))):
                    response = view(self.request(), *args)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(json.loads(response.content)["error"], "ads_invalid_config")
                    self.assertNotIn("private-secret", response.content.decode())
                    self.assertNotIn(str(SUBJECT_ID), response.content.decode())
                client_class.assert_not_called()
                lookup.assert_not_called()

    def test_result_lookup_uses_internal_owner(self):
        record = SimpleNamespace(delivery_state="ACKNOWLEDGED", status="ACCEPTED",
            decision_id=DECISION_ID, reaction_id="reaction", reason_code=None,
            request_id=None, attempts=1, last_error=None)
        with patch("ad_bridge.game.views.impression_store.get_impression", return_value=record) as lookup:
            response = reaction_result(self.request(), DECISION_ID)
        self.assertEqual(response.status_code, 200)
        lookup.assert_called_once_with(decision_id=DECISION_ID, owner_id=SUBJECT_ID)
