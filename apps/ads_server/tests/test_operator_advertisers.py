"""Step 3-1d 관리자: 광고주 목록(사용량 대 상한·잔액), 비활성화(사유 필수 — 로그인·세션·송출이 모두 멈춤)·다시 활성화, 지갑·원장 열람,
포인트 조정(사유 필수·0 밑으로 불가·반대 부호의 새 항목, 원장 + 감사 로그, 다시 제출해도 한 번만)."""
import re
import uuid

from django.test import Client, TestCase, override_settings, tag
from django.urls import reverse

from billing import api as billing
from campaigns import api as campaigns
from campaigns.models import CreativeImage
from foundation.api import errors, get_advertiser, list_advertisers, set_advertiser_active
from foundation.models import AuditLog, User
from records import api as records
from tests.factories import NOW, PW, SUBJECT, World, make_advertiser, png_file


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
        signed_in = Client()
        self.assertEqual(signed_in.post(reverse("login"), {"username": self.w.adv.username, "password": PW}).status_code, 302)
        self.assertEqual(signed_in.get(reverse("advertiser_home")).status_code, 200)
        set_advertiser_active(self.w.admin, self.w.adv.pk, False, "스팸 소재")
        self.assertEqual(signed_in.get(reverse("advertiser_home")).status_code, 302)  # 열린 세션도 끝난다
        self.assertEqual(Client().post(reverse("login"), {"username": self.w.adv.username, "password": PW}).status_code, 200)  # 로그인 실패(폼 다시)


class OperatorAdvertiserBase(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.client.force_login(self.w.admin)
        self.uid = self.w.adv.pk
        self.list = reverse("operator:advertiser_list")
        self.detail = reverse("operator:advertiser_detail", args=[self.uid])
        self.adjust_url = reverse("operator:advertiser_adjust", args=[self.uid])

    def adjust_fields(self, **over):
        """상세 화면의 조정 폼에서 한 번 쓰는 토큰을 꺼내 함께 보낸다(화면이 싣는 대로)."""
        html = self.client.get(self.detail).content.decode()
        once = re.search(r'name="once" value="([^"]+)"', html).group(1)
        return {"once": once, "amount": -1000, "note": "잘못 받은 과금 환원 정정", **over}

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
        self.assertRedirects(self.client.post(self.adjust_url, fields), self.detail, fetch_redirect_response=False)  # 새로 고침·뒤로 가기·두 번 누름
        self.assertContains(self.client.get(self.detail), "이미 처리했거나 오래된 요청입니다")
        self.assertEqual(self.balance(), 49_000)
        self.assertEqual(self.client.post(self.adjust_url, {"amount": -1000, "note": "토큰 없음"}).status_code, 302)
        self.assertEqual(self.balance(), 49_000)

    def test_ledger_pages_by_cursor(self):
        for i in range(50):
            billing.adjust(self.w.admin, self.uid, 1, f"조정 {i}", now=NOW)
        html = self.client.get(self.detail).content.decode()
        self.assertNotIn("가입 지급", html)  # 한 쪽은 50 줄(최신순)
        older = re.search(r'href="([^"]+)" rel="next"', html).group(1).replace("&amp;", "&")  # 같은 화면의 쿼리(`?before=…`)
        self.assertContains(self.client.get(self.detail + older), "가입 지급")
        self.assertEqual(self.client.get(self.detail + "?before=abc").status_code, 200)  # 틀린 커서는 첫 쪽
