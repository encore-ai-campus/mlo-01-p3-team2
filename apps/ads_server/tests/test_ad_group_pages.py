"""Step 3-2d 광고 상세(광고그룹): 구성별 결과, 입찰 이력과 새 입찰(낙관적 잠금 충돌 안내), 이름·구성·켜기/끄기, 이미지 고르기·올리기(6-11).
소재의 제목·주소 수정과 이미지 교체는 소재 상세에서만 한다(시험은 `test_creative_pages`).

완료 조건(계획 3-2d): 입찰은 추가만, 충돌 안내. 동작마다 작은 폼이라 한 칸의 제출이 다른 칸을 덮지 않는다.
World: 구성(하한 100·기준 200·상한 500, 노출 98%), 입찰 300.
"""
import re
from unittest import mock

from django.test import TestCase, tag
from django.urls import reverse

from campaigns import api as campaigns
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

    def seen(self):
        """화면이 싣는 광고그룹의 마지막 변경 시각."""
        return self.group().updated_at.isoformat()


class DetailTests(AdGroupPageBase):
    def test_shows_bid_effects_history_slots_and_the_creative(self):
        html = self.html()
        self.assertIn(f'<a href="{reverse("campaign_detail", args=[self.w.campaign.campaign_id])}">← 캠페인</a>', html)  # 속한 캠페인으로
        self.assertIn("현재 입찰 <strong>300 포인트</strong>", html)
        self.assertRegex(html, r"그대로 적용</td>\s*<td class=\"num\">300 포인트</td>\s*<td>노출 294 · 클릭 3 · 전환 3</td>")  # 위치별 예상 과금(6-10d)
        self.assertIn("노출 98% · 클릭 1% · 전환 1%", html)  # 고를 수 있는 위치의 비율
        self.assertIn(reverse("creative_image_file", args=[self.crid]), html)
        self.assertIn("<strong>example.com</strong>", html)
        self.assertRegex(html, rf'value="{self.w.slot.slot_id}" checked')
        campaigns.add_bid(self.w.adv, self.gid, 350, 1)
        self.assertRegex(self.html(), r'(?s)입찰 변경 이력</caption>.*?<td class="num">2</td><td class="num">350 포인트</td>.*?<td class="num">1</td><td class="num">300 포인트</td>')  # 최신부터

    def test_the_page_reads_slot_policies_once(self):
        """계획 3-4g B1: 위치 정보와 위치별 결과가 같은 읽기를 본다(전에는 슬롯 정책을 두 번 읽었다)."""
        with mock.patch.object(masters, "get_slots_with_policy", wraps=masters.get_slots_with_policy) as read:
            self.html()
        self.assertEqual(read.call_count, 1)

    def test_user_text_is_escaped(self):
        campaigns.update_ad_group(self.w.adv, self.gid, {"name": "<b>그룹</b>"})
        campaigns.update_creative(self.w.adv, self.crid, {"title": "<script>x</script>"})
        html = self.html()
        self.assertNotIn("<b>그룹</b>", html)
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)


class BidTests(AdGroupPageBase):
    def test_a_new_bid_is_added_as_a_new_version(self):
        self.assertRedirects(self.client.post(reverse("ad_group_bid", args=[self.gid]), {"amount": 600, "expected_version": 1}), self.detail)
        self.assertEqual([b.amount for b in campaigns.list_bids(self.w.adv, self.gid)], [600, 300])  # 추가만
        html = self.html()
        self.assertRegex(html, r"상한으로 적용</td>\s*<td class=\"num\">500 포인트")
        self.assertRegex(html, r'name="expected_version" value="2"')

    def test_a_concurrent_bid_is_explained_and_nothing_is_overwritten(self):
        campaigns.add_bid(self.w.adv, self.gid, 400, expected_version=1)  # 다른 탭에서 먼저
        r = self.client.post(reverse("ad_group_bid", args=[self.gid]), {"amount": 600, "expected_version": 1})
        self.assertContains(r, "다른 곳에서 먼저 바뀌었습니다(현재 버전 2)", status_code=409)  # 다른 낙관적 잠금 충돌과 같은 안내
        self.assertEqual([b.amount for b in campaigns.list_bids(self.w.adv, self.gid)], [400, 300])

    def test_bad_amount_and_ended_campaign_are_refused_by_the_service(self):
        self.assertEqual(self.client.post(reverse("ad_group_bid", args=[self.gid]), {"amount": 0, "expected_version": 1}).status_code, 400)
        campaigns.end_campaign(self.w.adv, self.w.campaign.campaign_id)
        r = self.client.post(reverse("ad_group_bid", args=[self.gid]), {"amount": 600, "expected_version": 1})
        self.assertIn(r.status_code, (400, 409))
        self.assertEqual(len(campaigns.list_bids(self.w.adv, self.gid)), 1)


