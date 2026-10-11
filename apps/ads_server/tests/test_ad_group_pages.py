"""Step 3-2d 광고그룹 상세: 위치별 결과, 입찰 이력과 새 입찰(낙관적 잠금 충돌 안내), 이름·위치·켜기/끄기, 소재(본인 이미지·제목/주소·켜기/끄기·이미지 교체).

완료 조건(계획 3-2d): 입찰은 추가만, 충돌 안내, 교체한 과거 이미지 보유 규칙은 서비스 그대로. 동작마다 작은 폼이라 한 칸의 제출이 다른 칸을 덮지 않는다.
World: 노출 단위 슬롯(하한 10·기준 20·상한 50), 입찰 30.
"""
import re

from django.test import Client, TestCase, override_settings, tag
from django.urls import reverse

from campaigns import api as campaigns
from campaigns.models import CreativeImage
from masters import api as masters
from tests.factories import World, make_slot, png_file


@tag("security")
class AdGroupPageBase(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.gid = self.w.group.ad_group_id
        self.crid = self.w.creative.creative_id
        self.client.force_login(self.w.adv)
        self.detail = reverse("ad_group_detail", args=[self.gid])

    def html(self):
        return self.client.get(self.detail).content.decode()

    def group(self):
        return campaigns.get_ad_group(self.w.adv, self.gid)

    def creative(self):
        return campaigns.get_creative(self.w.adv, self.crid)

    def edit_fields(self, **over):
        prefix = str(self.crid)
        html = self.html()
        found = dict(re.findall(rf'name="{prefix}-(title|redirect_url|updated_at)"[^>]*?value="([^"]*)"', html))
        return {f"{prefix}-{k}": v for k, v in {**found, **over}.items()}


class DetailTests(AdGroupPageBase):
    def test_shows_bid_effects_history_slots_and_the_creative(self):
        html = self.html()
        self.assertIn("만든 뒤에는 바꿀 수 없습니다", html)  # 과금 단위 불변 안내
        self.assertIn("현재 입찰 <strong>30 포인트</strong>", html)
        self.assertRegex(html, r"그대로 적용</td>\s*<td class=\"num\">30 포인트")
        self.assertIn(reverse("creative_image_file", args=[self.crid]), html)
        self.assertIn("<strong>example.com</strong>", html)
        self.assertRegex(html, rf'value="{self.w.slot.slot_id}" checked')

    def test_user_text_is_escaped(self):
        campaigns.update_ad_group(self.w.adv, self.gid, {"name": "<b>그룹</b>"})
        campaigns.update_creative(self.w.adv, self.crid, {"title": "<script>x</script>"})
        html = self.html()
        self.assertNotIn("<b>그룹</b>", html)
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)


class BidTests(AdGroupPageBase):
    def test_a_new_bid_is_added_as_a_new_version(self):
        self.assertRedirects(self.client.post(reverse("ad_group_bid", args=[self.gid]), {"amount": 60, "expected_version": 1}), self.detail)
        self.assertEqual([b.amount for b in campaigns.list_bids(self.w.adv, self.gid)], [60, 30])  # 추가만
        html = self.html()
        self.assertRegex(html, r"상한으로 적용</td>\s*<td class=\"num\">50 포인트")
        self.assertRegex(html, r'name="expected_version" value="2"')

    def test_a_concurrent_bid_is_explained_and_nothing_is_overwritten(self):
        campaigns.add_bid(self.w.adv, self.gid, 40, expected_version=1)  # 다른 탭에서 먼저
        r = self.client.post(reverse("ad_group_bid", args=[self.gid]), {"amount": 60, "expected_version": 1})
        self.assertContains(r, "현재 버전은 2", status_code=409)
        self.assertEqual([b.amount for b in campaigns.list_bids(self.w.adv, self.gid)], [40, 30])

    def test_bad_amount_and_ended_campaign_are_refused_by_the_service(self):
        self.assertEqual(self.client.post(reverse("ad_group_bid", args=[self.gid]), {"amount": 0, "expected_version": 1}).status_code, 400)
        campaigns.end_campaign(self.w.adv, self.w.campaign.campaign_id)
        r = self.client.post(reverse("ad_group_bid", args=[self.gid]), {"amount": 60, "expected_version": 1})
        self.assertIn(r.status_code, (400, 409))
        self.assertEqual(len(campaigns.list_bids(self.w.adv, self.gid)), 1)


