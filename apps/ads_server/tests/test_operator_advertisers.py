"""Step 3-1d 관리자: 광고주 목록(사용량 대 상한·잔액), 비활성화(사유 필수 — 로그인·세션·송출이 모두 멈춤)·다시 활성화, 지갑·원장 열람,
포인트 조정(사유 필수·0 밑으로 불가·반대 부호의 새 항목, 원장 + 감사 로그, 다시 제출해도 한 번만)."""
import io
import os
import re
import threading
import uuid
from unittest import mock

from django.contrib.admin.utils import quote
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings, tag
from django.http import HttpResponseNotFound
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from billing import api as billing
from billing.models import LedgerEntry, Wallet
from campaigns import api as campaigns
from campaigns.models import CreativeImage
from foundation.admin import UserAdmin
from foundation.admin_site import AuditedAdminSite
from foundation.api import errors, get_advertiser, list_advertisers, set_advertiser_active
from foundation.models import AuditLog, User
from records import api as records
from tests.concurrency import BLOCKED, WAIT, Worker, arriving_before, overlap, pausing_before
from tests.factories import NOW, PW, SUBJECT, World, make_admin, make_advertiser, png_file


@tag("security")
class AdvertiserServiceTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)

    def test_usage_counts_like_the_limits(self):
        campaigns.replace_creative_image(self.w.adv, self.w.creative.creative_id, png_file((1, 2, 3)), now=NOW)  # 교체한 과거 파일도 보유량
        group = campaigns.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "둘째", "IMPRESSION", [self.w.slot.slot_id], bid_amount=30, now=NOW)
        campaigns.create_creative(self.w.adv, group.ad_group_id, "같은 그림", "https://example.com/", png_file(), now=NOW)  # 첫 파일과 같은 파일
        idle = make_advertiser()
        usage = campaigns.advertiser_usage(self.w.admin, [self.w.adv.pk, idle.pk, "not-a-uuid"])
        files = dict(CreativeImage.objects.filter(creative__ad_group__campaign__owner=self.w.adv).values_list("image_name", "image_bytes"))
        self.assertEqual(len(files), 2)
        mine = usage[self.w.adv.pk]
        self.assertEqual((mine.campaigns, mine.creatives, mine.image_bytes), (1, 2, sum(files.values())))  # 같은 파일은 한 번(상한 검사와 같다)
        self.assertEqual((usage[idle.pk].campaigns, usage[idle.pk].image_bytes), (0, 0))  # 없는 광고주는 0 으로
        self.assertEqual(set(usage), {self.w.adv.pk, idle.pk})
        self.assertEqual([a.user_id for a in list_advertisers(self.w.admin)], [idle.pk, self.w.adv.pk])  # 관리자는 빠지고 최근 가입순

    def test_admin_only(self):
        adv = self.w.adv
        for call in (
            lambda: list_advertisers(adv), lambda: get_advertiser(adv, adv.pk), lambda: set_advertiser_active(adv, adv.pk, False, "사유"),
            lambda: campaigns.advertiser_usage(adv, [adv.pk]), lambda: billing.wallet_of(adv, adv.pk), lambda: billing.ledger_of(adv, adv.pk),
        ):
            with self.assertRaises(errors.Forbidden):
                call()

    def test_deactivation_needs_a_reason_and_is_audited(self):
        with self.assertRaises(errors.InvalidRequest):
            set_advertiser_active(self.w.admin, self.w.adv.pk, False, "  ")
        self.assertTrue(User.objects.get(pk=self.w.adv.pk).is_active)
        set_advertiser_active(self.w.admin, self.w.adv.pk, False, "스팸 소재")
        self.assertFalse(User.objects.get(pk=self.w.adv.pk).is_active)
        with self.assertRaises(errors.Conflict):
            set_advertiser_active(self.w.admin, self.w.adv.pk, False, "다시")
        set_advertiser_active(self.w.admin, self.w.adv.pk, True)  # 다시 활성화는 사유가 선택
        actions = list(AuditLog.objects.filter(target_id=str(self.w.adv.pk), action__startswith="account.").order_by("created_at", "pk")
                       .values_list("action", "actor_id", "detail"))
        self.assertEqual(actions, [("account.deactivated", self.w.admin.pk, {"reason": "스팸 소재"}), ("account.reactivated", self.w.admin.pk, {"reason": ""})])
        for other in (self.w.admin.pk, uuid.uuid4(), "x"):  # 관리자 계정·없는 ID 는 광고주가 아니다
            with self.assertRaises(errors.NotFound):
                set_advertiser_active(self.w.admin, other, False, "사유")

    def test_a_deactivated_advertisers_ads_stop_and_come_back(self):
        """설계 결정(2026-10-11): 비활성화는 송출도 멈춘다. 캠페인 상태는 그대로라 다시 활성화하면 다시 나간다."""
        name = self.w.creative.image_name
        self.assertIsNotNone(records.decide(self.w.slot.media_id, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW).chosen)
        set_advertiser_active(self.w.admin, self.w.adv.pk, False, "스팸 소재")
        self.assertIsNone(records.decide(self.w.slot.media_id, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW).chosen)
        self.assertFalse(campaigns.is_asset_servable(name, now=NOW))
        with override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable"):
            self.assertEqual(Client().get(reverse("asset", args=[name])).status_code, 404)
        self.assertEqual(campaigns.get_campaign(self.w.adv, self.w.campaign.campaign_id).status, "ACTIVE")
        set_advertiser_active(self.w.admin, self.w.adv.pk, True)
        self.assertIsNotNone(records.decide(self.w.slot.media_id, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW).chosen)
        self.assertTrue(campaigns.is_asset_servable(name, now=NOW))

    def test_deactivation_ends_sessions_and_blocks_login(self):
        """외부 검토(3-1d) P2: 세션이 정말 끝나야 한다 — 비활성 중에 다녀간 세션도, 다녀가지 않고 쿠키만 둔 세션도 다시 활성화한 뒤 거절된다."""
        visited, kept = Client(), Client()
        for client in (visited, kept):
            self.assertEqual(client.post(reverse("login"), {"username": self.w.adv.username, "password": PW}).status_code, 302)
            self.assertEqual(client.get(reverse("advertiser_home")).status_code, 200)
        set_advertiser_active(self.w.admin, self.w.adv.pk, False, "스팸 소재")
        self.assertEqual(visited.get(reverse("advertiser_home")).status_code, 302)  # 열린 세션도 끝난다
        self.assertEqual(Client().post(reverse("login"), {"username": self.w.adv.username, "password": PW}).status_code, 200)  # 로그인 실패(폼 다시)
        set_advertiser_active(self.w.admin, self.w.adv.pk, True)
        for client in (visited, kept):
            self.assertEqual(client.get(reverse("advertiser_home")).status_code, 302)  # 다시 활성화해도 옛 쿠키로는 못 들어온다
        fresh = Client()
        self.assertEqual(fresh.post(reverse("login"), {"username": self.w.adv.username, "password": PW}).status_code, 302)
        self.assertEqual(fresh.get(reverse("advertiser_home")).status_code, 200)  # 새로 로그인하면 된다


