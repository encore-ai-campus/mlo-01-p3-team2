"""소재 화면(6-9d, 설계 §10 "소재 목록"): 목록(올리기·쓰는 광고·삭제), 상세(수정·이미지 교체·삭제). 소재는 여러 광고에 쓰이므로 상세에서 고치면 상세로 돌아온다."""
import re

from django.test import Client, TestCase, override_settings, tag
from django.urls import reverse

from campaigns import api as campaigns
from campaigns.models import CreativeImage
from tests.factories import NOW, World, png_file

LIST = reverse("creative_list")


@tag("security")
class CreativePageTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.client.force_login(self.w.adv)
        self.spare = campaigns.create_creative(self.w.adv, None, "예비 소재", "https://spare.example/", png_file((7, 7, 7)), now=NOW)

    def test_the_list_shows_where_each_creative_is_used_and_only_unused_ones_can_be_deleted(self):
        html = self.client.get(LIST).content.decode()
        self.assertIn("그룹</a> <span class=\"muted\">(캠페인 · 나가는 중)</span>", html)
        self.assertIn(reverse("creative_archive", args=[self.spare.creative_id]), html)  # 쓰는 광고가 없다 — 삭제 버튼
        self.assertNotIn(reverse("creative_archive", args=[self.w.creative.creative_id]), html)  # 끝나지 않은 캠페인의 광고에 쓰인다
        self.assertIn("사용 중", html)

    def test_deleting_hides_a_creative_and_a_used_one_is_refused_with_a_reason(self):
        self.assertRedirects(self.client.post(reverse("creative_archive", args=[self.spare.creative_id])), LIST)
        self.assertNotIn("예비 소재", self.client.get(LIST).content.decode())
        r = self.client.post(reverse("creative_archive", args=[self.w.creative.creative_id]), follow=True)
        self.assertContains(r, "끝나지 않은 캠페인의 광고에 연결된 소재는 삭제할 수 없습니다")  # 위조한 요청도 서비스가 막는다
        self.assertFalse(campaigns.get_creative(self.w.adv, self.w.creative.creative_id).archived)

    def test_inputs_the_forms_reject_redraw_the_detail_page_and_change_nothing(self):
        """폼이 거른 입력(빈 제목·변경 시각 없음·파일 없음)은 서비스까지 가지 않고, 입력한 값을 지닌 채 상세를 400 으로 다시 그린다."""
        prefix, before = str(self.spare.creative_id), campaigns.get_creative(self.w.adv, self.spare.creative_id)
        edit, image, seen = reverse("creative_edit", args=[prefix]), reverse("creative_image", args=[prefix]), before.updated_at.isoformat()
        r = self.client.post(edit, {f"{prefix}-title": "", f"{prefix}-redirect_url": "https://typed.example/", f"{prefix}-updated_at": seen})
        self.assertContains(r, f'id="id_{prefix}-title_error"', status_code=400)
        self.assertContains(r, 'value="https://typed.example/"', status_code=400)  # 새 폼이 아니라 제출한 폼을 다시 그린다
        r = self.client.post(edit, {f"{prefix}-title": "고친 제목", f"{prefix}-redirect_url": "https://spare.example/"})  # 변경 시각 없음
        self.assertContains(r, 'value="고친 제목"', status_code=400)
        r = self.client.post(image, {f"{prefix}-updated_at": seen})  # 파일 없음
        self.assertContains(r, f'id="image_{prefix}-image_error"', status_code=400)
        after = campaigns.get_creative(self.w.adv, self.spare.creative_id)
        self.assertEqual((after.title, after.redirect_url, after.image_name, after.updated_at), (before.title, before.redirect_url, before.image_name, before.updated_at))

    def test_a_deleted_creative_is_read_only(self):
        campaigns.archive_creative(self.w.adv, self.spare.creative_id, now=NOW)
        html = self.client.get(reverse("creative_detail", args=[self.spare.creative_id])).content.decode()
        self.assertIn("삭제한 소재입니다", html)
        self.assertNotIn(reverse("creative_edit", args=[self.spare.creative_id]), html)
        self.assertNotIn(reverse("creative_archive", args=[self.spare.creative_id]), html)

    def test_another_advertisers_creative_is_404(self):
        other = World(ends_in=None)
        for name in ("creative_detail", "creative_image_file"):
            self.assertEqual(self.client.get(reverse(name, args=[other.creative.creative_id])).status_code, 404, name)
        self.assertEqual(self.client.post(reverse("creative_archive", args=[other.creative.creative_id])).status_code, 404)
        self.assertNotIn(str(other.creative.creative_id), self.client.get(LIST).content.decode())


@tag("security")
class CreativeDetailTests(TestCase):
    """소재 상세의 제목·주소 수정과 이미지 교체(6-11 부터 여기서만 — 광고 상세는 고르기만 한다). 화면이 본 변경 시각을 잠금 안에서 대조한다."""

    def setUp(self):
        self.w = World(ends_in=None)
        self.crid = self.w.creative.creative_id
        self.client.force_login(self.w.adv)
        self.creative_page = reverse("creative_detail", args=[self.crid])

    def creative(self):
        return campaigns.get_creative(self.w.adv, self.crid)

    def seen_creative(self):
        return self.creative().updated_at.isoformat()

    def edit_fields(self, **over):
        """소재 상세의 제목·주소 폼(접두사 = 소재 ID)이 싣는 값."""
        prefix = str(self.crid)
        html = self.client.get(self.creative_page).content.decode()
        found = dict(re.findall(rf'name="{prefix}-(title|redirect_url|updated_at)"[^>]*?value="([^"]*)"', html))
        return {f"{prefix}-{k}": v for k, v in {**found, **over}.items()}

    def image_fields(self, image, creative=None, updated_at=None):
        """소재 상세의 이미지 교체 폼(접두사 = 소재 ID)."""
        creative = creative or self.creative()
        return {f"{creative.creative_id}-image": image, f"{creative.creative_id}-updated_at": updated_at or creative.updated_at.isoformat()}

    def test_edit_only_what_changed(self):
        self.assertRedirects(self.client.post(reverse("creative_edit", args=[self.crid]), self.edit_fields(title="새 제목")), self.creative_page)
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

    def test_image_replacement_keeps_the_old_file(self):
        old = self.creative().image_name
        self.assertRedirects(self.client.post(reverse("creative_image", args=[self.crid]), self.image_fields(png_file((5, 6, 7)))), self.creative_page)
        self.assertNotEqual(self.creative().image_name, old)
        self.assertEqual(set(CreativeImage.objects.filter(creative_id=self.crid).values_list("image_name", flat=True)), {old, self.creative().image_name})

    def test_a_rejected_image_shows_the_reason(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post(reverse("creative_image", args=[self.crid]), self.image_fields(SimpleUploadedFile("x.png", b"nope", content_type="image/png")))
        self.assertEqual(r.status_code, 400)
        self.assertRegex(r.content.decode(), rf'id="image_{self.crid}-image_error"><li>[^<]+</li>')

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

    def test_a_stale_image_form_does_not_replace_a_newer_image(self):
        seen = self.seen_creative()
        newer = campaigns.replace_creative_image(self.w.adv, self.crid, png_file((1, 2, 3)))
        r = self.client.post(reverse("creative_image", args=[self.crid]), self.image_fields(png_file((7, 7, 7)), updated_at=seen))
        self.assertContains(r, "다른 곳에서 먼저 바뀌었습니다", status_code=409)
        self.assertEqual(self.creative().image_name, newer.image_name)
