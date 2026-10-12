"""ads-server manage.py에서 실행한다. 개발 DB의 광고·계정·매체 키는 사용하지 않는다."""

from datetime import timedelta
from uuid import uuid4

from django.test import LiveServerTestCase
from django.utils import timezone

from ad_bridge import AdsClient, AdsConfig, AdsHTTPError
from billing import api as billing
from campaigns import api as campaigns
from masters import api as masters
from records.models import Decision, Reaction
from serving_api.throttle import buckets
from tests.factories import make_admin, make_advertiser, png_file


class ProviderDecisionTests(LiveServerTestCase):
    def setUp(self):
        buckets.reset()
        self.addCleanup(buckets.reset)
        self.admin = make_admin()
        self.adv = make_advertiser()
        billing.grant_signup(self.adv)
        self.media = masters.create_media(self.admin, "브리지 통합 시험")
        self.slot = masters.create_slot(self.admin, self.media.media_id, "개인 배너", "IMPRESSION", 10, 20, 50, "시험")
        self.key = masters.issue_media_key(self.admin, self.media.media_id, "시험 전용").key
        self.bridge = AdsClient(AdsConfig(f"{self.live_server_url}/api/media/v1", self.key, 5))
        self.subject = str(uuid4())

    def add_ad(self, slot):
        now = timezone.now()
        campaign = campaigns.create_campaign(self.adv, "실제 응답 시험", now - timedelta(minutes=1), None, 1000)
        group = campaigns.create_ad_group(self.adv, campaign.campaign_id, "그룹", "IMPRESSION", [slot.slot_id], bid_amount=20)
        return campaigns.create_creative(self.adv, group.ad_group_id, "광고 제목", "https://example.com", png_file())

    def test_real_ad_response_is_stored_and_does_not_charge(self):
        creative = self.add_ad(self.slot)
        before = billing.get_wallet(self.adv).balance
        result = self.bridge.create_decision(self.slot.slot_id, self.subject)
        self.assertEqual(result.ad.creative_id, str(creative.creative_id))
        self.assertIn("/assets/", result.ad.image_url)
        self.assertIn("/c/", result.ad.click_url)
        self.assertTrue(result.request_id)
        self.assertTrue(Decision.objects.filter(pk=result.decision_id, subject_id=self.subject).exists())
        self.assertEqual(billing.get_wallet(self.adv).balance, before)
        self.assertEqual(billing.get_wallet(self.adv).spent_today, 0)
        self.assertEqual(Reaction.objects.count(), 0)

    def test_real_no_ad_response(self):
        result = self.bridge.create_decision(self.slot.slot_id, self.subject)
        self.assertIsNone(result.ad)
        self.assertTrue(Decision.objects.filter(pk=result.decision_id).exists())

    def test_real_authentication_and_subject_errors(self):
        bad = AdsClient(AdsConfig(f"{self.live_server_url}/api/media/v1", "invalid-key", 5))
        with self.assertRaises(AdsHTTPError) as caught:
            bad.create_decision(self.slot.slot_id, self.subject)
        self.assertEqual((caught.exception.status, caught.exception.code), (401, "unauthorized"))
        self.assertTrue(caught.exception.request_id)
        with self.assertRaises(AdsHTTPError) as caught:
            self.bridge.create_decision(self.slot.slot_id)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(Decision.objects.count(), 0)

    def test_real_shared_response_preserves_person_placeholder(self):
        slot = masters.create_slot(self.admin, self.media.media_id, "공유 배너", "IMPRESSION", 10, 20, 50, "시험", audience="shared")
        self.add_ad(slot)
        result = self.bridge.create_decision(slot.slot_id)
        self.assertEqual(result.audience, "shared")
        self.assertIn("{subject_id}", result.ad.click_url)

    def test_redirect_does_not_forward_key_or_reissue_request(self):
        # 실제 HTTP 302에도 API 인증 헤더를 다른 경로로 재전송하지 않는다.
        from django.contrib.auth.decorators import login_not_required
        from django.http import HttpResponseRedirect
        from django.test import override_settings
        from django.urls import path

        seen = []

        @login_not_required
        def redirecting(request):
            seen.append("initial")
            return HttpResponseRedirect("/destination")

        @login_not_required
        def destination(request):
            seen.append("destination")
            return HttpResponseRedirect("/")

        class RedirectUrls:
            urlpatterns = [path("api/media/v1/decisions", redirecting), path("destination", destination)]

        with override_settings(ROOT_URLCONF=RedirectUrls):
            with self.assertRaises(AdsHTTPError) as caught:
                self.bridge.create_decision(self.slot.slot_id, self.subject)
        self.assertEqual(caught.exception.status, 302)
        self.assertEqual(seen, ["initial"])
