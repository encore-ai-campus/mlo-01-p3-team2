"""Step 3-1d 관리자: 광고주 목록(사용량 대 상한·잔액), 비활성화(사유 필수 — 로그인·세션·송출이 모두 멈춤)·다시 활성화, 지갑·원장 열람,
포인트 조정(사유 필수·0 밑으로 불가·반대 부호의 새 항목, 원장 + 감사 로그, 다시 제출해도 한 번만)."""
import io
import os
import re
import threading
import uuid
from unittest import mock

from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings, tag
from django.urls import reverse

from billing import api as billing
from billing.models import LedgerEntry, Wallet
from campaigns import api as campaigns
from campaigns.models import CreativeImage
from foundation.api import errors, get_advertiser, list_advertisers, set_advertiser_active
from foundation.models import AuditLog, User
from records import api as records
from tests.factories import NOW, PW, SUBJECT, World, make_admin, make_advertiser, png_file
from tests.test_campaign_expire_race import pausing_before
from tests.test_receipt_ordering import BLOCKED, WAIT, Worker


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
    """광고주의 활성 여부를 바꾸는 길은 운영 화면 하나(사유 필수·감사, 송출도 함께 멈춤). 사용자 관리 화면에서는 읽기 전용이고, 관리자 계정은 그대로 바꾼다."""

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

    def test_user_admin_still_changes_an_admins_active_flag(self):
        other = make_admin()
        signed_in = Client()
        signed_in.force_login(other)
        self.assertEqual(self.save(other, is_superuser="on").status_code, 302)
        self.assertFalse(User.objects.get(pk=other.pk).is_active)
        self.assertIn("is_active", AuditLog.objects.get(action="account.admin_updated").detail["changed"])
        self.assertEqual(self.save(User.objects.get(pk=other.pk), is_active="on", is_superuser="on").status_code, 302)
        self.assertEqual(signed_in.get(reverse("admin:index")).status_code, 404)  # 껐던 관리자의 옛 세션도 다시 켠 뒤 돌아오지 않는다

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
        paused, release = threading.Event(), threading.Event()
        first = Worker(pausing_before("INSERT", "billing_ledger_entry", lambda: self.client.post(self.url, self.fields), paused, release))
        first.start()
        self.assertTrue(paused.wait(WAIT), "첫 요청이 원장 INSERT 에 이르지 않았다")
        second = Worker(lambda: self.twin().post(self.url, self.fields))
        second.start()
        second.join(BLOCKED)  # 지갑 잠금을 기다린다
        release.set()
        first.join(WAIT)
        second.join(WAIT)
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
