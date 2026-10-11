"""Step 3-2a 광고주 대시보드: 기간(오늘 포함 최근 N일, 예산 일 경계 — 설계 D3-5)·지표 카드(직전 같은 길이 대비 증감)·서버가 그린 SVG 추세 그래프와 같은 값의 표·포인트.

시각은 `NOW`(2026-10-07 12:00 UTC)로 고정한다(대시보드의 `_now` 를 바꾼다). 예산 일은 UTC 자정이라 오늘은 2026-10-07 이다.
"""
import re
import uuid
from datetime import date, timedelta
from random import Random
from unittest import mock

from django.test import TestCase, tag
from django.urls import reverse

from campaigns.models import Campaign
from records import api as records
from records.models import Reaction
from tests.factories import DAY, NOW, SUBJECT, World

SEC = timedelta(seconds=1)


def impression(world, when):
    """`when` 에 결정, 1초 뒤 노출 수신·인정(입찰 30 이 과금된다)."""
    decision = records.decide(world.slot.media_id, world.slot.slot_id, subject_id=SUBJECT, now=when, rng=Random(1))
    view, _ = records.receive_reaction(decision.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", when + SEC, {}, now=when + SEC)
    assert records.process_reaction(Reaction.objects.get(pk=view.inbox_id).inbox_id, now=when + SEC) == "ACCEPTED"


@tag("security")
class DashboardTests(TestCase):
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

    def test_default_is_the_last_seven_days_including_today_and_today_is_marked(self):
        html = self.page()
        self.assertEqual(self.dates(html), [f"2026-10-{d:02d}" for d in range(1, 8)])
        self.assertEqual(html.count("(집계 중)"), 1)
        self.assertIn("<td>2026-10-07 (집계 중)", html)
        self.assertEqual(html.count('class="bar'), 7)
        self.assertEqual(html.count('class="bar partial"'), 1)  # 오늘 막대는 흐리게

    def test_cards_show_totals_and_the_change_against_the_previous_window(self):
        impression(self.w, NOW - DAY)
        impression(self.w, NOW)  # 오늘(집계 중)도 합에 들어간다
        impression(self.w, NOW - 8 * DAY)  # 직전 7일
        html = self.page()
        cards = re.search(r'<section class="cards".*?</section>', html, re.S).group(0)
        self.assertIn('<div class="value">2</div>', cards)  # 노출
        self.assertIn("직전 7일 대비 +100.0%", cards)
        self.assertIn('<div class="value">60</div>', cards)  # 소진 포인트(입찰 30 × 2)

    def test_no_data_and_zero_previous_do_not_divide_by_zero(self):
        html = self.page()
        self.assertIn("직전 7일 대비 —", html)
        self.assertIn("클릭률 —", html)
        self.assertIn("전환율 —", html)

    def test_other_advertisers_numbers_never_show_up(self):
        other = World(ends_in=None)
        for _ in range(3):
            impression(other, NOW)
        cards = re.search(r'<section class="cards".*?</section>', self.page(), re.S).group(0)
        self.assertEqual(re.findall(r'<div class="value">([^<]+)</div>', cards), ["0", "0", "0", "0"])

    def test_period_choice_and_bad_values_fall_back(self):
        self.assertEqual(len(self.dates(self.page(days=14))), 14)
        self.assertEqual(len(self.dates(self.page(days=90))), 90)
        for bad in ({"days": "abc"}, {"days": 92}, {"days": -1}, {"metric": "<script>"}):
            html = self.page(**bad)
            self.assertEqual(len(self.dates(html)), 7, bad)
            self.assertNotIn("<script>", html)

    def test_the_chart_is_inline_svg_with_a_table_of_the_same_values(self):
        impression(self.w, NOW - 2 * DAY)
        html = self.page(metric="spent")
        svg = re.search(r"<svg.*?</svg>", html, re.S).group(0)
        self.assertIn('role="img"', svg)
        self.assertIn("소진 포인트 일별 추세", svg)
        self.assertIn("<title>10-05 30</title>", svg)  # 막대마다 값
        self.assertRegex(html, r"<td>2026-10-05</td>\s*(<td class=\"num\">[^<]+</td>){3}<td class=\"num\">30</td>")  # 표에도 같은 값
        self.assertNotRegex(html, r"\sstyle=")  # CSP: 인라인 style 없음
        self.assertNotIn("<script", html)

    def test_points_widget(self):
        impression(self.w, NOW)
        html = self.page()
        self.assertIn("잔액 <strong>49,970 포인트</strong>", html)
        self.assertIn("오늘 소진 30 포인트", html)
        self.assertIn("2026-10-08 09:00", html)  # 다음 예산 일 시작(KST)

    def test_only_the_advertiser_sees_it(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)  # 로그인으로
        self.client.force_login(self.w.admin)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)
