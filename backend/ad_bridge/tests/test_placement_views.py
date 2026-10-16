"""새 API의 인증·CSRF·이동 승인 검증과 공유 노출 가명 연결을 검사한다."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, TestCase, override_settings

from ad_bridge.api.config import AdsConfig
from ad_bridge.game.placements import placement
from ad_bridge.placements import transfer_token


@override_settings(ADS_ENABLED=True)
class PlacementViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(pk=7, is_authenticated=True,
            campus_profile=SimpleNamespace(user_uuid=uuid4()))

    def request(self, body):
        request = self.factory.post('/api/ads/placements/portal/', data=json.dumps(body), content_type='application/json')
        request.user = self.user
        return request

    def test_invalid_or_other_user_transfer_never_calls_ad_server(self):
        for body in ([], {}, {"token": {}}, {"token": "forged"}, {"token": transfer_token(8, uuid4())}):
            with self.subTest(body=body), patch('ad_bridge.game.placements.AdsClient') as client:
                self.assertEqual(placement(self.request(body), 'portal').status_code, 400)
                client.assert_not_called()

    def test_login_and_csrf_are_required(self):
        request = self.request({})
        request.user = AnonymousUser()
        self.assertEqual(placement(request, 'portal').status_code, 302)
        request = self.request({})
        self.assertEqual(CsrfViewMiddleware(lambda r: None).process_view(request, placement, (), {"location":"portal"}).status_code, 403)

    @override_settings(ADS_ENABLED=False)
    def test_unconfigured_environment_does_not_request_ads(self):
        with patch('ad_bridge.game.placements.AdsClient') as client:
            self.assertEqual(placement(self.request({}), 'rooftop').status_code, 503)
            client.assert_not_called()

    def test_approved_transfer_is_passed_with_server_owner_only(self):
        transfer = uuid4()
        config = AdsConfig('https://ads.test/api/media/v1','test-key',1,subject_secret='secret')
        with patch('ad_bridge.game.placements.AdsConfig.from_env', return_value=config), \
             patch('ad_bridge.game.placements.get_batch') as batch, \
             patch('ad_bridge.game.placements.public_batch', return_value={"ads": []}):
            batch.return_value = Mock(state='READY')
            response = placement(self.request({"token": transfer_token(7, transfer), "owner_id": str(uuid4())}), 'portal')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(batch.call_args.kwargs['owner_id'], self.user.campus_profile.user_uuid)
            self.assertEqual(batch.call_args.kwargs['transfer_id'], str(transfer))