class OperatorAdvertiserBase(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.client.force_login(self.w.admin)
        self.uid = self.w.adv.pk
        self.list = reverse("operator:advertiser_list")
        self.detail = reverse("operator:advertiser_detail", args=[self.uid])
        self.adjust_url = reverse("operator:advertiser_adjust", args=[self.uid])

    def adjust_fields(self, **over):
        """상세 화면의 조정 폼이 싣는 요청 키를 꺼내 함께 보낸다(화면이 싣는 대로)."""
        html = self.client.get(self.detail).content.decode()
        key = re.search(r'name="request_key" value="([^"]+)"', html).group(1)
        return {"request_key": key, "amount": -1000, "note": "잘못 받은 과금 환원 정정", **over}

    def balance(self):
        return billing.get_wallet(self.w.adv, now=NOW).balance


@tag("security")
class AdvertiserPagesTests(OperatorAdvertiserBase):
    def test_list_shows_usage_balance_and_escapes(self):
        User.objects.filter(pk=self.uid).update(nickname="<b>꼬마</b>")  # 가입 규칙을 우회한 값이라도 이스케이프
        html = self.client.get(self.list).content.decode()
        self.assertIn(self.detail, html)
        self.assertIn("&lt;b&gt;꼬마&lt;/b&gt;", html)
        self.assertNotIn("<b>꼬마</b>", html)
        self.assertIn("1 / 20", html)  # 캠페인 수 / 상한
        self.assertIn("50,000 포인트", html)

    def test_detail_shows_the_wallet_ledger_and_password_reset(self):
        html = self.client.get(self.detail).content.decode()
        self.assertIn("50,000 포인트", html)
        self.assertIn("가입 지급", html)
        self.assertIn(reverse("admin:auth_user_password_change", args=[self.uid]), html)  # 비밀번호 초기화는 기존 사용자 관리 화면

    def test_non_admins_and_unknown_ids_see_nothing(self):
        for url in (reverse("operator:advertiser_detail", args=[uuid.uuid4()]), reverse("operator:advertiser_detail", args=[self.w.admin.pk])):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse("operator:advertiser_adjust", args=[uuid.uuid4()]), {"amount": 1, "note": "x"}).status_code, 404)
        for client in (Client(), self.adv_client()):
            self.assertEqual(client.get(self.list).status_code, 404)
            self.assertEqual(client.get(self.detail).status_code, 404)
            self.assertEqual(client.post(self.adjust_url, {"amount": 1000, "note": "x"}).status_code, 404)
            self.assertEqual(client.post(reverse("operator:advertiser_active", args=[self.uid]), {"active": "0", "reason": "x"}).status_code, 404)
        self.assertEqual(self.balance(), 50_000)
        self.assertTrue(User.objects.get(pk=self.uid).is_active)

    def adv_client(self):
        client = Client()
        client.force_login(make_advertiser())
        return client

    def test_deactivate_and_reactivate_from_the_page(self):
        url = reverse("operator:advertiser_active", args=[self.uid])
        self.assertRegex(self.client.get(self.detail).content.decode(), r'<form[^>]*/active"[^>]*data-confirm=')  # 되돌리기 어려운 동작의 확인 창
        self.assertRedirects(self.client.post(url, {"active": "0", "reason": ""}), self.detail, fetch_redirect_response=False)
        self.assertContains(self.client.get(self.detail), "사유은(는) 1~200자의 보이는 문자여야 합니다.")
        self.assertTrue(User.objects.get(pk=self.uid).is_active)
        self.assertRedirects(self.client.post(url, {"active": "0", "reason": "스팸 소재"}), self.detail)
        self.assertContains(self.client.get(self.detail), "로그인할 수 없고 이 광고주의 광고가 나가지 않습니다")
        self.assertRedirects(self.client.post(url, {"active": "1"}), self.detail)
        self.assertTrue(User.objects.get(pk=self.uid).is_active)

    def test_monitor_and_review_queue_mark_a_deactivated_advertiser(self):
        """캠페인 상태는 ACTIVE 그대로라 표시가 없으면 나가는 광고로 오해한다. 광고주 이름은 상세(비활성화·조정)로 이어진다."""
        monitor, queue = reverse("operator:campaign_monitor"), reverse("operator:review_queue")
        campaigns.suspend_campaign(self.w.admin, self.w.campaign.campaign_id, "사유")
        campaigns.create_review_request(self.w.adv, self.w.campaign.campaign_id, "고쳤습니다")
        for url in (monitor, queue):
            html = self.client.get(url).content.decode()
            self.assertIn(self.detail, html)
            self.assertNotIn("광고주 비활성", html)
        set_advertiser_active(self.w.admin, self.uid, False, "스팸 소재")
        self.assertContains(self.client.get(monitor), "광고주 비활성 — 광고가 나가지 않습니다")
        self.assertContains(self.client.get(queue), "광고주 비활성 — 해제해도 광고가 나가지 않습니다")


