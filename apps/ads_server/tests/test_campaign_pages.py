"""Step 3-2b 광고주 캠페인 화면: 목록(상태·켜기/끄기·오늘 소진·최근 성과), 상세(수정·끝내기·중단 사유와 재검토 요청·광고그룹).

완료 조건(계획 3-2b): 끝난·중단된 캠페인의 규칙은 **서비스 오류로만** 화면에 보인다(뷰에 규칙 없음), 남의 캠페인은 404.
서비스는 실제 시계를 쓰므로 끝 시각은 먼 미래로 둔다. 목록의 성과·오늘 소진만 화면 시계(`_now`)를 `NOW` 로 고정해 본다.
"""
import re
from datetime import datetime, timezone
from unittest import mock

from django.test import TestCase, tag
from django.urls import reverse

from campaigns import api as campaigns
from campaigns.models import Campaign
from foundation.models import AuditLog
from tests.factories import DAY, NOW, World, impression


@tag("security")
class CampaignPagesBase(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.cid = self.w.campaign.campaign_id
        self.client.force_login(self.w.adv)
        self.list = reverse("campaign_list")
        self.detail = reverse("campaign_detail", args=[self.cid])

    def view(self):
        return campaigns.get_campaign(self.w.adv, self.cid)

    def edit_fields(self, **over):
        """상세 화면의 수정 폼이 싣는 값(화면이 본 마지막 변경 시각 포함)."""
        html = self.client.get(self.detail).content.decode()
        fields = dict(re.findall(r'name="(name|daily_budget|ends_at|updated_at)"[^>]*?value="([^"]*)"', html))
        fields.setdefault("ends_at", "")
        return {**fields, **over}

    def flash(self):
        return self.client.get(self.detail).content.decode()


class CampaignListTests(CampaignPagesBase):
    def test_lists_own_campaigns_with_status_today_and_recent_numbers(self):
        Campaign.objects.filter(pk=self.cid).update(starts_at=NOW - 30 * DAY)
        impression(self.w, NOW)
        other = World(ends_in=None)
        with mock.patch("console.views.campaigns._now", return_value=NOW):
            html = self.client.get(self.list).content.decode()
        self.assertIn(self.detail, html)
        self.assertNotIn(str(other.campaign.campaign_id), html)  # 남의 캠페인은 없다
        row = re.search(rf'<a href="{re.escape(self.detail)}">.*?</tr>', html, re.S).group(0)
        self.assertIn("집행 중", row)
        self.assertIn("끄기", row)
        self.assertRegex(row, r'<td class="num">294 포인트</td>\s*<td class="num">1</td>')  # 오늘 소진 294(입찰 300 × 노출 98%) · 최근 7일 노출 1

    def test_a_suspended_campaign_has_no_toggle_and_shows_the_reason_escaped(self):
        campaigns.update_campaign(self.w.adv, self.cid, {"name": "<b>캠페인</b>"})
        campaigns.suspend_campaign(self.w.admin, self.cid, "<script>x</script>")
        html = self.client.get(self.list).content.decode()
        self.assertIn("관리자 중단", html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)
        self.assertNotIn("<script>x</script>", html)
        self.assertNotIn("<b>캠페인</b>", html)
        self.assertNotIn(reverse("campaign_status", args=[self.cid]), html)


class ToggleTests(CampaignPagesBase):
    def test_off_and_on(self):
        url = reverse("campaign_status", args=[self.cid])
        self.assertRedirects(self.client.post(url, {"status": "PAUSED", "back": "list"}), self.list)
        self.assertEqual(self.view().status, "PAUSED")
        self.assertRedirects(self.client.post(url, {"status": "ACTIVE"}), self.detail)
        self.assertEqual(self.view().status, "ACTIVE")
        self.assertRedirects(self.client.post(url, {"status": "ACTIVE", "back": "https://evil.example/"}), self.detail)  # 정한 곳으로만

    def test_rules_come_from_the_service(self):
        """중단된 캠페인을 켜려는 제출(화면에는 버튼이 없지만 직접 보낼 수 있다)은 서비스가 거절하고 화면은 그 오류를 보일 뿐이다."""
        campaigns.suspend_campaign(self.w.admin, self.cid, "사유")
        self.client.post(reverse("campaign_status", args=[self.cid]), {"status": "ACTIVE"})
        self.assertEqual(self.view().status, "SUSPENDED")
        self.assertIn('class="notice error"', self.flash())
        self.client.post(reverse("campaign_status", args=[self.cid]), {"status": "ENDED"})  # 광고주가 고를 수 없는 상태
        self.assertEqual(self.view().status, "SUSPENDED")


class EditTests(CampaignPagesBase):
    def test_only_changed_fields_are_sent_and_kst_input_becomes_utc(self):
        r = self.client.post(self.detail, self.edit_fields(daily_budget="7000", ends_at="2099-12-31T09:00"))
        self.assertRedirects(r, self.detail)
        view = self.view()
        self.assertEqual((view.daily_budget, view.ends_at), (7000, datetime(2099, 12, 31, 0, 0, tzinfo=timezone.utc)))  # KST 09:00 = UTC 00:00
        self.assertEqual(AuditLog.objects.filter(action="campaign.updated").latest("created_at").detail["changed"], ["daily_budget", "ends_at"])
        self.assertIn('value="2099-12-31T09:00"', self.client.get(self.detail).content.decode())  # 다시 KST 로 보인다

    def test_a_stale_form_does_not_overwrite_a_change_made_elsewhere(self):
        fields = self.edit_fields(daily_budget="7000")  # 이 탭은 폼을 열어 둔 채
        campaigns.update_campaign(self.w.adv, self.cid, {"name": "다른 탭에서 바꾼 이름"})
        r = self.client.post(self.detail, fields)
        self.assertContains(r, "다른 곳에서 먼저 바뀌었습니다", status_code=409)
        view = self.view()
        self.assertEqual((view.name, view.daily_budget), ("다른 탭에서 바꾼 이름", 50_000))  # 옛 이름으로 되돌리지 않았다

    def test_service_rules_are_shown_next_to_the_fields(self):
        r = self.client.post(self.detail, self.edit_fields(ends_at="2020-01-01T09:00"))
        self.assertContains(r, "종료 시각은 시작보다 뒤이고 지금보다 뒤여야 합니다", status_code=400)
        self.assertContains(self.client.post(self.detail, self.edit_fields(daily_budget="abc")), "daily_budget", status_code=400)
        self.assertIsNone(self.view().ends_at)

    def test_time_edges_are_field_errors_not_500(self):
        """외부 검토(41d2288) P2: KST 로 읽은 0001-01-01T00:00 은 UTC 로 표현할 수 없어 500 이었다. 위쪽 끝은 정상 값이다."""
        self.assertContains(self.client.post(self.detail, self.edit_fields(ends_at="0001-01-01T00:00")), 'id="id_ends_at_error"', status_code=400)
        self.assertIsNone(self.view().ends_at)
        self.assertRedirects(self.client.post(self.detail, self.edit_fields(ends_at="9999-12-31T23:59")), self.detail)
        self.assertEqual(self.view().ends_at, datetime(9999, 12, 31, 14, 59, tzinfo=timezone.utc))

    def test_nothing_changed(self):
        """화면은 분 단위라, 초가 있는 끝 시각을 그대로 내도 '바뀌지 않음'이다(끝 시각을 분으로 잘라 몰래 바꾸지 않는다)."""
        campaigns.update_campaign(self.w.adv, self.cid, {"ends_at": datetime(2099, 12, 31, 0, 0, 30, tzinfo=timezone.utc)})
        self.assertRedirects(self.client.post(self.detail, self.edit_fields()), self.detail, fetch_redirect_response=False)
        self.assertIn("바뀐 것이 없습니다", self.flash())
        self.assertEqual(self.view().ends_at, datetime(2099, 12, 31, 0, 0, 30, tzinfo=timezone.utc))


class EndTests(CampaignPagesBase):
    def test_ending_is_confirmed_final_and_hides_the_forms(self):
        html = self.client.get(self.detail).content.decode()
        self.assertRegex(html, r'<form[^>]*/end"[^>]*data-confirm="[^"]*되돌릴 수 없습니다')
        self.assertIn("console/confirm.js", html)
        self.client.post(reverse("campaign_end", args=[self.cid]))
        self.assertEqual(self.view().status, "ENDED")
        html = self.flash()
        self.assertNotIn(reverse("campaign_end", args=[self.cid]), html)
        self.assertNotIn('name="daily_budget"', html)
        self.assertEqual(self.client.post(reverse("campaign_end", args=[self.cid])).status_code, 302)  # 두 번째는 서비스 오류를 보일 뿐(500 아님)
        r = self.client.post(self.detail, {"name": "x", "daily_budget": "1", "ends_at": "", "updated_at": self.view().updated_at.isoformat()})
        self.assertIn(r.status_code, (400, 409))  # 끝난 캠페인은 서비스가 수정을 거절한다
        self.assertEqual(self.view().daily_budget, 50_000)


class SuspensionTests(CampaignPagesBase):
    def test_reason_review_request_and_its_answer(self):
        campaigns.suspend_campaign(self.w.admin, self.cid, "<i>부적절한</i> 이동 주소")
        html = self.client.get(self.detail).content.decode()
        self.assertIn("&lt;i&gt;부적절한&lt;/i&gt; 이동 주소", html)
        self.assertIn(reverse("campaign_review", args=[self.cid]), html)
        self.assertRedirects(self.client.post(reverse("campaign_review", args=[self.cid]), {"message": "고쳤습니다"}), self.detail, fetch_redirect_response=False)
        html = self.flash()
        self.assertIn("재검토를 요청했습니다", html)
        self.assertNotIn(reverse("campaign_review", args=[self.cid]), html)  # 열린 요청이 있으면 버튼이 없다
        self.client.post(reverse("campaign_review", args=[self.cid]), {"message": "또"})  # 직접 다시 보내면 서비스가 거절
        self.assertEqual(len(campaigns.list_review_requests(self.w.adv, self.cid)), 1)
        (review,) = campaigns.list_review_requests(self.w.adv, self.cid)
        campaigns.reject_review_request(self.w.admin, review.review_request_id, "<b>여전히</b> 같습니다")
        html = self.client.get(self.detail).content.decode()
        self.assertIn("반려됨", html)
        self.assertIn("&lt;b&gt;여전히&lt;/b&gt; 같습니다", html)


class AdGroupTableTests(CampaignPagesBase):
    def test_groups_with_bid_and_placement_summary(self):
        campaigns.add_bid(self.w.adv, self.w.group.ad_group_id, 600, expected_version=1)  # 상한 500 초과
        html = self.client.get(self.detail).content.decode()
        table = html[html.index('aria-label="광고"'):]
        self.assertIn("600 포인트", table)
        self.assertIn("노출 가능 1곳 · 상한 적용 1곳", table)


class IsolationTests(CampaignPagesBase):
    def test_other_advertisers_campaign_is_404_everywhere_and_nothing_changes(self):
        other = World(ends_in=None)
        oid = other.campaign.campaign_id
        self.assertEqual(self.client.get(reverse("campaign_detail", args=[oid])).status_code, 404)
        for name, data in (("campaign_status", {"status": "PAUSED"}), ("campaign_end", {}), ("campaign_review", {"message": "x"})):
            self.assertEqual(self.client.post(reverse(name, args=[oid]), data).status_code, 404, name)
        self.assertEqual(self.client.post(reverse("campaign_detail", args=[oid]), {"name": "x", "daily_budget": "1", "updated_at": "2026-01-01T00:00:00+00:00"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("campaign_detail", args=["not-a-uuid"])).status_code, 404)
        view = campaigns.get_campaign(other.adv, oid)
        self.assertEqual((view.status, view.name, view.daily_budget), ("ACTIVE", "캠페인", 50_000))
