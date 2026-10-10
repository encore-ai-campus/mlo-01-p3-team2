"""Step 3-1a 관리자 화면: 매체·슬롯 등록과 활성/비활성, 매체 키 발급·교체·폐기(계획 §8.1.3, S6). 화면은 서비스만 부른다."""
import logging
import re
import uuid
from datetime import timedelta

from django.test import Client, TestCase, tag
from django.urls import reverse
from django.utils import timezone

from foundation.models import AuditLog
from masters import api as masters
from masters.models import MediaKey
from tests.factories import make_admin, make_advertiser, make_slot

KEY_RE = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}")


def once_token(html, form_id):
    """페이지의 그 폼에 든 한 번 쓰는 토큰."""
    form = html[html.index(f'id="{form_id}"'):]
    return re.search(r'name="once" value="([^"]+)"', form).group(1)


@tag("security")
class OperatorAccessTests(TestCase):
    def test_only_admins_see_the_operator_pages(self):
        media = masters.create_media(make_admin(), "매체")
        urls = [reverse("operator:media_list"), reverse("operator:media_detail", args=[media.media_id])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404)  # 익명에게도 존재를 숨긴다(관리자 경로 규칙)
        self.client.force_login(make_advertiser())
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {"name": "x"}).status_code, 404)
        self.client.force_login(make_admin())
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_index_links_to_the_operator_pages(self):
        self.client.force_login(make_admin())
        self.assertContains(self.client.get(reverse("admin:index")), reverse("operator:media_list"))


class OperatorBase(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)


@tag("security")
class MediaPageTests(OperatorBase):
    def test_create_media(self):
        r = self.client.post(reverse("operator:media_list"), {"name": "메타버스 캠퍼스"})
        self.assertRedirects(r, reverse("operator:media_list"))
        self.assertEqual([m.name for m in masters.list_media(self.admin)], ["메타버스 캠퍼스"])
        self.assertTrue(AuditLog.objects.filter(action="masters.media_created", actor_id=self.admin.pk).exists())

    def test_service_errors_are_shown_on_the_form(self):
        masters.create_media(self.admin, "같은 이름")
        r = self.client.post(reverse("operator:media_list"), {"name": "같은 이름"})
        self.assertContains(r, "같은 이름의 매체가 이미 있습니다.", status_code=400)
        self.assertContains(self.client.post(reverse("operator:media_list"), {"name": "  "}), "매체 이름", status_code=400)

    def test_toggle_media_active(self):
        media = masters.create_media(self.admin, "매체")
        url = reverse("operator:media_active", args=[media.media_id])
        self.assertRedirects(self.client.post(url, {"active": "0"}), reverse("operator:media_list"))
        self.assertFalse(masters.get_media(self.admin, media.media_id).is_active)
        self.client.post(url, {"active": "1"})
        self.assertTrue(masters.get_media(self.admin, media.media_id).is_active)
        self.assertEqual(self.client.post(reverse("operator:media_active", args=[uuid.uuid4()]), {"active": "1"}).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 405)  # 상태를 바꾸는 주소는 POST 만

    def test_names_are_escaped(self):
        masters.create_media(self.admin, "<script>alert(1)</script>")
        html = self.client.get(reverse("operator:media_list")).content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse("operator:media_list"), {"name": "토큰 없음"}).status_code, 403)
        self.assertEqual(masters.list_media(self.admin), [])


@tag("security")
class SlotPageTests(OperatorBase):
    def setUp(self):
        super().setUp()
        self.media = masters.create_media(self.admin, "매체")
        self.detail = reverse("operator:media_detail", args=[self.media.media_id])

    def post_slot(self, **over):
        data = {"name": "로비 배너", "pricing_unit": "CLICK", "audience": "shared", "floor": 10, "base": 20, "cap": 50, "reason": "개설", **over}
        return self.client.post(reverse("operator:slot_create", args=[self.media.media_id]), data)

    def test_create_slot_shows_unit_and_audience_and_says_they_are_fixed(self):
        self.assertRedirects(self.post_slot(), self.detail)
        (slot,) = masters.list_slots(active_only=False, media_id=self.media.media_id)
        self.assertEqual((slot.pricing_unit, slot.audience, slot.policy.floor, slot.policy.cap), ("CLICK", "shared", 10, 50))
        html = self.client.get(self.detail).content.decode()
        self.assertIn("로비 배너", html)
        self.assertIn("<td>클릭</td>", html)  # 코드(CLICK)가 아니라 화면 이름
        self.assertIn("<td>일괄</td>", html)
        self.assertIn("만든 뒤 바꿀 수 없습니다", html)

    def test_policy_errors_go_next_to_the_fields(self):
        r = self.post_slot(floor=30, base=20)
        self.assertContains(r, "하한 ≤ 기준가 ≤ 상한이어야 합니다.", status_code=400)
        self.assertEqual(masters.list_slots(active_only=False, media_id=self.media.media_id), [])

    def test_toggle_slot_active(self):
        slot = make_slot(self.admin)
        url = reverse("operator:slot_active", args=[slot.slot_id])
        self.assertRedirects(self.client.post(url, {"active": "0"}), reverse("operator:media_detail", args=[slot.media_id]))
        self.assertFalse(masters.get_slot(slot.slot_id).is_active)

    def test_unknown_media_is_404(self):
        r = self.client.get(reverse("operator:media_detail", args=[uuid.uuid4()]))
        self.assertEqual(r.status_code, 404)
        self.assertIn("text/html", r["Content-Type"])  # 화면의 404(서비스 예외가 API 오류 형식으로 새지 않는다)
        self.assertEqual(self.client.get(reverse("operator:media_detail", args=["not-a-uuid"])).status_code, 404)


