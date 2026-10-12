"""Step 3-2e 광고주 포인트: 잔액·오늘 소진·리셋 시각, 원장 내역(최신순 커서 쪽 나누기, 과금 줄은 캠페인 이름). 완료 조건: 커서 이동, 남의 원장 비노출."""
import re
import uuid
from random import Random
from unittest import mock

from django.test import Client, TestCase, tag
from django.urls import reverse

from billing import api as billing
from campaigns import api as campaigns
from foundation.models import User
from records import api as records
from tests.factories import NOW, PW, SUBJECT, World
from tests.test_dashboard import impression

URL = reverse("points")


@tag("security")
class PointsPageTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.client.force_login(self.w.adv)
        patch = mock.patch("console.views.points._now", return_value=NOW)
        patch.start()
        self.addCleanup(patch.stop)

    def rows(self, html):
        body = html[html.index('aria-label="원장 내역"'):]
        return re.findall(r"<tr>\s*<td>[^<]+</td>\s*<td>([^<]+)</td>\s*<td class=\"num\">([^<]+)</td>", body)

    def test_balance_today_and_entries_newest_first_with_campaign_names(self):
        campaigns.update_campaign(self.w.adv, self.w.campaign.campaign_id, {"name": "<b>캠페인</b>"})
        impression(self.w, NOW)  # 과금 30
        decision = records.decide(self.w.slot.media_id, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))  # 잔액이 있을 때 나간 광고
        billing.adjust(self.w.admin, self.w.adv.pk, -(49_970 - 10), "잔액 10 으로", now=NOW)
        view, _ = records.receive_reaction(decision.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        self.assertEqual(records.process_reaction(view.inbox_id, now=NOW), "ACCEPTED")  # 10 만 받고 20 은 못 받음
        html = self.client.get(URL).content.decode()
        self.assertIn("잔액 <strong>0 포인트</strong> · 오늘 소진 40 포인트", html)
        self.assertEqual(self.rows(html), [("반응 과금", "-10 포인트"), ("관리자 조정", "-49,960 포인트"), ("반응 과금", "-30 포인트"), ("가입 지급", "50,000 포인트")])
        self.assertIn("&lt;b&gt;캠페인&lt;/b&gt;", html)  # 과금 줄의 캠페인 이름(이스케이프)
        self.assertNotIn("<b>캠페인</b>", html)
        self.assertRegex(html, r"<td class=\"num\">20 포인트</td>")  # 못 받은 포인트

    def test_cursor_paging_and_bad_cursors(self):
        for i in range(54):
            billing.adjust(self.w.admin, self.w.adv.pk, 1, f"조정 {i}", now=NOW)
        html = self.client.get(URL).content.decode()
        self.assertEqual(len(self.rows(html)), 50)
        self.assertNotIn("가입 지급", html)
        older = re.search(r'href="([^"]+)" rel="next"', html).group(1).replace("&amp;", "&")
        html = self.client.get(URL + older).content.decode()
        self.assertEqual(len(self.rows(html)), 5)  # 남은 조정 4 + 가입 지급
        self.assertIn("가입 지급", html)
        self.assertIn(f'href="{URL}">처음으로', html)
        self.assertNotIn('rel="next"', html)
        for bad in ("abc", "²", "-1", "9" * 5000):
            self.assertEqual(len(self.rows(self.client.get(URL, {"before": bad}).content.decode())), 50, bad)

    def test_other_advertisers_ledger_never_shows_up(self):
        other = World(ends_in=None)
        campaigns.update_campaign(other.adv, other.campaign.campaign_id, {"name": "남의 캠페인"})
        impression(other, NOW)
        billing.adjust(other.admin, other.adv.pk, 7, "남의 조정", now=NOW)
        html = self.client.get(URL).content.decode()
        self.assertNotIn("남의 캠페인", html)
        self.assertNotIn("남의 조정", html)
        self.assertEqual(self.rows(html), [("가입 지급", "50,000 포인트")])

    def test_an_account_without_a_wallet(self):
        legacy = User.objects.create_user("legacy_points", PW, nickname="옛계정", class_label="1반")
        client = Client()
        client.force_login(legacy)
        self.assertContains(client.get(URL), "지갑이 없습니다")

    def test_the_admin_ledger_shows_campaign_names_too(self):
        impression(self.w, NOW)
        admin = Client()
        admin.force_login(self.w.admin)
        self.assertContains(admin.get(reverse("operator:advertiser_detail", args=[self.w.adv.pk])), "<td>캠페인</td>")

    def test_only_the_advertiser(self):
        self.assertEqual(Client().get(URL).status_code, 302)
        admin = Client()
        admin.force_login(self.w.admin)
        self.assertNotEqual(admin.get(URL).status_code, 200)
