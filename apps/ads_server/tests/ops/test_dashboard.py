"""Step 3-2a 광고주 대시보드: 기간(오늘 포함 최근 N일, 예산 일 경계 — 설계 D3-5)·지표 카드(직전 같은 길이 대비 증감)·서버가 그린 SVG 추세 그래프와 같은 값의 표·포인트.

시각은 `NOW`(2026-10-07 12:00 UTC)로 고정한다(대시보드의 `_now` 를 바꾼다). 예산 일은 UTC 자정이라 오늘은 2026-10-07 이다.
"""
import re
from unittest import mock

from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from billing import api as billing
from campaigns import api as campaigns
from campaigns.models import Campaign
from records import api as records
from tests.support.factories import DAY, NOW, World, impression, make_slot, png_file
from tests.support.cases import Cases


@tag("security")
class DashboardTests(Cases, TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        Campaign.objects.filter(pk=self.w.campaign.campaign_id).update(starts_at=NOW - 30 * DAY)  # 직전 구간에도 노출이 있게
        self.client.force_login(self.w.adv)
        patch = mock.patch("console.views.dashboard._now", return_value=NOW)
        patch.start()
        self.addCleanup(patch.stop)
        self.url = reverse("advertiser_home")

    def page(self, **params):
        r = self.client.get(self.url, params)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def dates(self, html):
        return re.findall(r"<td>(\d{4}-\d{2}-\d{2})", html)

    def case_the_page_reads_the_wallet_and_the_campaign_list_once(self):
        """계획 3-4g B1: 포인트 위젯과 잔액 알림, 상위 캠페인 표와 알림이 같은 읽기를 본다(전에는 지갑·캠페인 목록을 두 번씩 읽었다)."""
        with mock.patch.object(billing, "get_wallet", wraps=billing.get_wallet) as wallet, \
                mock.patch.object(campaigns, "list_campaigns", wraps=campaigns.list_campaigns) as listed:
            self.page()
        self.assertEqual((wallet.call_count, listed.call_count), (1, 1))

    def case_default_is_the_last_seven_days_including_today_and_today_is_marked(self):
        html = self.page()
        self.assertEqual(self.dates(html), [f"2026-10-{d:02d}" for d in range(1, 8)])
        self.assertEqual(html.count("(집계 중)"), 1)
        self.assertIn("<td>2026-10-07 (집계 중)", html)
        self.assertEqual(html.count('class="bar'), 7)
        self.assertEqual(html.count('class="bar partial"'), 1)  # 오늘 막대는 흐리게

    def case_cards_show_totals_and_the_change_against_the_previous_window(self):
        impression(self.w, NOW - DAY)
        impression(self.w, NOW)  # 오늘(집계 중)도 합에 들어간다
        impression(self.w, NOW - 8 * DAY)  # 직전 7일
        html = self.page()
        cards = re.search(r'<section class="cards".*?</section>', html, re.S).group(0)
        self.assertIn('<div class="value">2</div>', cards)  # 노출
        self.assertIn("직전 7일 대비 +100.0%", cards)
        self.assertIn('<div class="value">588</div>', cards)  # 소진 포인트(입찰 300 × 노출 98% = 294, 두 번)

    def case_no_data_and_zero_previous_do_not_divide_by_zero(self):
        html = self.page()
        self.assertIn("직전 7일 대비 —", html)
        self.assertIn("클릭률 —", html)
        self.assertIn("전환율 —", html)

    def case_other_advertisers_numbers_never_show_up(self):
        other = World(ends_in=None)
        for _ in range(3):
            impression(other, NOW)
        cards = re.search(r'<section class="cards".*?</section>', self.page(), re.S).group(0)
        self.assertEqual(re.findall(r'<div class="value">([^<]+)</div>', cards), ["0", "0", "0", "0"])

    def case_period_choice_and_bad_values_fall_back(self):
        self.assertEqual(len(self.dates(self.page(days=14))), 14)
        self.assertEqual(len(self.dates(self.page(days=90))), 90)
        for bad in ({"days": "abc"}, {"days": 92}, {"days": -1}, {"metric": "<script>"}):
            html = self.page(**bad)
            self.assertEqual(len(self.dates(html)), 7, bad)
            self.assertNotIn("<script>", html)

    def case_the_chart_is_inline_svg_with_a_table_of_the_same_values(self):
        impression(self.w, NOW - 2 * DAY)
        html = self.page(metric="spent")
        svg = re.search(r"<svg class=\"chart\".*?</svg>", html, re.S).group(0)  # 메뉴 아이콘(장식 SVG)이 아니라 그래프
        self.assertIn('role="img"', svg)
        self.assertIn("소진 포인트 일별 추세", svg)
        self.assertIn("<title>10-05 294</title>", svg)  # 막대마다 값
        self.assertRegex(html, r"<td>2026-10-05</td>\s*(<td class=\"num\">[^<]+</td>){3}<td class=\"num\">294</td>")  # 표에도 같은 값
        self.assertNotRegex(html, r"\sstyle=")  # CSP: 인라인 style 없음
        self.assertNotIn("<script", html)

    def case_points_widget(self):
        impression(self.w, NOW)
        html = self.page()
        self.assertIn("잔액 <strong>49,706 포인트</strong>", html)
        self.assertIn("오늘 소진 294 포인트", html)
        self.assertIn("2026-10-08 09:00", html)  # 다음 예산 일 시작(KST)

    def test_dashboard(self):
        self.run_cases()


@tag("security")
class TopCampaignTests(Cases, TestCase):
    """상위 캠페인 표: 캠페인별 합계(`records.campaign_totals`)는 일별 성과와 같은 규칙이고, 화면은 소진 포인트 순으로 보인다."""

    def setUp(self):
        self.w = World(ends_in=None)
        Campaign.objects.filter(pk=self.w.campaign.campaign_id).update(starts_at=NOW - 30 * DAY)
        self.slot2 = make_slot(self.w.admin)
        self.second = campaigns.create_campaign(self.w.adv, "<b>둘째</b>", NOW - 30 * DAY, None, 5000, now=NOW)
        group = campaigns.create_ad_group(self.w.adv, self.second.campaign_id, "그룹", [self.slot2.slot_id], bid_amount=400, now=NOW)
        campaigns.create_creative(self.w.adv, group.ad_group_id, "제목", "https://example.com/2", png_file((9, 9, 9)), now=NOW)
        self.window = (NOW.replace(hour=0) - 6 * DAY, NOW.replace(hour=0) + DAY)

    def case_campaign_totals_follow_the_daily_report_rules(self):
        impression(self.w, NOW - DAY)
        impression(self.w, NOW, slot=self.slot2)
        impression(self.w, NOW - DAY, slot=self.slot2)
        impression(self.w, NOW - 10 * DAY)  # 기간 밖
        other = World(ends_in=None)
        impression(other, NOW)  # 다른 광고주
        totals = records.campaign_totals(self.w.adv, *self.window)
        self.assertEqual({cid: (t.impressions, t.spent) for cid, t in totals.items()},
                         {self.w.campaign.campaign_id: (1, 294), self.second.campaign_id: (2, 784)})  # 노출 98%: 300 → 294, 400 → 392
        report = records.daily_report(self.w.adv, *self.window)
        self.assertEqual((sum(t.impressions for t in totals.values()), sum(t.spent for t in totals.values())), (report.totals.impressions, report.totals.spent))

    def case_the_number_of_queries_does_not_grow_with_the_data(self):
        impression(self.w, NOW)
        with CaptureQueriesContext(connection) as few:
            records.campaign_totals(self.w.adv, *self.window)
        for _ in range(3):
            impression(self.w, NOW, slot=self.slot2)
        with CaptureQueriesContext(connection) as many:
            records.campaign_totals(self.w.adv, *self.window)
        self.assertEqual(len(few), len(many))

    def case_the_table_ranks_by_spent_and_escapes_names(self):
        self.client.force_login(self.w.adv)
        with mock.patch("console.views.dashboard._now", return_value=NOW):
            self.assertContains(self.client.get(reverse("advertiser_home")), "이 기간에 성과가 있는 캠페인이 없습니다")
            impression(self.w, NOW)
            impression(self.w, NOW, slot=self.slot2)
            html = self.client.get(reverse("advertiser_home")).content.decode()
        table = re.search(r'aria-label="상위 캠페인".*?</section>', html, re.S).group(0)
        self.assertEqual(re.findall(r"<tr><td>([^<]+)</td>", table), ["&lt;b&gt;둘째&lt;/b&gt;", "캠페인"])  # 소진 392 > 294
        self.assertNotIn("<b>둘째</b>", html)

    def test_top_campaign(self):
        self.run_cases()