@tag("security")
class PointAdjustPageTests(OperatorAdvertiserBase):
    def test_adjustment_adds_a_ledger_entry_and_an_audit_and_keeps_balance_equal_to_the_ledger(self):
        self.assertRedirects(self.client.post(self.adjust_url, self.adjust_fields()), self.detail)
        self.assertEqual(self.balance(), 49_000)
        entries, _ = billing.list_ledger(self.w.adv)
        self.assertEqual((entries[0].entry_type, entries[0].amount, entries[0].note), ("ADMIN_ADJUST", -1000, "잘못 받은 과금 환원 정정"))
        self.assertEqual(sum(e.amount for e in entries), self.balance())  # 잔액 = 원장 합계
        self.assertEqual(billing.check_ledger(quiescent=True), [])
        audit = AuditLog.objects.get(action="billing.adjusted")
        self.assertEqual((audit.actor_id, audit.detail["amount"], audit.detail["note"]), (self.w.admin.pk, -1000, "잘못 받은 과금 환원 정정"))
        self.assertContains(self.client.get(self.detail), "관리자 조정")

    def test_a_correction_is_a_new_entry_of_the_opposite_sign(self):
        self.client.post(self.adjust_url, self.adjust_fields(amount=-1000))
        self.client.post(self.adjust_url, self.adjust_fields(amount=1000, note="앞선 조정 되돌림"))
        entries, _ = billing.list_ledger(self.w.adv)
        self.assertEqual([(e.entry_type, e.amount) for e in entries], [("ADMIN_ADJUST", 1000), ("ADMIN_ADJUST", -1000), ("SIGNUP_GRANT", 50_000)])
        self.assertEqual(self.balance(), 50_000)

    def test_cannot_go_below_zero_or_skip_the_reason(self):
        r = self.client.post(self.adjust_url, self.adjust_fields(amount=-50_001))
        self.assertContains(r, "잔액(50000)보다 많이 차감할 수 없습니다", status_code=400)
        self.assertRegex(r.content.decode(), r'name="amount"[^>]*value="-50001"')  # 입력을 지우지 않고 다시 보여 준다
        self.assertEqual(self.client.post(self.adjust_url, self.adjust_fields(note="")).status_code, 400)
        self.assertContains(self.client.post(self.adjust_url, self.adjust_fields(note="   ")), "사유", status_code=400)
        self.assertEqual(self.client.post(self.adjust_url, self.adjust_fields(amount=0)).status_code, 400)
        self.assertEqual(self.client.post(self.adjust_url, self.adjust_fields(amount="1.5")).status_code, 400)
        self.assertEqual(self.balance(), 50_000)
        self.assertFalse(AuditLog.objects.filter(action="billing.adjusted").exists())

    def test_the_same_form_submitted_twice_adjusts_once(self):
        fields = self.adjust_fields()
        self.assertRedirects(self.client.post(self.adjust_url, fields), self.detail)
        self.assertRedirects(self.client.post(self.adjust_url, fields), self.detail)  # 새로 고침·뒤로 가기·두 번 누름: 처음 결과 그대로
        self.assertEqual(self.balance(), 49_000)
        self.assertEqual(LedgerEntry.objects.filter(entry_type="ADMIN_ADJUST").count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="billing.adjusted").count(), 1)
        r = self.client.post(self.adjust_url, {**fields, "amount": -2000})  # 같은 폼에 다른 내용
        self.assertContains(r, "이 조정 폼은 이미 다른 내용으로 처리됐습니다", status_code=409)
        self.assertRedirects(self.client.post(self.adjust_url, {"amount": -1000, "note": "키 없음"}), self.detail, fetch_redirect_response=False)
        self.assertContains(self.client.get(self.detail), "새로 불러와 다시 조정하세요")
        self.assertEqual(self.balance(), 49_000)

    def test_an_input_error_keeps_the_key_and_the_corrected_form_applies_once(self):
        fields = self.adjust_fields(amount=-50_001)
        r = self.client.post(self.adjust_url, fields)
        self.assertEqual(r.status_code, 400)
        self.assertIn(f'value="{fields["request_key"]}"', r.content.decode())  # 아직 아무것도 반영하지 않은 키
        self.assertRedirects(self.client.post(self.adjust_url, {**fields, "amount": -1000}), self.detail)
        self.assertEqual(self.balance(), 49_000)

    def test_ledger_pages_by_cursor(self):
        for i in range(50):
            billing.adjust(self.w.admin, self.uid, 1, f"조정 {i}", now=NOW)
        html = self.client.get(self.detail).content.decode()
        self.assertNotIn("가입 지급", html)  # 한 쪽은 50 줄(최신순)
        older = re.search(r'href="([^"]+)" rel="next"', html).group(1).replace("&amp;", "&")  # 같은 화면의 쿼리(`?before=…`)
        self.assertContains(self.client.get(self.detail + older), "가입 지급")
        for odd in ("abc", "²", "①", "9" * 5000, "-1"):  # 틀린 커서는 첫 쪽(외부 검토 P3: `isdigit()` 이 참인 비 ASCII 숫자·아주 긴 숫자가 500 이었다)
            self.assertContains(self.client.get(self.detail, {"before": odd}), "관리자 조정", msg_prefix=odd)
        self.assertEqual(len(billing.list_ledger(self.w.adv, before="²")[0]), 50)


