"""외부 검토(41d2288) P2: 광고주 전체 상한과 요청 키의 경쟁.

1. 서로 다른 캠페인의 동시 쓰기가 광고주 전체 상한(캠페인 수·이미지 보유량)을 넘겼다 — 캠페인마다 잠그면 함께 줄을 서지 않는다.
   → 만들기·이미지 교체는 광고주 잠금 행(`AdvertiserQuota`)을 가장 먼저 잡고, 잠금 안에서 상한을 다시 센다.
2. 성공한 요청 키의 겹친 재전송이 상한 오류(409)로 끝났다 — 첫 조회와 앞선 요청의 커밋 사이의 틈.
   → 같은 잠금 안에서 키를 다시 본다.
실제 MySQL 연결 두 개로, 한쪽이 쓰기 직전(상한 확인 뒤)에 멈춘 사이 다른 쪽을 실행한다.
"""
import threading

from django.test import TransactionTestCase, override_settings, tag

from assets.api import validate_image
from campaigns import api as campaigns
from campaigns.models import Campaign, CreativeImage
from tests.concurrency import BLOCKED, WAIT, Worker, pausing_before
from tests.factories import NOW, World, png_file


@tag("security")
class QuotaRaceTests(TransactionTestCase):
    def setUp(self):
        self.w = World(ends_in=None)

    def ad(self, key, color):
        return lambda: campaigns.create_ad(
            self.w.adv,
            campaign={"name": f"광고 {key}", "starts_at": NOW, "ends_at": None, "daily_budget": 1000},
            ad_group={"name": "그룹", "pricing_unit": "IMPRESSION", "slot_ids": [self.w.slot.slot_id], "bid_amount": 30},
            creative={"title": "제목", "redirect_url": "https://example.com/", "image_file": png_file(color)},
            request_key=key,
        )

    def overlap(self, first, verb, table, second):
        """`first` 가 `table` 에 쓰기 직전(상한 확인 뒤)에 멈춘 사이 `second` 를 보낸다. 둘째는 광고주 잠금에서 기다려야 한다."""
        paused, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        a = Worker(pausing_before(verb, table, first, paused, release))
        a.start()
        self.assertTrue(paused.wait(WAIT), f"첫 요청이 {table} {verb} 에 이르지 않았다")
        b = Worker(second)
        b.start()
        b.join(BLOCKED)
        self.assertTrue(b.is_alive(), "둘째 요청이 광고주 잠금을 기다리지 않았다")
        release.set()
        a.join(WAIT)
        b.join(WAIT)
        self.assertEqual(a.errors, [])
        return b

    @override_settings(MAX_CAMPAIGNS_PER_ADVERTISER=2)  # 이미 1개
    def test_two_new_ads_with_different_keys_do_not_pass_the_campaign_limit(self):
        second = self.overlap(self.ad("k1", (1, 1, 1)), "INSERT", "campaigns_campaign", self.ad("k2", (2, 2, 2)))
        self.assertEqual([type(e) for e in second.errors], [campaigns.LimitExceeded])
        self.assertEqual(Campaign.objects.filter(owner=self.w.adv).count(), 2)

    @override_settings(MAX_CAMPAIGNS_PER_ADVERTISER=2)
    def test_an_overlapping_resubmission_of_the_same_key_finds_the_first_ad_not_the_limit(self):
        second = self.overlap(self.ad("same", (1, 1, 1)), "INSERT", "campaigns_campaign", self.ad("same", (1, 1, 1)))
        self.assertEqual(second.errors, [])
        self.assertTrue(second.result.duplicate)
        self.assertEqual(Campaign.objects.filter(owner=self.w.adv).count(), 2)

    def test_two_image_replacements_in_different_campaigns_do_not_pass_the_upload_quota(self):
        other = campaigns.create_campaign(self.w.adv, "둘째", NOW, None, 1000)
        group = campaigns.create_ad_group(self.w.adv, other.campaign_id, "그룹", "IMPRESSION", [self.w.slot.slot_id], bid_amount=30)
        creative = campaigns.create_creative(self.w.adv, group.ad_group_id, "제목", "https://example.com/", png_file((9, 9, 9)))
        held = sum(dict(CreativeImage.objects.filter(creative__ad_group__campaign__owner=self.w.adv).values_list("image_name", "image_bytes")).values())
        a_bytes, b_bytes = (len(validate_image(png_file(c)).data) for c in ((3, 3, 3), (4, 4, 4)))
        limit = held + max(a_bytes, b_bytes) + min(a_bytes, b_bytes) - 1  # 하나씩은 들어가지만 둘 다는 안 들어간다
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=limit):
            second = self.overlap(lambda: campaigns.replace_creative_image(self.w.adv, self.w.creative.creative_id, png_file((3, 3, 3))),
                                  "UPDATE", "campaigns_creative",
                                  lambda: campaigns.replace_creative_image(self.w.adv, creative.creative_id, png_file((4, 4, 4))))
        self.assertEqual([type(e) for e in second.errors], [campaigns.LimitExceeded])
        now_held = sum(dict(CreativeImage.objects.filter(creative__ad_group__campaign__owner=self.w.adv).values_list("image_name", "image_bytes")).values())
        self.assertLessEqual(now_held, limit)