class GroupEditTests(AdGroupPageBase):
    def test_name_slots_and_toggle_are_separate_and_do_not_touch_each_other(self):
        other_slot = make_slot(self.w.admin, name="둘째 위치")
        self.client.post(reverse("ad_group_slots", args=[self.gid]), {"slot_ids": [str(self.w.slot.slot_id), str(other_slot.slot_id)], "updated_at": self.seen()})
        self.assertEqual(set(self.group().slot_ids), {self.w.slot.slot_id, other_slot.slot_id})
        self.client.post(reverse("ad_group_name", args=[self.gid]), {"name": "새 이름", "updated_at": self.seen()})
        self.client.post(reverse("ad_group_enabled", args=[self.gid]), {"enabled": "0"})
        group = self.group()
        self.assertEqual((group.name, group.enabled, len(group.slot_ids)), ("새 이름", False, 2))  # 앞의 변경이 남아 있다

    def test_slot_rules_are_shown(self):
        click = make_slot(self.w.admin, unit="CLICK", name="클릭 위치")
        self.assertIn(str(click.slot_id), self.html())  # 과금 단위가 없어 비율이 다른 위치도 고를 수 있다(6-10d)
        masters.set_slot_active(self.w.admin, click.slot_id, False)
        self.assertNotIn(str(click.slot_id), self.html())  # 꺼진 위치는 고를 수 없다
        self.assertEqual(self.client.post(reverse("ad_group_slots", args=[self.gid]), {"slot_ids": [str(click.slot_id)], "updated_at": self.seen()}).status_code, 400)
        r = self.client.post(reverse("ad_group_slots", args=[self.gid]), {"updated_at": self.seen()})
        self.assertContains(r, "구성을 하나 이상 고르세요", status_code=400)
        self.assertEqual(self.group().slot_ids, (self.w.slot.slot_id,))

    def test_an_inactive_linked_slot_is_explained(self):
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        html = self.html()
        self.assertIn("지금 꺼진 구성", html)
        self.assertIn("꺼진 구성 — 노출 안 됨", html)


class ImageSectionTests(AdGroupPageBase):
    def test_the_image_section_only_selects_and_the_upload_section_only_uploads(self):
        """6-11(사용자 요청): 광고 상세의 "이미지"는 내 이미지(보관하지 않은 것 전부) 중 하나를 고르기만 하고, "이미지 업로드"는 올리기만 한다.
        제목·주소 수정과 이미지 교체는 소재 상세에만 있다."""
        mine = campaigns.create_creative(self.w.adv, None, "목록의 이미지", "https://example.com/2", png_file((9, 9, 9)))  # 아직 이 광고에 연결되지 않음
        gone = campaigns.create_creative(self.w.adv, None, "지운 이미지", "https://example.com/3", png_file((8, 8, 8)))
        campaigns.archive_creative(self.w.adv, gone.creative_id)
        html = self.html()
        image, upload = html.split('aria-label="이미지"', 1)[1].split('aria-label="이미지 업로드"', 1)
        self.assertNotIn("소재 더하기", html)
        self.assertEqual(re.findall(r'name="creative_id" value="([^"]+)"', image), [str(mine.creative_id)])  # 나가는 중인 것은 버튼이 없고, 지운 것은 보이지 않는다
        self.assertIn("나가는 중", image)
        self.assertIn('aria-label="이 이미지로 바꾸기: 목록의 이미지"', image)  # 이미지마다 버튼 이름이 다르다(R8)
        self.assertNotIn("지운 이미지", image)
        self.assertNotIn(f'action="{reverse("creative_edit", args=[self.crid])}"', html)  # 이 화면에서는 고치지 않는다
        self.assertNotIn(f'action="{reverse("creative_image", args=[self.crid])}"', html)
        self.assertEqual(re.findall(r'<input type="file"[^>]*name="([^"]+)"', html), ["new-image"])  # 파일 칸은 올리기 하나
        self.assertNotIn('name="creative_id"', upload)

        self.assertRedirects(self.client.post(reverse("ad_group_creative_select", args=[self.gid]), {"creative_id": str(mine.creative_id)}), self.detail)
        self.assertEqual(self.group().creative_id, mine.creative_id)  # 연결되지 않았던 것도 고르면 연결과 선택이 함께
        self.assertIn(mine.creative_id, {c.creative_id for c in campaigns.list_creatives(self.w.adv, self.gid)})

        r = self.client.post(reverse("ad_group_creative_upload", args=[self.gid]),
                             {"new-title": "새 이미지", "new-redirect_url": "https://example.com/new", "new-image": png_file((7, 7, 7))})
        self.assertRedirects(r, self.detail)
        uploaded = next(o.creative for o in campaigns.list_owned_creatives(self.w.adv) if o.creative.title == "새 이미지")
        self.assertEqual(self.group().creative_id, mine.creative_id)  # 올리기만 한다 — 선택은 그대로
        self.assertNotIn(uploaded.creative_id, {c.creative_id for c in campaigns.list_creatives(self.w.adv, self.gid)})  # 연결도 하지 않는다
        self.assertIn(f'value="{uploaded.creative_id}"', self.html().split('aria-label="이미지 업로드"', 1)[0])  # 위 목록에서 고를 수 있다


    def test_a_refused_choice_says_why_and_keeps_the_image(self):
        """R13(6-13d): 고르기가 거절되면(끝난 캠페인) 이유를 알리고, 나가는 이미지는 그대로다."""
        mine = campaigns.create_creative(self.w.adv, None, "목록의 이미지", "https://example.com/2", png_file((9, 9, 9)))
        campaigns.end_campaign(self.w.adv, self.w.campaign.campaign_id)
        r = self.client.post(reverse("ad_group_creative_select", args=[self.gid]), {"creative_id": str(mine.creative_id)}, follow=True)
        self.assertRedirects(r, self.detail)
        self.assertContains(r, "종료된 캠페인은 수정할 수 없습니다")
        self.assertEqual(self.group().creative_id, self.crid)


