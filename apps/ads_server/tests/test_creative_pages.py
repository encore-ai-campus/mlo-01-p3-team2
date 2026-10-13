"""소재 화면(6-9d, 설계 §10 "소재 목록"): 목록(올리기·쓰는 광고·삭제), 상세(수정·이미지 교체·삭제). 소재는 여러 광고에 쓰이므로 상세에서 고치면 상세로 돌아온다."""
from django.test import TestCase, tag
from django.urls import reverse

from campaigns import api as campaigns
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

    def test_an_edit_from_the_detail_page_returns_there(self):
        detail = reverse("creative_detail", args=[self.spare.creative_id])
        updated_at = campaigns.get_creative(self.w.adv, self.spare.creative_id).updated_at.isoformat()
        prefix = str(self.spare.creative_id)
        r = self.client.post(reverse("creative_edit", args=[self.spare.creative_id]),
                             {f"{prefix}-title": "고친 제목", f"{prefix}-redirect_url": "https://spare.example/", f"{prefix}-updated_at": updated_at})
        self.assertRedirects(r, detail)
        self.assertEqual(campaigns.get_creative(self.w.adv, self.spare.creative_id).title, "고친 제목")
        updated_at = campaigns.get_creative(self.w.adv, self.spare.creative_id).updated_at.isoformat()
        r = self.client.post(reverse("creative_edit", args=[self.spare.creative_id]),
                             {f"{prefix}-title": " ", f"{prefix}-redirect_url": "https://spare.example/", f"{prefix}-updated_at": updated_at})
        self.assertContains(r, f'id="id_{prefix}-title_error"', status_code=400)  # 상세 화면을 오류와 함께 다시 그린다

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
