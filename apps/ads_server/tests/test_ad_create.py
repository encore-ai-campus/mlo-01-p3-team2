"""광고 만들기(6-9d, 설계 §10 "광고 만들기 흐름" — Step 3-2c D3-3 을 대체)와 캠페인 만들기.

광고 만들기는 이미 있는 캠페인을 고르고 광고(광고그룹 + 입찰)와 소재(새로 올리기 또는 등록된 소재)를 한 페이지 폼으로 만든다(원자적 `create_ad`).
완료 조건: 원자성, 중복 제출 방지(요청 키 + PRG — 두 번 누름·동시 제출·응답 실패 뒤 재시도), 이미지 거절 사유 표시, 쿼터 초과 안내, 남의 캠페인·소재 거절.
World: 노출 단위 슬롯(하한 10·기준 20·상한 50), 끝나지 않는 캠페인 하나와 그 광고그룹·소재. 서비스는 실제 시계를 쓰므로 끝은 먼 미래로 둔다.
"""
import re
from unittest import mock

from django.test import Client, TestCase, TransactionTestCase, override_settings, tag
from django.urls import reverse

from campaigns import api as campaigns
from campaigns.models import AdGroup, Campaign, Creative
from foundation.models import AuditLog
from masters import api as masters
from tests.concurrency import overlap
from tests.factories import World, make_slot, png_file

URL = reverse("ad_create")
NEW_CAMPAIGN = reverse("campaign_create")


def request_key(html):
    return re.search(r'name="request_key" value="([^"]+)"', html).group(1)


class AdCreateBase:
    def setUp(self):
        self.w = World(ends_in=None)
        self.client.force_login(self.w.adv)
        self.click_slot = make_slot(self.w.admin, unit="CLICK", name="클릭 위치")

    def fields(self, **over):
        """화면이 싣는 요청 키와 함께, 집행할 수 있는 값(새 소재를 올린다)."""
        data = {
            "request_key": request_key(self.client.get(URL).content.decode()), "action": "create", "campaign_id": str(self.w.campaign.campaign_id),
            "pricing_unit": "IMPRESSION", "group_name": "새 그룹", "slot_ids": [str(self.w.slot.slot_id)], "bid_amount": "25",
            "creative_source": "new", "title": "제목", "redirect_url": "https://example.com/new", "image": png_file((10, 20, 30)),
        }
        data.update(over)
        return data

    def created(self):
        return AdGroup.objects.filter(campaign__owner=self.w.adv, name="새 그룹")