class IsolationTests(AdGroupPageBase):
    def test_other_advertisers_group_and_creative_are_404_everywhere(self):
        other = World(ends_in=None)
        gid, crid = other.group.ad_group_id, other.creative.creative_id
        self.assertEqual(self.client.get(reverse("ad_group_detail", args=[gid])).status_code, 404)
        posts = (("ad_group_bid", gid, {"amount": 1, "expected_version": 1}), ("ad_group_name", gid, {"name": "x"}),
                 ("ad_group_slots", gid, {"slot_ids": [str(other.slot.slot_id)]}), ("ad_group_enabled", gid, {"enabled": "0"}),
                 ("creative_edit", crid, {}), ("creative_image", crid, {"image": png_file()}),
                 ("ad_group_creative_upload", gid, {"new-title": "남의 화면", "new-redirect_url": "https://example.com/x", "new-image": png_file()}))
        for name, target, data in posts:
            self.assertEqual(self.client.post(reverse(name, args=[target]), data).status_code, 404, name)
        self.assertEqual(self.client.get(reverse("creative_image_file", args=[crid])).status_code, 404)
        group = campaigns.get_ad_group(other.adv, gid)
        self.assertEqual((group.name, group.enabled, group.current_bid.amount), ("그룹", True, 300))
        self.assertEqual(campaigns.get_creative(other.adv, crid).title, "제목")
        self.assertEqual([o.creative.title for o in campaigns.list_owned_creatives(self.w.adv)], ["제목"])  # 남의 광고 화면으로는 올라가지 않는다
        self.assertEqual(self.client.post(reverse("ad_group_creative_select", args=[gid]), {"creative_id": str(self.crid)}).status_code, 404)  # 남의 광고에 내 이미지를 고를 수 없다
        self.assertEqual(self.client.post(reverse("ad_group_creative_select", args=[self.gid]), {"creative_id": str(crid)}).status_code, 404)  # 내 광고에 남의 이미지도
        self.assertEqual(campaigns.get_ad_group(other.adv, gid).creative_id, other.creative.creative_id)
        self.assertEqual(self.group().creative_id, self.crid)


class StaleSameFieldTests(AdGroupPageBase):
    """외부 검토(41d2288) P3: 작은 폼은 다른 칸을 덮지 않지만, 열어 둔 폼이 **같은 칸**의 최신 변경을 덮었다(S1 → S1+S2 뒤 옛 폼의 S1 이 S2 를 지움).
    이름·구성도 화면이 본 변경 시각과 잠금 안에서 대조한다(이미지 교체는 소재 상세 — `test_creative_pages`)."""

    def test_a_stale_slots_form_does_not_remove_a_slot_added_elsewhere(self):
        seen = self.seen()  # 옛 탭이 본 시각
        second = make_slot(self.w.admin, name="둘째 위치")
        both = [str(self.w.slot.slot_id), str(second.slot_id)]
        self.assertRedirects(self.client.post(reverse("ad_group_slots", args=[self.gid]), {"slot_ids": both, "updated_at": seen}), self.detail)
        r = self.client.post(reverse("ad_group_slots", args=[self.gid]), {"slot_ids": [str(self.w.slot.slot_id)], "updated_at": seen})
        self.assertContains(r, "다른 곳에서 먼저 바뀌었습니다", status_code=409)
        self.assertEqual(set(self.group().slot_ids), {self.w.slot.slot_id, second.slot_id})

    def test_a_stale_name_form_is_refused(self):
        seen = self.seen()
        campaigns.update_ad_group(self.w.adv, self.gid, {"name": "다른 탭"})
        self.assertContains(self.client.post(reverse("ad_group_name", args=[self.gid]), {"name": "옛 탭", "updated_at": seen}),
                            "다른 곳에서 먼저 바뀌었습니다", status_code=409)
        self.assertEqual(self.client.post(reverse("ad_group_name", args=[self.gid]), {"name": "", "updated_at": self.seen()}).status_code, 400)  # 폼이 거른 입력
        self.assertEqual(self.group().name, "다른 탭")