@tag("security")
class UserAdminActiveFlagTests(TestCase):
    """사용자 관리 화면은 프로필과 비밀번호 초기화만: 계정 추가·역할·활성 여부·슈퍼유저 여부를 바꾸지 않는다. 광고주의 활성 여부는 운영 화면 하나(사유 필수·감사, 송출도 함께 멈춤),
    관리자 계정은 서버 명령."""

    def setUp(self):
        self.root = make_admin()
        self.client.force_login(self.root)

    def save(self, user, **over):
        """사용자 관리 화면의 저장(체크박스를 보내지 않으면 끄기)."""
        data = {"username": user.username, "nickname": user.nickname, "class_label": user.class_label, "role": user.role, "_save": "저장", **over}
        return self.client.post(reverse("admin:foundation_user_change", args=[user.pk]), data)

    def test_user_admin_cannot_change_an_advertisers_active_flag(self):
        adv = make_advertiser()
        self.assertContains(self.client.get(reverse("admin:foundation_user_change", args=[adv.pk])), "광고주 · 포인트 조정")  # 바꾸는 곳 안내
        self.assertEqual(self.save(adv).status_code, 302)  # is_active 를 보내지 않음 = 끄기
        self.assertTrue(User.objects.get(pk=adv.pk).is_active)
        self.assertNotIn("is_active", AuditLog.objects.get(action="account.admin_updated").detail["changed"])
        self.assertFalse(AuditLog.objects.filter(action="account.deactivated").exists())

    def test_user_admin_cannot_change_an_admins_active_flag_either(self):
        """관리자 계정도 화면에서 끄지 않는다(설계 §10) — 급히 끊을 때는 서버 명령 changepassword. 탈취한 관리자 세션이 다른 관리자를 끄지 못한다."""
        other = make_admin()
        signed_in = Client()
        signed_in.force_login(other)
        self.assertContains(self.client.get(reverse("admin:foundation_user_change", args=[other.pk])), "changepassword")  # 끊는 길 안내
        self.assertEqual(self.save(other).status_code, 302)  # is_active 를 보내지 않음 = 끄기
        self.assertEqual(User.objects.filter(pk=other.pk).values_list("is_active", "session_epoch").get(), (True, 0))
        self.assertNotIn("is_active", AuditLog.objects.get(action="account.admin_updated").detail["changed"])
        self.assertEqual(signed_in.get(reverse("admin:index")).status_code, 200)

    def test_user_admin_cannot_add_accounts_or_change_roles(self):
        """관리자는 `createsuperuser` 로만, 광고주는 가입으로만 생긴다(추가 폼으로 만든 광고주는 지갑·가입 지급이 없었다 — 외부 검토 3-1d).
        역할과 슈퍼유저 여부는 어느 계정에서도 바뀌지 않는다(광고주 → 관리자, 관리자 → 광고주)."""
        add = reverse("admin:foundation_user_add")
        self.assertEqual(self.client.get(add).status_code, 403)
        before = User.objects.count()
        r = self.client.post(add, {"username": "made_by_admin", "nickname": "만든", "class_label": "2반", "role": "advertiser",
                                   "password1": "Another-Str0ng-pass", "password2": "Another-Str0ng-pass", "usable_password": "true"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(User.objects.count(), before)
        adv, other = make_advertiser(), make_admin()
        self.assertEqual(self.save(adv, role="admin", is_superuser="on").status_code, 302)  # 광고주 → 관리자
        self.assertEqual(self.save(other, role="advertiser", is_active="on").status_code, 302)  # 관리자 → 광고주, 슈퍼유저 끄기(체크박스 안 보냄)
        self.assertEqual(User.objects.filter(pk=adv.pk).values_list("role", "is_superuser").get(), ("advertiser", False))
        self.assertEqual(User.objects.filter(pk=other.pk).values_list("role", "is_superuser").get(), ("admin", True))
        for entry in AuditLog.objects.filter(action="account.admin_updated"):
            self.assertFalse({"role", "is_superuser"} & set(entry.detail["changed"]))

    def test_the_reset_form_writes_only_the_password(self):
        """심층 방어: 초기화는 대상을 잠근 뒤 읽지만, 폼이 오래된 사용자 객체를 받더라도 비밀번호 열만 써서 그 사이의 비활성화를 되돌리지 않는다
        (외부 검토 3-1d d44b36a — 잠금이 대상을 놓쳤을 때 이 보호가 없어 비활성화가 되돌려졌다)."""
        adv = make_advertiser()
        stale = User.objects.get(pk=adv.pk)
        set_advertiser_active(self.root, adv.pk, False, "스팸 소재")
        form = UserAdmin.change_password_form(stale, {"password1": "Reset-Str0ng-pass-1", "password2": "Reset-Str0ng-pass-1", "usable_password": "true"})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        row = User.objects.get(pk=adv.pk)
        self.assertEqual((row.is_active, row.session_epoch), (False, 1))
        self.assertTrue(row.check_password("Reset-Str0ng-pass-1"))

    def test_user_admin_cannot_delete_accounts(self):
        """외부 검토(3-1d) P2: 추가는 막았지만 삭제는 Django 기본 그대로 열려 있었다(DRD 수명주기: 사용자 삭제 없음). 개별 삭제와 묶음 삭제 모두."""
        other, adv = make_admin(), make_advertiser()
        delete = reverse("admin:foundation_user_delete", args=[other.pk])
        self.assertEqual(self.client.get(delete).status_code, 403)
        self.assertEqual(self.client.post(delete, {"post": "yes"}).status_code, 403)
        changelist = reverse("admin:foundation_user_changelist")
        self.assertNotIn('value="delete_selected"', self.client.get(changelist).content.decode())
        self.client.post(changelist, {"action": "delete_selected", "_selected_action": [str(other.pk), str(adv.pk)], "post": "yes"})
        self.assertEqual(User.objects.filter(pk__in=[other.pk, adv.pk]).count(), 2)

    def test_the_role_detour_cannot_deactivate_an_advertiser(self):
        """외부 검토(3-1d) P2 재현 그대로: 역할을 admin 으로 → (admin 이 된 줄 알고) 활성 끄기 → advertiser 로, 세 번 저장해도 광고주는 켜진 채다."""
        adv = make_advertiser()
        self.assertEqual(self.save(adv, role="admin", is_active="on").status_code, 302)
        self.assertEqual(self.save(User.objects.get(pk=adv.pk), role="admin").status_code, 302)  # 활성 체크 해제
        self.assertEqual(self.save(User.objects.get(pk=adv.pk), role="advertiser").status_code, 302)
        self.assertEqual(User.objects.filter(pk=adv.pk).values_list("role", "is_active").get(), ("advertiser", True))
        self.assertFalse(AuditLog.objects.filter(action="account.deactivated").exists())

    def test_createsuperuser_still_makes_an_admin(self):
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": PW}):
            call_command("createsuperuser", interactive=False, username="made_by_cmd", nickname="관리", class_label="-", stdout=io.StringIO())
        made = User.objects.get(username="made_by_cmd")
        self.assertEqual((made.role, made.is_superuser, made.is_staff), ("admin", True, True))


@tag("security")
class WalletlessAdvertiserTests(OperatorAdvertiserBase):
    """외부 검토(3-1d) P2: 가입 묶음을 거치지 않은 옛 계정(지갑 없음)도 목록·상세가 열리고 비활성화할 수 있다. 조회가 지급을 몰래 만들지 않는다."""

    def test_an_account_without_a_wallet_can_still_be_seen_and_deactivated(self):
        legacy = User.objects.create_user("legacy_adv", PW, nickname="옛계정", class_label="1반")  # 지갑·가입 지급 없음
        detail = reverse("operator:advertiser_detail", args=[legacy.pk])
        self.assertContains(self.client.get(self.list), "지갑 없음")
        html = self.client.get(detail).content.decode()
        self.assertIn("지갑 없음", html)
        self.assertNotIn('name="request_key"', html)  # 조정 폼이 없다
        self.assertRedirects(self.client.post(reverse("operator:advertiser_active", args=[legacy.pk]), {"active": "0", "reason": "옛 계정 정리"}), detail)
        self.assertFalse(User.objects.get(pk=legacy.pk).is_active)
        self.assertEqual(self.client.post(reverse("operator:advertiser_adjust", args=[legacy.pk]),
                                          {"request_key": "k", "amount": 1000, "note": "지급"}).status_code, 404)
        self.assertFalse(Wallet.objects.filter(owner=legacy).exists())


@tag("security")
class AdjustKeyTests(TestCase):
    def setUp(self):
        self.w = World()

    def test_same_key_applies_once_and_a_different_content_is_refused(self):
        first = billing.adjust(self.w.admin, self.w.adv.pk, -1000, "정정", request_key="k1")
        self.assertEqual(billing.adjust(self.w.admin, self.w.adv.pk, -1000, "정정", request_key="k1"), first)
        for over in ({"amount": -2000}, {"note": "다른 사유"}, {"user_id": make_advertiser_with_wallet().pk}):
            args = {"user_id": self.w.adv.pk, "amount": -1000, "note": "정정", **over}
            with self.assertRaises(errors.Conflict):
                billing.adjust(self.w.admin, args["user_id"], args["amount"], args["note"], request_key="k1")
        self.assertEqual(billing.get_wallet(self.w.adv).balance, 49_000)
        self.assertEqual(LedgerEntry.objects.filter(adjust_key="k1").count(), 1)

    def test_db_keeps_one_entry_per_key_and_keys_only_on_adjustments(self):
        billing.adjust(self.w.admin, self.w.adv.pk, 5, "보너스", request_key="k2")
        entry = LedgerEntry.objects.get(adjust_key="k2")
        for changes in ({"adjust_key": "k2", "seq": entry.seq + 1}, {"adjust_key": "k3", "seq": entry.seq + 1, "entry_type": "TOPUP"}):
            row = {f.attname: getattr(entry, f.attname) for f in LedgerEntry._meta.concrete_fields if not f.generated and not f.primary_key}
            with self.assertRaises(IntegrityError), transaction.atomic():
                LedgerEntry.objects.bulk_create([LedgerEntry(**{**row, **changes})])


def make_advertiser_with_wallet():
    adv = make_advertiser()
    billing.grant_signup(adv, now=NOW)
    return adv


@tag("security")
class AdjustRaceTests(TransactionTestCase):
    """외부 검토(3-1d) P1: 같은 폼을 동시에 두 번 보내거나, 처리가 커밋된 뒤 응답이 실패해 다시 보내도 조정은 한 번이다."""

    def setUp(self):
        self.w = World()
        self.uid = self.w.adv.pk
        self.url = reverse("operator:advertiser_adjust", args=[self.uid])
        self.client = Client()
        self.client.force_login(self.w.admin)
        html = self.client.get(reverse("operator:advertiser_detail", args=[self.uid])).content.decode()
        self.fields = {"request_key": re.search(r'name="request_key" value="([^"]+)"', html).group(1), "amount": -1000, "note": "정정"}

    def assert_applied_once(self):
        self.assertEqual(billing.get_wallet(self.w.adv).balance, 49_000)
        self.assertEqual(LedgerEntry.objects.filter(entry_type="ADMIN_ADJUST").count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="billing.adjusted").count(), 1)

    def twin(self):
        """같은 로그인 쿠키를 쓰는 두 번째 브라우저 탭."""
        other = Client()
        other.cookies = self.client.cookies
        return other

    def test_the_same_form_sent_twice_at_once_adjusts_once(self):
        first, second = overlap(self, lambda: self.client.post(self.url, self.fields), "INSERT", "billing_ledger_entry", lambda: self.twin().post(self.url, self.fields),
                                waits=False)  # 둘째는 지갑 잠금을 기다린다
        self.assertEqual((first.errors, second.errors), ([], []))
        self.assertEqual((first.result.status_code, second.result.status_code), (302, 302))
        self.assert_applied_once()

    def test_a_retry_after_the_response_failed_post_commit_adjusts_once(self):
        failing = Client(raise_request_exception=False)
        failing.cookies = self.client.cookies
        with mock.patch.object(SessionStore, "save", side_effect=RuntimeError("세션 저장 실패")):
            self.assertEqual(failing.post(self.url, self.fields).status_code, 500)  # 조정은 커밋됐고 응답만 실패
        self.assertEqual(billing.get_wallet(self.w.adv).balance, 49_000)
        self.assertEqual(self.client.post(self.url, self.fields).status_code, 302)  # 같은 폼으로 재시도
        self.assert_applied_once()


@tag("security")
class UserAdminSaveRaceTests(TransactionTestCase):
    """외부 검토(3-1d) P2: 사용자 관리 화면의 저장이 요청 처음에 읽은 객체를 통째로 써서(`obj.save()`), 그 사이 다른 관리자가 한 비활성화
    (`is_active`·`session_epoch`)를 되돌렸다 — 읽기 전용 칸도 저장에서는 다시 쓰였다. 편집한 칸만 쓴다."""

    def setUp(self):
        self.root = make_admin()
        self.client = Client()
        self.client.force_login(self.root)

    def change_url(self, user):
        return reverse("admin:foundation_user_change", args=[user.pk])

    def save_paused(self, user, data):
        """폼 검증을 마친 뒤 저장 직전에 멈춘 저장(첫 저장만 멈춘다). (작업자, 멈춤, 풀기, 패치)를 돌려준다."""
        paused, release = threading.Event(), threading.Event()
        real = UserAdmin.save_model

        def waiting(admin_self, *args, **kwargs):
            if not paused.is_set():
                paused.set()
                assert release.wait(WAIT)
            return real(admin_self, *args, **kwargs)
        patch = mock.patch.object(UserAdmin, "save_model", waiting)
        patch.start()
        self.addCleanup(patch.stop)
        worker = Worker(lambda: self.client.post(self.change_url(user), data))
        worker.start()
        self.assertTrue(paused.wait(WAIT), "저장 직전에 이르지 않았다")
        return worker, release

    def finish(self, worker, release):
        release.set()
        worker.join(WAIT)
        self.assertEqual(worker.errors, [])
        self.assertEqual(worker.result.status_code, 302)

    def test_a_profile_edit_does_not_undo_a_deactivation_made_in_between(self):
        adv = make_advertiser()
        signed_in = Client()
        signed_in.force_login(adv)
        worker, release = self.save_paused(adv, {"username": adv.username, "nickname": "바꾼닉", "class_label": adv.class_label, "_save": "저장"})
        set_advertiser_active(make_admin(), adv.pk, False, "스팸 소재")  # 다른 관리자가 운영 화면에서 먼저 커밋
        self.finish(worker, release)
        self.assertEqual(User.objects.filter(pk=adv.pk).values_list("nickname", "is_active", "session_epoch").get(), ("바꾼닉", False, 1))
        self.assertEqual(signed_in.get(reverse("advertiser_home")).status_code, 302)  # 옛 세션은 계속 끝난 채
        self.assertEqual(AuditLog.objects.get(action="account.admin_updated").detail["changed"], ["nickname"])

    def test_a_password_reset_does_not_undo_a_deactivation_made_in_between(self):
        """같은 결함의 다른 길: 사용자 관리의 비밀번호 초기화가 대상을 통째로 저장했다. 지금은 초기화가 대상 행을 먼저 잠그므로, 겹친 비활성화는
        그 잠금을 기다렸다가 초기화 뒤에 적용된다 — 어느 쪽도 다른 쪽을 지우지 않는다."""
        self.reset_racing_a_deactivation(lambda pk: pk)

    def test_the_same_holds_for_another_spelling_of_the_target_id(self):
        """외부 검토(3-1d d44b36a) P2: Django 화면은 경로를 `unquote` 한 뒤 대상을 찾아 `urn:uuid:…` 표기도 같은 사용자다. 잠금이 원문을 따로 해석해
        대상을 빼먹으면 비활성화가 되돌려졌다. 잠금도 화면과 같은 해석을 쓴다."""
        self.reset_racing_a_deactivation(lambda pk: quote(f"urn:uuid:{pk}"))

    def reset_racing_a_deactivation(self, spell):
        adv = make_advertiser()
        paused, release = threading.Event(), threading.Event()
        url = reverse("admin:auth_user_password_change", args=[spell(adv.pk)])
        data = {"password1": "Reset-Str0ng-pass-1", "password2": "Reset-Str0ng-pass-1", "usable_password": "true"}
        worker = Worker(pausing_before("UPDATE", "foundation_user", lambda: self.client.post(url, data), paused, release))
        worker.start()
        self.assertTrue(paused.wait(WAIT), "비밀번호 저장에 이르지 않았다")
        deactivate = Worker(lambda: set_advertiser_active(make_admin(), adv.pk, False, "스팸 소재"))
        deactivate.start()
        deactivate.join(BLOCKED)
        self.assertTrue(deactivate.is_alive(), "비활성화가 초기화의 대상 행 잠금을 기다리지 않았다")
        self.finish(worker, release)
        deactivate.join(WAIT)
        self.assertEqual(deactivate.errors, [])
        row = User.objects.get(pk=adv.pk)
        self.assertEqual((row.is_active, row.session_epoch), (False, 1))
        self.assertTrue(row.check_password("Reset-Str0ng-pass-1"))

SERVER_PW = "Server-Chosen-9-pass"


@tag("security")
class EmergencyPasswordResetTests(TransactionTestCase):
    """외부 검토(3-1d) P2: 관리자 계정을 급히 끊는 서버 명령 `changepassword` 가 커밋된 뒤, 그 전에 인증을 마친 진행 중 요청이 비밀번호를 바꾸면
    서버가 정한 비밀번호를 덮고 그 요청의 로그인까지 이어졌다(본인 변경 화면·사용자 관리의 본인 초기화 둘 다). 요청을 인증한 근거를 잠근 최신 행과 대조해 거절한다."""

    def setUp(self):
        self.me = make_admin()
        self.client = Client()
        self.client.force_login(self.me)

    def pause_after_auth(self):
        """요청이 인증(관리자 경로 입장 검사)을 마친 뒤, 화면 처리 전에 멈춘다(첫 검사만)."""
        paused, release = threading.Event(), threading.Event()
        real = AuditedAdminSite.has_permission

        def waiting(site, request):
            allowed = real(site, request)
            if not paused.is_set():
                paused.set()
                assert release.wait(WAIT)
            return allowed
        patch = mock.patch.object(AuditedAdminSite, "has_permission", waiting)
        patch.start()
        self.addCleanup(patch.stop)
        return paused, release

    def emergency_changepassword(self):
        with mock.patch("django.contrib.auth.management.commands.changepassword.getpass.getpass", return_value=SERVER_PW):
            call_command("changepassword", self.me.username, stdout=io.StringIO())  # 진짜 서버 명령

    def race(self, url, data, in_between=None):
        paused, release = self.pause_after_auth()
        worker = Worker(lambda: self.client.post(url, data))
        worker.start()
        self.assertTrue(paused.wait(WAIT), "요청이 인증을 마치지 않았다")
        (in_between or self.emergency_changepassword)()  # 먼저 커밋
        release.set()
        worker.join(WAIT)
        self.assertEqual(worker.errors, [])
        self.assertEqual(worker.result.status_code, 403)  # 오래된 인증 근거의 비밀번호 변경은 거절
        if in_between is None:
            self.assertTrue(User.objects.get(pk=self.me.pk).check_password(SERVER_PW))  # 서버가 정한 비밀번호 그대로
            self.assertEqual(self.client.get(reverse("admin:index")).status_code, 404)  # 그 요청의 로그인도 끝났다

    def test_a_shell_style_deactivation_in_between_is_respected_too(self):
        """셸에서 is_active 만 끈 경우(폐기 버전은 그대로 — 운영 안내상 쓰지 않는 길)에도 진행 중인 비밀번호 변경이 저장하지 않는다."""
        self.race(reverse("admin:password_change"), {"old_password": PW, "new_password1": "Mine-Again-7-pass", "new_password2": "Mine-Again-7-pass"},
                  in_between=lambda: User.objects.filter(pk=self.me.pk).update(is_active=False))
        self.assertTrue(User.objects.get(pk=self.me.pk).check_password(PW))

    def test_an_in_flight_own_password_change_cannot_override_an_emergency_changepassword(self):
        self.race(reverse("admin:password_change"), {"old_password": PW, "new_password1": "Mine-Again-7-pass", "new_password2": "Mine-Again-7-pass"})
        self.assertFalse(AuditLog.objects.filter(action="account.password_changed", actor_id=self.me.pk).exists())

    def test_an_in_flight_own_reset_in_user_admin_cannot_override_an_emergency_changepassword(self):
        self.race(reverse("admin:auth_user_password_change", args=[self.me.pk]),
                  {"password1": "Mine-Again-7-pass", "password2": "Mine-Again-7-pass", "usable_password": "true"})
        self.assertFalse(AuditLog.objects.filter(action="account.password_reset_by_admin").exists())

    def test_an_own_password_change_keeps_a_profile_edit_made_in_between(self):
        """본인 비밀번호 변경도 비밀번호 열만 쓴다 — Django 기본은 인증 때 읽은 사용자 객체를 통째로 저장해 그 사이의 프로필 편집을 되돌렸다."""
        paused, release = self.pause_after_auth()
        worker = Worker(lambda: self.client.post(reverse("admin:password_change"),
                                                 {"old_password": PW, "new_password1": "Mine-Again-7-pass", "new_password2": "Mine-Again-7-pass"}))
        worker.start()
        self.assertTrue(paused.wait(WAIT))
        other = Client()
        other.force_login(make_admin())
        data = {"username": self.me.username, "nickname": "바꾼닉", "class_label": self.me.class_label, "_save": "저장"}
        self.assertEqual(other.post(reverse("admin:foundation_user_change", args=[self.me.pk]), data).status_code, 302)
        release.set()
        worker.join(WAIT)
        self.assertEqual(worker.result.status_code, 302)
        row = User.objects.get(pk=self.me.pk)
        self.assertEqual(row.nickname, "바꾼닉")
        self.assertTrue(row.check_password("Mine-Again-7-pass"))

    def test_a_current_login_still_changes_its_password(self):
        r = self.client.post(reverse("admin:password_change"), {"old_password": PW, "new_password1": "Mine-Again-7-pass", "new_password2": "Mine-Again-7-pass"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.get(pk=self.me.pk).check_password("Mine-Again-7-pass"))
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)  # 바꾼 그 세션은 이어진다


@tag("security")
class MutualResetTests(TransactionTestCase):
    """외부 검토(3-1d 3eb5f77) P2: 두 관리자가 서로의 비밀번호를 동시에 초기화하면, 요청자 행을 먼저 잠그고 대상 행은 저장할 때 잠가 순서가 엇갈렸다 —
    교착(MySQL 1213)으로 한 요청이 500. 요청자와 대상을 ID 순서로 함께 잠그면 줄을 서고, 뒤의 요청은 앞의 초기화로 바뀐 자기 인증 근거 때문에 403 이다."""

    def test_two_admins_resetting_each_other_queue_up_without_a_deadlock(self):
        self.mutual_reset(lambda pk: pk)

    def test_the_same_holds_for_another_spelling_of_the_target_id(self):
        self.mutual_reset(lambda pk: quote(f"urn:uuid:{pk}"))  # 외부 검토(3-1d d44b36a): 다른 표기로 대상이 잠금에서 빠지면 교착이 다시 났다

    def test_an_unreadable_target_is_404_before_anything_is_locked_or_run(self):
        """이름이 주장하는 것까지 본다(외부 검토 00d3067 P3): 404 일 뿐 아니라 행 잠금 SQL 이 나가지 않고 Django 의 초기화 화면도 실행되지 않는다."""
        client = Client()
        client.force_login(make_admin())
        with CaptureQueriesContext(connection) as queries, mock.patch.object(BaseUserAdmin, "user_change_password", return_value=HttpResponseNotFound()) as parent:
            r = client.post(reverse("admin:auth_user_password_change", args=["not-a-user"]),
                            {"password1": "Set-By-A-1-pass", "password2": "Set-By-A-1-pass", "usable_password": "true"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse([q["sql"] for q in queries.captured_queries if "FOR UPDATE" in q["sql"]])
        parent.assert_not_called()

    def mutual_reset(self, spell):
        a, b = make_admin(), make_admin()
        client_a, client_b = Client(), Client()
        client_a.force_login(a)
        client_b.force_login(b)

        def reset(client, target, password):
            return client.post(reverse("admin:auth_user_password_change", args=[spell(target.pk)]),
                               {"password1": password, "password2": password, "usable_password": "true"})
        paused, release = threading.Event(), threading.Event()
        first = Worker(pausing_before("UPDATE", "foundation_user", lambda: reset(client_a, b, "Set-By-A-1-pass"), paused, release))
        first.start()
        self.assertTrue(paused.wait(WAIT), "A 의 초기화가 B 행 UPDATE 에 이르지 않았다")  # A 는 잠금을 쥔 채
        self.addCleanup(release.set)
        arrived = threading.Event()
        second = Worker(arriving_before("FOR UPDATE", "foundation_user", lambda: reset(client_b, a, "Set-By-B-2-pass"), arrived))
        second.start()
        self.assertTrue(arrived.wait(WAIT), "B 의 초기화가 잠금 SQL 에 이르지 않았다")
        second.join(BLOCKED)
        self.assertTrue(second.is_alive(), "B 의 초기화가 잠금을 기다리지 않았다")  # 잠금 SQL 을 보낸 뒤에도 끝나지 않음 = DB 잠금 대기
        release.set()
        first.join(WAIT)
        second.join(WAIT)
        self.assertEqual((first.errors, second.errors), ([], []))  # 교착·500 없음
        self.assertEqual((first.result.status_code, second.result.status_code), (302, 403))
        self.assertTrue(User.objects.get(pk=b.pk).check_password("Set-By-A-1-pass"))
        self.assertTrue(User.objects.get(pk=a.pk).check_password(PW))  # 뒤의 요청은 반영되지 않았다
        self.assertEqual(client_b.get(reverse("admin:index")).status_code, 404)  # B 의 옛 세션은 끝났다
        self.assertEqual(client_a.get(reverse("admin:index")).status_code, 200)


@tag("security")
class PasswordAuditAtomicityTests(TransactionTestCase):
    """외부 검토(00d3067) P2: 비밀번호 변경·초기화의 성공 감사 기록을 변경이 커밋된 **뒤에** 써서, 기록이 실패하면 응답은 500 인데 비밀번호는 바뀌고
    기록은 0 건이었다. 기록은 변경과 같은 트랜잭션이라 실패하면 비밀번호도 되돌려진다."""

    def setUp(self):
        self.me = make_admin()
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.me)
        self.adv = make_advertiser()
        self.cases = {
            "account.password_changed": (reverse("admin:password_change"),
                                         {"old_password": PW, "new_password1": "Mine-Again-7-pass", "new_password2": "Mine-Again-7-pass"}, self.me),
            "account.password_reset_by_admin": (reverse("admin:auth_user_password_change", args=[self.adv.pk]),
                                                {"password1": "Mine-Again-7-pass", "password2": "Mine-Again-7-pass", "usable_password": "true"}, self.adv),
        }

    def test_a_failing_success_audit_rolls_the_password_back(self):
        def fail_audit_insert(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith("INSERT") and "`foundation_audit_log`" in sql:
                raise DatabaseError("감사 기록 실패(시험)")
            return execute(sql, params, many, context)
        for action, (url, data, user) in self.cases.items():
            with self.subTest(action), connection.execute_wrapper(fail_audit_insert):
                self.assertEqual(self.client.post(url, data).status_code, 500)
            self.assertTrue(User.objects.get(pk=user.pk).check_password(PW), action)  # 바뀌지 않았다
            self.assertFalse(AuditLog.objects.filter(action=action).exists())

    def test_a_success_writes_exactly_one_audit_with_the_change(self):
        for action, (url, data, user) in self.cases.items():
            with self.subTest(action):
                self.assertEqual(self.client.post(url, data).status_code, 302)
                self.assertTrue(User.objects.get(pk=user.pk).check_password("Mine-Again-7-pass"))
                entry = AuditLog.objects.get(action=action)
                self.assertEqual((entry.actor_id, entry.target_id), (self.me.pk, str(user.pk)))


@tag("security")
class TransientLockOnAdminWriteTests(TransactionTestCase):
    """외부 검토(00d3067) P3: 관리자 쓰기에서 잠금 대기 초과가 500(Retry-After 없음)으로 나갔다. 서버가 되돌린 일시 오류는 503 + Retry-After 다."""

    def test_a_lock_wait_timeout_is_503_with_retry_after_and_nothing_changes(self):
        admin, adv = make_admin(), make_advertiser()
        client = Client(raise_request_exception=False)
        client.force_login(admin)
        held, done = threading.Event(), threading.Event()

        def hold():  # 다른 연결이 대상 행을 잠그고 있다
            with transaction.atomic():
                User.objects.select_for_update().get(pk=adv.pk)
                held.set()
                done.wait(WAIT)
        holder = Worker(hold)
        holder.start()
        self.addCleanup(done.set)
        self.assertTrue(held.wait(WAIT))
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout = 1")  # 이 연결(요청)만 짧게
        try:
            r = client.post(reverse("admin:auth_user_password_change", args=[adv.pk]),
                            {"password1": "Mine-Again-7-pass", "password2": "Mine-Again-7-pass", "usable_password": "true"})
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION innodb_lock_wait_timeout = DEFAULT")
            done.set()
            holder.join(WAIT)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r["Retry-After"], "1")
        self.assertIn("text/html", r["Content-Type"])
        self.assertTrue(User.objects.get(pk=adv.pk).check_password(PW))