@tag("security")
class AdCreatePageTests(AdCreateBase, TestCase):
    def test_page_groups_slots_by_media_and_only_the_chosen_units_slots_are_selectable(self):
        html = self.client.get(URL).content.decode()
        self.assertIn("① 캠페인", html)
        self.assertIn("⑤ 확인 후 집행", html)
        self.assertRegex(html, rf'value="{self.w.slot.slot_id}" data-unit="IMPRESSION" disabled')  # 단위를 고르기 전에는 고를 수 없다
        html = self.client.get(URL, {"unit": "IMPRESSION"}).content.decode()
        self.assertRegex(html, rf'value="{self.w.slot.slot_id}" data-unit="IMPRESSION">')
        self.assertRegex(html, rf'value="{self.click_slot.slot_id}" data-unit="CLICK" disabled')
        self.assertIn("console/ad_create.js", html)
        self.assertRegex(html, r'<button[^>]*value="create"[^>]*data-confirm=')  # 집행 버튼만 확인 창
        self.assertNotRegex(html, r"\sstyle=")

    def test_enter_in_a_field_creates_instead_of_redrawing(self):
        """3-3 브라우저 점검: 칸에서 Enter 를 누르면 폼의 첫 제출 버튼이 눌린다. 그것이 숨긴 '단위 보기'여서 화면만 다시 그리며 고른 이미지를 말없이 잃었다."""
        form = self.client.get(URL).content.decode().split('class="ad-create"', 1)[1]
        first = re.search(r"<button[^>]*>", form).group(0)
        self.assertIn('value="create"', first)
        self.assertIn("data-confirm=", first)  # JS 가 있으면 확인 창
        self.assertIn(" hidden", first)

    def test_choosing_a_unit_without_js_keeps_the_input_and_creates_nothing(self):
        r = self.client.post(URL, self.fields(action="unit", pricing_unit="CLICK", image=""))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertRegex(html, rf'value="{self.click_slot.slot_id}" data-unit="CLICK">')
        self.assertIn('value="새 그룹"', html)
        self.assertNotIn('class="errorlist', html)  # 저장하지 않는 동작이라 오류를 보이지 않는다
        self.assertFalse(self.created().exists())

    def test_preview_shows_what_the_server_computes_per_slot(self):
        cheap = make_slot(self.w.admin, floor=30, base=35, cap=40, name="비싼 하한")
        capped = make_slot(self.w.admin, floor=5, base=10, cap=20, name="낮은 상한")
        r = self.client.post(URL, self.fields(action="preview", image="", slot_ids=[str(self.w.slot.slot_id), str(cheap.slot_id), str(capped.slot_id)]))
        table = r.content.decode().split("지금 정책 기준")[1]
        self.assertRegex(table, r"그대로 적용</td><td class=\"num\">25 포인트")
        self.assertRegex(table, r"하한 미만 — 노출 안 됨</td><td class=\"num\">—")
        self.assertRegex(table, r"상한으로 적용</td><td class=\"num\">20 포인트")
        self.assertFalse(self.created().exists())

    def test_create_makes_the_ad_and_its_creative_in_the_chosen_campaign(self):
        r = self.client.post(URL, self.fields())
        group = self.created().get()
        self.assertRedirects(r, reverse("ad_group_detail", args=[group.ad_group_id]), fetch_redirect_response=False)
        self.assertEqual((group.campaign_id, group.pricing_unit), (self.w.campaign.campaign_id, "IMPRESSION"))
        self.assertEqual((Creative.objects.filter(ad_group_links__ad_group=group).count(), group.creative.title), (1, "제목"))  # 올리고 연결·선택했다
        self.assertEqual(Campaign.objects.filter(owner=self.w.adv).count(), 1)  # 캠페인은 만들지 않는다
        self.assertTrue(AuditLog.objects.filter(action="creative.created", actor_id=self.w.adv.pk).exists())

    def test_a_registered_creative_is_reused(self):
        r = self.client.post(URL, self.fields(creative_source="existing", creative_id=str(self.w.creative.creative_id), title="", redirect_url="", image=""))
        group = self.created().get()
        self.assertRedirects(r, reverse("ad_group_detail", args=[group.ad_group_id]), fetch_redirect_response=False)
        self.assertEqual(group.creative_id, self.w.creative.creative_id)
        self.assertEqual(Creative.objects.filter(owner=self.w.adv).count(), 1)  # 새 소재를 만들지 않았다

    def test_the_campaign_in_the_link_is_preselected_and_only_mine_are_offered(self):
        other = World(ends_in=None)
        html = self.client.get(URL, {"campaign": str(self.w.campaign.campaign_id)}).content.decode()
        self.assertRegex(html, rf'<option value="{self.w.campaign.campaign_id}" selected>')
        self.assertNotIn(str(other.campaign.campaign_id), html)
        self.assertNotIn(str(other.creative.creative_id), html)  # 남의 소재는 고를 수 없다
        for over in ({"campaign_id": str(other.campaign.campaign_id)},
                     {"creative_source": "existing", "creative_id": str(other.creative.creative_id), "image": ""}):  # 위조한 폼
            with self.subTest(over):
                self.assertEqual(self.client.post(URL, self.fields(**over)).status_code, 400)
        self.assertFalse(self.created().exists())

    def test_without_an_open_campaign_the_page_asks_to_make_one_first(self):
        campaigns.end_campaign(self.w.adv, self.w.campaign.campaign_id)
        for response in (self.client.get(URL), self.client.post(URL, {"request_key": "k", "action": "create"})):
            self.assertContains(response, "캠페인을 먼저 만드세요")
            self.assertContains(response, f'href="{NEW_CAMPAIGN}"')
        self.assertFalse(self.created().exists())

    def test_the_same_form_twice_creates_once(self):
        data = self.fields()
        first = self.client.post(URL, data)
        data["image"] = png_file((10, 20, 30))  # 파일은 다시 실어야 한다(브라우저의 다시 보냄과 같다)
        second = self.client.post(URL, data)
        self.assertEqual(self.created().count(), 1)
        self.assertEqual(first["Location"], second["Location"])
        self.assertContains(self.client.get(second["Location"]), "이미 만든 광고입니다")

    def test_errors_are_shown_next_to_the_fields_and_nothing_is_left_behind(self):
        cases = (
            ({"redirect_url": "http://example.com/"}, "redirect_url"),
            ({"slot_ids": [str(self.click_slot.slot_id)]}, "slot_ids"),  # 단위가 다른 위치(화면은 막지만 직접 보낼 수 있다)
            ({"bid_amount": "0"}, "bid_amount"),
            ({"group_name": " "}, "group_name"),  # 서비스 오류 위치 /ad_group/name → 이 칸
            ({"title": " "}, "title"),  # /creative/title → 이 칸
            ({"image": ""}, "image"),  # 새로 올리기인데 이미지가 없다
            ({"creative_source": "existing", "image": ""}, "creative_id"),  # 등록된 소재를 고르지 않았다
        )
        for over, field in cases:
            r = self.client.post(URL, self.fields(**over))
            self.assertEqual(r.status_code, 400, over)
            self.assertIn(f'id="id_{field}_error"', r.content.decode(), over)
        self.assertFalse(self.created().exists())
        self.assertEqual(Creative.objects.filter(owner=self.w.adv).count(), 1)  # 원자성: 광고그룹도 소재도 남지 않는다

    def test_a_rejected_image_shows_the_reason_and_leaves_nothing(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post(URL, self.fields(image=SimpleUploadedFile("x.png", b"not an image", content_type="image/png")))
        self.assertEqual(r.status_code, 400)
        self.assertRegex(r.content.decode(), r'id="id_image_error"><li>[^<]+</li>')  # 거절 사유가 이미지 칸에
        self.assertFalse(self.created().exists())

    def test_a_resubmission_after_the_slot_was_turned_off_still_finds_the_first_ad(self):
        """외부 검토(41d2288) P2: 폼 검증(지금 켜진 위치 목록)이 먼저 돌아 400 이 됐다. 이미 성공한 제출의 다시 보냄은 검증보다 먼저 처음 결과로 간다."""
        data = self.fields()
        first = self.client.post(URL, data)
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        data["image"] = png_file((10, 20, 30))
        second = self.client.post(URL, data)
        self.assertEqual((second.status_code, second["Location"]), (302, first["Location"]))
        self.assertEqual(self.created().count(), 1)

    @override_settings(MAX_AD_GROUPS_PER_ADVERTISER=2)
    def test_a_resubmission_at_the_quota_still_finds_the_first_ad(self):
        """처음 제출로 상한(2)에 닿은 뒤 같은 폼을 다시 보내도 '상한 초과'가 아니라 이미 만든 광고로 간다(만들기 전에 요청 키를 먼저 본다)."""
        data = self.fields()
        first = self.client.post(URL, data)
        data["image"] = png_file((10, 20, 30))
        second = self.client.post(URL, data)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(first["Location"], second["Location"])
        self.assertEqual(self.created().count(), 1)

    @override_settings(MAX_AD_GROUPS_PER_ADVERTISER=1)
    def test_the_quota_is_explained(self):
        r = self.client.post(URL, self.fields())
        self.assertContains(r, "광고그룹 개수 상한에 도달했습니다", status_code=r.status_code)
        self.assertIn(r.status_code, (400, 409, 422))
        self.assertFalse(self.created().exists())

    def test_an_oversized_upload_is_a_readable_page(self):
        r = self.client.post(URL, {}, CONTENT_LENGTH=str(50 * 1024 * 1024))
        self.assertEqual(r.status_code, 413)
        self.assertIn("text/html", r["Content-Type"])
        self.assertContains(r, "이미지는 2MB까지", status_code=413)

    def test_admin_given_names_are_escaped(self):
        make_slot(self.w.admin, name="<b>슬롯</b>")
        html = self.client.get(URL, {"unit": "IMPRESSION"}).content.decode()
        self.assertIn("&lt;b&gt;슬롯&lt;/b&gt;", html)
        self.assertNotIn("<b>슬롯</b>", html)

    def test_inactive_slots_are_not_offered(self):
        masters.set_slot_active(self.w.admin, self.click_slot.slot_id, False)
        self.assertNotIn(str(self.click_slot.slot_id), self.client.get(URL).content.decode())


@tag("security")
class CampaignCreatePageTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.client.force_login(self.w.adv)

    def fields(self, **over):
        data = {"request_key": request_key(self.client.get(NEW_CAMPAIGN).content.decode()), "name": "새 캠페인",
                "starts_at": "2026-10-01T09:00", "ends_at": "2030-12-31T09:00", "daily_budget": "3000"}
        data.update(over)
        return data

    def created(self):
        return Campaign.objects.filter(owner=self.w.adv, name="새 캠페인")

    def test_a_campaign_is_made_alone_and_then_offered_for_ads(self):
        r = self.client.post(NEW_CAMPAIGN, self.fields())
        campaign = self.created().get()
        self.assertRedirects(r, reverse("campaign_detail", args=[campaign.campaign_id]), fetch_redirect_response=False)
        self.assertEqual((campaign.daily_budget, campaign.starts_at.isoformat()), (3000, "2026-10-01T00:00:00+00:00"))  # KST 09:00 = UTC 00:00
        self.assertFalse(AdGroup.objects.filter(campaign=campaign).exists())  # 광고는 따로 만든다
        self.assertContains(self.client.get(r["Location"]), f'{URL}?campaign={campaign.campaign_id}')  # 이 캠페인에 광고 만들기
        self.assertContains(self.client.get(reverse("campaign_list")), f'href="{NEW_CAMPAIGN}"')

    def test_the_same_campaign_form_twice_creates_once(self):
        data = self.fields()
        first = self.client.post(NEW_CAMPAIGN, data)
        second = self.client.post(NEW_CAMPAIGN, data)
        self.assertEqual((self.created().count(), first["Location"]), (1, second["Location"]))
        self.assertContains(self.client.get(second["Location"]), "이미 만든 캠페인입니다")

    def test_campaign_errors_are_shown_next_to_the_fields(self):
        for over, field in (({"name": " "}, "name"), ({"daily_budget": "0"}, "daily_budget"), ({"ends_at": "2020-01-01T09:00"}, "ends_at")):
            r = self.client.post(NEW_CAMPAIGN, self.fields(**over))
            self.assertContains(r, f'id="id_{field}_error"', status_code=400)
        self.assertFalse(self.created().exists())

    def test_a_time_kst_cannot_express_is_a_field_error_not_a_500(self):
        """외부 검토(41d2288) P2: 0001-01-01T00:00 KST 는 UTC 로 바꿀 수 없어 500 이었다(6-9d 부터 시작 시각은 캠페인 만들기 화면에 있다)."""
        r = self.client.post(NEW_CAMPAIGN, self.fields(starts_at="0001-01-01T00:00"))
        self.assertContains(r, 'id="id_starts_at_error"', status_code=400)
        self.assertFalse(self.created().exists())
        self.assertEqual(self.client.post(NEW_CAMPAIGN, self.fields(starts_at="0001-01-01T09:00")).status_code, 302)  # 바로 위 경계(UTC 0001-01-01 00:00)는 정상 값

    @override_settings(MAX_CAMPAIGNS_PER_ADVERTISER=1)
    def test_the_campaign_quota_is_explained(self):
        self.assertContains(self.client.post(NEW_CAMPAIGN, self.fields()), "캠페인 개수 상한에 도달했습니다", status_code=409)
        self.assertFalse(self.created().exists())


@tag("security")
class AdCreateOnceTests(AdCreateBase, TransactionTestCase):
    """같은 폼을 동시에 두 번 보내거나, 만든 뒤 응답이 실패해 다시 보내도 광고는 하나다(요청 키가 광고그룹 행에 같은 트랜잭션으로 저장된다)."""

    def setUp(self):
        self.client = Client()
        super().setUp()

    def twin(self, **kwargs):
        other = Client(**kwargs)
        other.cookies = self.client.cookies
        return other

    def test_the_same_form_sent_twice_at_once_creates_once(self):
        data = self.fields()
        data2 = {**data, "image": png_file((10, 20, 30))}
        # 첫째는 광고그룹을 쓰기 직전에 멈추고, 둘째는 광고주 잠금에서 기다렸다가(같은 광고주의 만들기는 줄을 선다) 잠금 안에서 키를 다시 보고 처음 결과로 간다
        first, second = overlap(self, lambda: self.client.post(URL, data), "INSERT", "campaigns_ad_group", lambda: self.twin().post(URL, data2))
        self.assertEqual((first.errors, second.errors), ([], []))
        self.assertEqual((first.result.status_code, second.result.status_code), (302, 302))
        self.assertEqual(first.result["Location"], second.result["Location"])
        self.assertEqual(self.created().count(), 1)

    def test_a_retry_after_the_response_failed_post_commit_creates_once(self):
        data = self.fields()
        failing = self.twin(raise_request_exception=False)
        with mock.patch("console.views.ads.messages.success", side_effect=RuntimeError("응답 실패")):
            self.assertEqual(failing.post(URL, data).status_code, 500)  # 만들었고 응답만 실패
        self.assertEqual(self.created().count(), 1)
        data["image"] = png_file((10, 20, 30))
        self.assertEqual(self.client.post(URL, data).status_code, 302)
        self.assertEqual(self.created().count(), 1)
