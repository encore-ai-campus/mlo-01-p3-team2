"""Step 3-0 S3: 광고 만들기(`campaigns.api.create_ad`) — 캠페인·광고그룹·소재를 한 트랜잭션으로. 하나라도 실패하면 아무것도 남지 않는다(설계 D3-3)."""
import io

from django.test import TestCase, override_settings, tag

from assets.api import ImageRejected
from campaigns import api as campaigns
from campaigns.models import AdGroup, Bid, Campaign, Creative
from foundation.api import errors
from foundation.models import AuditLog
from tests.factories import DAY, NOW, make_admin, make_advertiser, make_slot, png_file


@tag("security")
class CreateAdTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.adv = make_advertiser()
        self.slot = make_slot(self.admin, unit="CLICK")

    def create(self, campaign=None, ad_group=None, creative=None, user=None):
        return campaigns.create_ad(
            user or self.adv,
            campaign={"name": "가을 캠페인", "starts_at": NOW, "ends_at": NOW + 10 * DAY, "daily_budget": 5000, **(campaign or {})},
            ad_group={"name": "로비 배너", "pricing_unit": "CLICK", "slot_ids": [self.slot.slot_id], "bid_amount": 30, **(ad_group or {})},
            creative={"title": "제목", "redirect_url": "https://example.com/landing", "image_file": png_file(), **(creative or {})},
            now=NOW,
        )

    def assertNothingCreated(self):
        self.assertEqual((Campaign.objects.count(), AdGroup.objects.count(), Bid.objects.count(), Creative.objects.count()), (0, 0, 0, 0))
        self.assertFalse(AuditLog.objects.filter(action__in=["campaign.created", "ad_group.created", "creative.created"]).exists())

    def test_creates_all_three_and_returns_their_views(self):
        ad = self.create()
        self.assertIsInstance(ad, campaigns.CreatedAd)
        self.assertEqual((ad.campaign.name, ad.ad_group.name, ad.creative.title), ("가을 캠페인", "로비 배너", "제목"))
        self.assertEqual((ad.ad_group.campaign_id, ad.creative.ad_group_id), (ad.campaign.campaign_id, ad.ad_group.ad_group_id))
        self.assertEqual(ad.ad_group.current_bid.amount, 30)
        self.assertEqual(Campaign.objects.get().owner, self.adv)
        self.assertEqual(sorted(AuditLog.objects.filter(actor_id=self.adv.pk).values_list("action", flat=True)), ["ad_group.created", "campaign.created", "creative.created"])

    def test_a_rejected_image_leaves_no_campaign_or_ad_group(self):
        with self.assertRaises(ImageRejected):
            self.create(creative={"image_file": io.BytesIO(b"not an image")})
        self.assertNothingCreated()

    def test_a_failure_in_any_part_leaves_nothing(self):
        other_unit = make_slot(self.admin, unit="IMPRESSION")
        cases = {
            "캠페인 이름": ({"name": ""}, None, None),
            "광고그룹 위치의 과금 단위": (None, {"slot_ids": [other_unit.slot_id]}, None),
            "입찰 금액": (None, {"bid_amount": 0}, None),
            "이동 주소": (None, None, {"redirect_url": "http://example.com"}),
            "소재 제목": (None, None, {"title": ""}),
        }
        for label, (campaign, ad_group, creative) in cases.items():
            with self.subTest(label), self.assertRaises(errors.InvalidRequest):
                self.create(campaign, ad_group, creative)
            self.assertNothingCreated()

    def test_errors_say_which_part_they_belong_to(self):
        """세 부분 모두 `/name` 같은 같은 이름의 칸이 있다 — 오류가 어느 부분의 칸인지 알려야 화면이 그 칸 옆에 보여 준다."""
        for part, override, pointer in (
            ("campaign", {"campaign": {"name": ""}}, "/campaign/name"),
            ("ad_group", {"ad_group": {"name": ""}}, "/ad_group/name"),
            ("creative", {"creative": {"title": ""}}, "/creative/title"),
        ):
            with self.subTest(part), self.assertRaises(errors.InvalidRequest) as e:
                self.create(**override)
            self.assertEqual([x["pointer"] for x in e.exception.errors], [pointer])

    @override_settings(MAX_CAMPAIGNS_PER_ADVERTISER=0)
    def test_a_limit_leaves_nothing(self):
        with self.assertRaises(campaigns.LimitExceeded):
            self.create()
        self.assertNothingCreated()

    def test_only_an_advertiser(self):
        with self.assertRaises(errors.Forbidden):
            self.create(user=self.admin)
        self.assertNothingCreated()