@tag("security")
class MediaKeyPageTests(OperatorBase):
    def setUp(self):
        super().setUp()
        self.media = masters.create_media(self.admin, "매체")
        self.detail = reverse("operator:media_detail", args=[self.media.media_id])

    def issue(self, token=None):
        token = token or once_token(self.client.get(self.detail).content.decode(), "key-issue")
        return self.client.post(reverse("operator:key_issue", args=[self.media.media_id]), {"label": "운영", "once": token})

    def test_the_plain_key_is_shown_once_and_stored_nowhere(self):
        with self.assertLogs(level="DEBUG") as logs:  # 루트 로거: 모든 로거가 여기로 올라온다
            logging.getLogger("probe").debug("시작")  # 로그가 하나도 없어도 assertLogs 가 실패하지 않게
            r = self.issue()
        self.assertEqual(r.status_code, 200)
        keys = KEY_RE.findall(r.content.decode())
        self.assertEqual(len(set(keys)), 1)
        key = keys[0]
        self.assertIn("no-store", r["Cache-Control"])
        row = MediaKey.objects.get()
        self.assertNotIn(key, str(row.__dict__))  # DB 에는 해시만
        self.assertFalse(any(key in str(a.detail) for a in AuditLog.objects.all()))
        self.assertFalse(any(key in line for line in logs.output))
        self.assertNotIn(key, self.client.get(self.detail).content.decode())  # 다시 보기 없음
        self.assertIsNotNone(masters.authenticate_media_key(key))

    def test_resubmitting_the_same_form_does_not_issue_another_key(self):
        token = once_token(self.client.get(self.detail).content.decode(), "key-issue")
        self.assertEqual(self.issue(token).status_code, 200)
        r = self.issue(token)  # 새로 고침·뒤로 가기로 같은 폼을 다시 보냄
        self.assertRedirects(r, self.detail)
        self.assertEqual(MediaKey.objects.count(), 1)
        self.assertEqual(self.client.post(reverse("operator:key_issue", args=[self.media.media_id]), {"once": "forged"}).status_code, 302)
        self.assertEqual(MediaKey.objects.count(), 1)

    def test_rotate_keeps_the_old_key_for_the_chosen_grace(self):
        old = masters.issue_media_key(self.admin, self.media.media_id)
        token = once_token(self.client.get(self.detail).content.decode(), "key-rotate")
        before = timezone.now()
        r = self.client.post(reverse("operator:key_rotate", args=[self.media.media_id]), {"grace_seconds": "3600", "label": "", "once": token})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(set(KEY_RE.findall(r.content.decode()))), 1)
        expires = MediaKey.objects.get(pk=old.key_id).expires_at
        self.assertTrue(before + timedelta(seconds=3590) < expires <= timezone.now() + timedelta(seconds=3600))
        self.assertEqual(MediaKey.objects.count(), 2)

    def test_revoke(self):
        issued = masters.issue_media_key(self.admin, self.media.media_id)
        self.assertIn("data-confirm=", self.client.get(self.detail).content.decode())  # 되돌릴 수 없는 동작은 확인 창(JS 가 없으면 바로 제출)
        r = self.client.post(reverse("operator:key_revoke", args=[issued.key_id]), {"media_id": str(self.media.media_id)})
        self.assertRedirects(r, self.detail)
        self.assertIsNone(masters.authenticate_media_key(issued.key))
        html = self.client.get(self.detail).content.decode()
        self.assertIn("폐기됨", html)