class GroupEditTests(AdGroupPageBase):
    def test_name_slots_and_toggle_are_separate_and_do_not_touch_each_other(self):
        other_slot = make_slot(self.w.admin, name="둘째 위치")
        self.client.post(reverse("ad_group_slots", args=[self.gid]), {"slot_ids": [str(self.w.slot.slot_id), str(other_slot.slot_id)]})
        self.assertEqual(set(self.group().slot_ids), {self.w.slot.slot_id, other_slot.slot_id})
        self.client.post(reverse("ad_group_name", args=[self.gid]), {"name": "새 이름"})
        self.client.post(reverse("ad_group_enabled", args=[self.gid]), {"enabled": "0"})
        group = self.group()
        self.assertEqual((group.name, group.enabled, len(group.slot_ids)), ("새 이름", False, 2))  # 앞의 변경이 남아 있다

    def test_slot_rules_are_shown(self):
        click = make_slot(self.w.admin, unit="CLICK", name="클릭 위치")
        self.assertNotIn(str(click.slot_id), self.html())  # 단위가 다른 위치는 고를 수 없다
        self.assertEqual(self.client.post(reverse("ad_group_slots", args=[self.gid]), {"slot_ids": [str(click.slot_id)]}).status_code, 400)
        r = self.client.post(reverse("ad_group_slots", args=[self.gid]), {})
        self.assertContains(r, "게재 위치를 하나 이상 고르세요", status_code=400)
        self.assertEqual(self.group().slot_ids, (self.w.slot.slot_id,))

    def test_an_inactive_linked_slot_is_explained(self):
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        html = self.html()
        self.assertIn("지금 꺼진 위치", html)
        self.assertIn("꺼진 위치 — 노출 안 됨", html)


class CreativeTests(AdGroupPageBase):
    def test_edit_only_what_changed(self):
        self.assertRedirects(self.client.post(reverse("creative_edit", args=[self.crid]), self.edit_fields(title="새 제목")), self.detail)
        creative = self.creative()
        self.assertEqual((creative.title, creative.redirect_url), ("새 제목", "https://example.com/landing"))

    def test_a_stale_edit_does_not_revert_an_image_replaced_elsewhere(self):
        fields = self.edit_fields(title="새 제목")
        new = campaigns.replace_creative_image(self.w.adv, self.crid, png_file((1, 2, 3)))  # 다른 탭에서
        r = self.client.post(reverse("creative_edit", args=[self.crid]), fields)
        self.assertContains(r, "다른 곳에서 먼저 바뀌었습니다", status_code=409)
        self.assertEqual((self.creative().title, self.creative().image_name), ("제목", new.image_name))

    def test_service_rules_next_to_the_field(self):
        r = self.client.post(reverse("creative_edit", args=[self.crid]), self.edit_fields(redirect_url="http://example.com/"))
        self.assertContains(r, f'id="id_{self.crid}-redirect_url_error"', status_code=400)
        self.assertEqual(self.creative().redirect_url, "https://example.com/landing")

    def test_toggle_and_image_replacement_keeps_the_old_file(self):
        old = self.creative().image_name
        self.client.post(reverse("creative_enabled", args=[self.crid]), {"enabled": "0"})
        self.assertFalse(self.creative().enabled)
        self.assertRedirects(self.client.post(reverse("creative_image", args=[self.crid]), {"image": png_file((5, 6, 7))}), self.detail)
        self.assertNotEqual(self.creative().image_name, old)
        self.assertEqual(set(CreativeImage.objects.filter(creative_id=self.crid).values_list("image_name", flat=True)), {old, self.creative().image_name})

    def test_a_rejected_image_shows_the_reason(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post(reverse("creative_image", args=[self.crid]), {"image": SimpleUploadedFile("x.png", b"nope", content_type="image/png")})
        self.assertEqual(r.status_code, 400)
        self.assertRegex(r.content.decode(), r'id="id_image_error"><li>[^<]+</li>')

    @override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable")
    def test_the_owner_sees_the_image_while_suspended_and_nobody_else_does(self):
        campaigns.suspend_campaign(self.w.admin, self.w.campaign.campaign_id, "사유")
        own = reverse("creative_image_file", args=[self.crid])
        r = self.client.get(own)
        self.assertEqual((r.status_code, r["Content-Type"], r["X-Content-Type-Options"]), (200, "image/png", "nosniff"))
        self.assertIn("no-store", r["Cache-Control"])
        self.assertEqual(Client().get(reverse("asset", args=[self.creative().image_name])).status_code, 404)  # 공개 경로는 막힌다
        other = Client()
        other.force_login(World(ends_in=None).adv)
        self.assertEqual(other.get(own).status_code, 404)
        self.assertNotEqual(Client().get(own).status_code, 200)


class IsolationTests(AdGroupPageBase):
    def test_other_advertisers_group_and_creative_are_404_everywhere(self):
        other = World(ends_in=None)
        gid, crid = other.group.ad_group_id, other.creative.creative_id
        self.assertEqual(self.client.get(reverse("ad_group_detail", args=[gid])).status_code, 404)
        posts = (("ad_group_bid", gid, {"amount": 1, "expected_version": 1}), ("ad_group_name", gid, {"name": "x"}),
                 ("ad_group_slots", gid, {"slot_ids": [str(other.slot.slot_id)]}), ("ad_group_enabled", gid, {"enabled": "0"}),
                 ("creative_edit", crid, {}), ("creative_enabled", crid, {"enabled": "0"}), ("creative_image", crid, {"image": png_file()}))
        for name, target, data in posts:
            self.assertEqual(self.client.post(reverse(name, args=[target]), data).status_code, 404, name)
        self.assertEqual(self.client.get(reverse("creative_image_file", args=[crid])).status_code, 404)
        group = campaigns.get_ad_group(other.adv, gid)
        self.assertEqual((group.name, group.enabled, group.current_bid.amount), ("그룹", True, 30))
        self.assertTrue(campaigns.get_creative(other.adv, crid).enabled)
