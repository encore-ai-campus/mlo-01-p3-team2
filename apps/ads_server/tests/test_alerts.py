"""Step 3-2a 알림 패널(C6 `/alerts`, 계획 S5): 저장하지 않고 지금 상태에서 계산한다 — 조건이 풀리면 사라진다.

비교는 결정 엔진의 후보 거르기와 같아야 한다(남은 일예산·잔액 < 적용 금액이면 그 위치에 나가지 않는다). 잔액 두 단계는 설계 D3-4.
World: 슬롯 정책 하한 10·기준 20·상한 50, 입찰 30(적용 30), 일예산 5,000, 가입 지급 50,000.
"""
import re
from random import Random
from unittest import mock

from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from billing import api as billing
from campaigns import api as campaigns
from console.queries.alerts import alerts_for
from masters import api as masters
from records import api as records
from tests.factories import DAY, NOW, SUBJECT, World, impression, make_slot


def codes(alerts):
    return [(a.code, a.severity) for a in alerts]


@tag("security")
class AlertTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.cid = self.w.campaign.campaign_id

    def alerts(self, at=NOW):
        """화면처럼 캠페인 목록과 지갑을 읽어 넘긴다."""
        return alerts_for(self.w.adv, at, campaigns.list_campaigns(self.w.adv, now=at), billing.get_wallet(self.w.adv, now=at))

    def test_a_healthy_account_has_no_alerts(self):
        self.assertEqual(self.alerts(), [])

    def test_suspension_and_the_rejection_of_this_suspension(self):
        campaigns.suspend_campaign(self.w.admin, self.cid, "부적절한 이동 주소", now=NOW)
        review = campaigns.create_review_request(self.w.adv, self.cid, "고쳤습니다", now=NOW)
        campaigns.reject_review_request(self.w.admin, review.review_request_id, "여전히 같습니다", now=NOW + DAY)
        alerts = self.alerts(NOW + DAY)
        self.assertEqual(codes(alerts), [("campaign_suspended", "critical"), ("review_rejected", "warning")])
        self.assertIn("부적절한 이동 주소", alerts[0].message)
        self.assertIn("여전히 같습니다", alerts[1].message)
        campaigns.release_campaign(self.w.admin, self.cid, now=NOW + 2 * DAY)
        campaigns.suspend_campaign(self.w.admin, self.cid, "새 사유", now=NOW + 2 * DAY)
        self.assertEqual(codes(self.alerts(NOW + 2 * DAY)), [("campaign_suspended", "critical")])  # 지난 중단의 반려는 보이지 않는다
        campaigns.release_campaign(self.w.admin, self.cid, now=NOW + 3 * DAY)
        self.assertEqual(self.alerts(NOW + 3 * DAY), [])  # 풀리면 사라진다

    def test_an_ended_campaign_is_announced_for_a_week(self):
        campaigns.end_campaign(self.w.adv, self.cid, now=NOW)
        self.assertEqual(codes(self.alerts(NOW + DAY)), [("campaign_ended", "info")])
        self.assertEqual(self.alerts(NOW + 8 * DAY), [])

    def test_budget_exhausted_when_the_rest_is_below_the_applied_amount(self):
        campaigns.update_campaign(self.w.adv, self.cid, {"daily_budget": 50}, now=NOW)
        impression(self.w, NOW)  # 30 소진, 남은 20 < 적용 30
        self.assertEqual(codes(self.alerts()), [("budget_exhausted", "warning")])
        decision = records.decide(self.w.slot.media_id, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        self.assertIsNone(decision.chosen)  # 엔진도 내보내지 않는다(같은 비교)
        self.assertEqual(self.alerts(NOW + DAY), [])  # 다음 예산 일에는 풀린다

    def test_bid_below_the_floor_and_above_the_cap(self):
        group = self.w.group.ad_group_id
        campaigns.add_bid(self.w.adv, group, 5, expected_version=1, now=NOW)
        self.assertEqual(codes(self.alerts()), [("bid_below_floor", "warning")])
        campaigns.add_bid(self.w.adv, group, 60, expected_version=2, now=NOW)
        self.assertEqual(codes(self.alerts()), [("bid_capped", "info")])

    def test_balance_low_and_insufficient_follow_the_engine(self):
        cheap = make_slot(self.w.admin, floor=10, base=15, cap=20)  # 입찰 30 → 상한 20 으로 적용
        campaigns.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"slot_ids": [self.w.slot.slot_id, cheap.slot_id]}, now=NOW)
        billing.adjust(self.w.admin, self.w.adv.pk, -(50_000 - 25), "잔액 25 로", now=NOW)
        self.assertEqual(codes(self.alerts()), [("balance_low", "warning"), ("bid_capped", "info")])
        decide = lambda slot: records.decide(slot.media_id, slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1)).chosen  # noqa: E731
        self.assertIsNone(decide(self.w.slot))  # 25 < 30: 이 위치에는 안 나간다
        self.assertIsNotNone(decide(cheap))  # 25 >= 20: 이 위치에는 나간다
        billing.adjust(self.w.admin, self.w.adv.pk, -15, "잔액 10 으로", now=NOW)
        self.assertEqual(codes(self.alerts())[0], ("balance_insufficient", "critical"))
        self.assertIsNone(decide(cheap))

    def test_effects_per_slot_follow_the_policy_and_an_inactive_slot_is_not_a_candidate(self):
        """`ad_group_effects`: 현재 입찰을 위치마다 현재 정책에 대어 본 결과(C6 `SlotEffect`). 꺼진 위치는 하한 미만이어도 `slot_inactive` 다."""
        campaigns.add_bid(self.w.adv, self.w.group.ad_group_id, 5, expected_version=1, now=NOW)
        (group,) = campaigns.ad_group_effects(self.w.adv)
        self.assertEqual([(e.reason, e.eligible, e.applied_amount, e.policy_version) for e in group.effects], [("below_floor", False, None, 1)])
        self.assertEqual(codes(self.alerts()), [("bid_below_floor", "warning")])
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        (group,) = campaigns.ad_group_effects(self.w.adv)
        self.assertEqual([e.reason for e in group.effects], ["slot_inactive"])
        self.assertEqual(self.alerts(), [])  # 꺼진 위치는 입찰 안내의 대상이 아니다

    def test_paused_campaigns_and_disabled_groups_raise_no_bid_or_balance_alerts(self):
        campaigns.add_bid(self.w.adv, self.w.group.ad_group_id, 5, expected_version=1, now=NOW)
        campaigns.update_campaign(self.w.adv, self.cid, {"status": "PAUSED"}, now=NOW)
        self.assertEqual(self.alerts(), [])

    def test_other_advertisers_alerts_never_show_up(self):
        other = World(ends_in=None)
        campaigns.suspend_campaign(other.admin, other.campaign.campaign_id, "남의 사유", now=NOW)
        self.assertEqual(self.alerts(), [])

    def test_the_number_of_queries_does_not_grow_with_campaigns(self):
        with CaptureQueriesContext(connection) as few:
            self.alerts()
        for i in range(3):
            c = campaigns.create_campaign(self.w.adv, f"더 {i}", NOW - DAY, None, 1000, now=NOW)
            campaigns.create_ad_group(self.w.adv, c.campaign_id, "그룹", "IMPRESSION", [self.w.slot.slot_id], bid_amount=5, now=NOW)
        with CaptureQueriesContext(connection) as many:
            alerts = self.alerts()
        self.assertEqual(len(few), len(many))
        self.assertEqual(len(alerts), 3)

    def test_the_panel_escapes_and_orders_by_severity(self):
        campaigns.update_campaign(self.w.adv, self.cid, {"name": "<b>캠페인</b>"}, now=NOW)
        campaigns.add_bid(self.w.adv, self.w.group.ad_group_id, 60, expected_version=1, now=NOW)
        campaigns.suspend_campaign(self.w.admin, self.cid, "<script>x</script>", now=NOW)
        other = campaigns.create_campaign(self.w.adv, "둘째", NOW - DAY, None, 1000, now=NOW)
        campaigns.create_ad_group(self.w.adv, other.campaign_id, "그룹", "IMPRESSION", [self.w.slot.slot_id], bid_amount=60, now=NOW)
        self.client.force_login(self.w.adv)
        with mock.patch("console.views.dashboard._now", return_value=NOW):
            html = self.client.get(reverse("advertiser_home")).content.decode()
        panel = html[html.index('aria-label="알림"'):html.index('aria-label="지표"')]
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", panel)
        self.assertNotIn("<script>x</script>", html)
        self.assertNotIn("<b>캠페인</b>", html)
        badges = re.findall(r'<span class="badge">([^<]+)</span>', panel)
        self.assertEqual(badges[0], "긴급")  # 중단(긴급)이 먼저, 상한 적용(알림)은 뒤
        self.assertEqual(badges[-1], "알림")
