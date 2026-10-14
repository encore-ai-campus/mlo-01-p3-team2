"""Step 3-1b 관리자 화면: 입찰 정책 새 버전(현재값이 채워진 폼·사유·낙관적 잠금), 이력, 여러 슬롯 일괄 새 버전(전부 성공/전부 취소)."""
import uuid

from django.test import TestCase, tag
from django.urls import reverse

from foundation.models import AuditLog
from masters import api as masters
from tests.support.factories import SHARES, make_admin, make_advertiser, make_slot


def versions(slot_id):
    return [p.policy_version for p in masters.list_policy_versions(make_admin(), slot_id)]


@tag("security")
class PolicyPageTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.slot = make_slot(self.admin, floor=100, base=200, cap=500, name="로비 배너")
        self.url = reverse("operator:slot_policy", args=[self.slot.slot_id])

    def post(self, **over):
        return self.client.post(self.url, {"floor": 150, "base": 250, "cap": 600, "impression_share": 1, "click_share": 98, "conversion_share": 1,
                                           "reason": "가격 조정", "expected_version": 1, **over})

    def test_form_starts_from_the_current_policy_and_shows_history(self):
        html = self.client.get(self.url).content.decode()
        for name, value in (("floor", 100), ("base", 200), ("cap", 500), *SHARES.items(), ("expected_version", 1)):
            self.assertRegex(html, rf'name="{name}" value="{value}"')
        self.assertIn("초기", html)  # 이력의 사유
        self.assertIn("<td>노출 98% · 클릭 1% · 전환 1%</td>", html)  # 이력의 비율
        self.assertIn("상한 500 포인트 · 노출 98% · 클릭 1% · 전환 1%</p>", html)  # 현재 정책의 비율
        self.assertIn(f"<td>{self.admin.username}</td>", html)  # 이력의 바꾼 사람(머리글의 환영 문구가 아니라)

    def test_a_new_version_is_added_and_audited(self):
        self.assertRedirects(self.post(), self.url)
        current = masters.get_slot(self.slot.slot_id).policy
        self.assertEqual((current.policy_version, current.floor, current.base, current.cap, current.reason), (2, 150, 250, 600, "가격 조정"))
        self.assertEqual((current.impression_share, current.click_share, current.conversion_share), (1, 98, 1))
        self.assertTrue(AuditLog.objects.filter(action="masters.policy_added", actor_id=self.admin.pk).exists())

    def test_a_concurrent_change_is_explained_and_nothing_is_overwritten(self):
        masters.add_policy_version(make_admin(), self.slot.slot_id, 110, 210, 510, "다른 관리자", expected_version=1, **SHARES)  # 폼을 연 뒤 누가 먼저 바꿈
        r = self.post()
        self.assertContains(r, "다른 곳에서 먼저 바뀌었습니다", status_code=409)
        self.assertContains(r, "새로 불러오기", status_code=409)
        self.assertEqual(versions(self.slot.slot_id), [2, 1])  # 덮어쓰지 않았다
        self.assertRegex(r.content.decode(), r'name="expected_version" value="1"')  # 본 버전을 몰래 올려 다시 보내면 덮어쓰게 되므로 그대로 둔다

    def test_value_rules_are_shown_next_to_the_fields(self):
        self.assertContains(self.post(floor=300), "하한 ≤ 기준가 ≤ 상한이어야 합니다.", status_code=400)
        self.assertEqual(self.post(reason="").status_code, 400)
        r = self.post(click_share=99, conversion_share=0)
        self.assertContains(r, "1 이상 98 이하의 정수(%)여야 합니다.", count=2, status_code=400)  # 두 칸 모두에
        r = self.post(click_share=97)
        self.assertContains(r, "노출·클릭·전환 비율의 합은 100이어야 합니다(지금 99).", status_code=400)
        self.assertNotContains(r, "새로 불러오기", status_code=400)  # 버전 충돌이 아니다
        self.assertEqual(versions(self.slot.slot_id), [1])

    def test_unknown_slot_is_404_and_non_admins_see_nothing(self):
        self.assertEqual(self.client.get(reverse("operator:slot_policy", args=[uuid.uuid4()])).status_code, 404)
        self.client.force_login(make_advertiser())
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(versions(self.slot.slot_id), [1])

    def test_media_page_links_to_the_policy_page(self):
        self.assertContains(self.client.get(reverse("operator:media_detail", args=[self.slot.media_id])), self.url)


@tag("security")
class BulkPolicyPageTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.a, self.b = make_slot(self.admin, name="첫 배너"), make_slot(self.admin, name="<b>둘째</b>")
        self.url = reverse("operator:policy_bulk")

    def post(self, slots, **over):
        return self.client.post(self.url, {"slots": slots, "floor": 500, "base": 600, "cap": 700, "impression_share": 1, "click_share": 1, "conversion_share": 98,
                                           "reason": "일괄 인하", **over})

    def test_lists_every_slot_with_its_version_escaped(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn(f'value="{self.a.slot_id}:1"', html)
        self.assertIn("500 포인트 · 노출 98% · 클릭 1% · 전환 1%</td>", html)  # 고를 때 지금 비율을 본다
        self.assertIn("&lt;b&gt;둘째&lt;/b&gt;", html)
        self.assertNotIn("<b>둘째</b>", html)

    def test_all_chosen_slots_get_the_same_new_version(self):
        self.assertRedirects(self.post([f"{self.a.slot_id}:1", f"{self.b.slot_id}:1"]), self.url)
        for slot in (self.a, self.b):
            policy = masters.get_slot(slot.slot_id).policy
            self.assertEqual((policy.policy_version, policy.floor, policy.cap, policy.impression_share, policy.conversion_share), (2, 500, 700, 1, 98))

    def test_one_stale_slot_cancels_all_and_names_it(self):
        masters.add_policy_version(self.admin, self.b.slot_id, 110, 210, 510, "먼저 바뀜", expected_version=1, **SHARES)
        r = self.post([f"{self.a.slot_id}:1", f"{self.b.slot_id}:1"])
        self.assertContains(r, "다른 곳에서 먼저 바뀌었습니다", status_code=409)
        self.assertContains(r, "&lt;b&gt;둘째&lt;/b&gt;", status_code=409)
        self.assertContains(r, "새로 불러오기", status_code=409)
        self.assertEqual((versions(self.a.slot_id), versions(self.b.slot_id)), ([1], [2, 1]))  # 첫 배너도 바뀌지 않았다

    def test_choosing_nothing_or_tampered_values(self):
        self.assertContains(self.post([]), "하나 이상 고르세요", status_code=400)
        self.assertEqual(self.post(["not-a-pair"]).status_code, 400)
        self.assertEqual(self.post([f"{uuid.uuid4()}:1"]).status_code, 404)
        r = self.post([f"{self.a.slot_id}:1"], impression_share=2)
        self.assertContains(r, "노출·클릭·전환 비율의 합은 100이어야 합니다(지금 101).", status_code=400)
        self.assertNotContains(r, "새로 불러오기", status_code=400)
        self.assertEqual(versions(self.a.slot_id), [1])
