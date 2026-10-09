"""Step 1 합격 증거(계획 §6.7): HTTP 없이 서비스 `api` 만으로 한 광고주의 전 과정이 돈다.

가입(지급) → 캠페인·광고그룹·소재·입찰 → 결정 저장. 그리고 입찰·정책·소재를 고치고 캠페인을 중단·종료해도 과거 결정은 그대로다.
"""
from random import Random

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from billing import api as billing
from campaigns import api as campaigns
from foundation.models import AuditLog, User
from masters import api as masters
from records import api as records
from records.models import Decision
from tests.factories import DAY, NOW, PW, make_admin, png_file

IMP = "IMPRESSION"


def signup(username, ip):
    response = Client().post(
        reverse("signup"),
        {"username": username, "password": PW, "password_confirm": PW, "nickname": "광고주", "class_label": "1반"},
        REMOTE_ADDR=ip,
    )
    assert response.status_code == 302, response.status_code
    return User.objects.get(username=username)


class Step1ScenarioTests(TestCase):
    def test_full_flow_through_services_only(self):
        # 1. 관리자: 매체 1·슬롯(노출 A·B·C, 클릭 D)·정책 A 10~50, B 10~20, C 40~100
        admin = make_admin()
        media = masters.create_media(admin, "메타버스")
        slots = {
            name: masters.create_slot(admin, media.media_id, name, unit, floor, base, cap, "초기 정책")
            for name, unit, floor, base, cap in (("A", IMP, 10, 20, 50), ("B", IMP, 10, 15, 20), ("C", IMP, 40, 50, 100), ("D", "CLICK", 5, 8, 30))
        }
        sid = {name: s.slot_id for name, s in slots.items()}

        # 2. 광고주 두 명 가입: 각각 50,000 지급, 가입·지급 감사 로그
        adv1, adv2 = signup("scenario_one", "10.7.0.1"), signup("scenario_two", "10.7.0.2")
        for adv in (adv1, adv2):
            self.assertEqual(billing.get_wallet(adv, now=NOW).balance, 50_000)
            self.assertEqual(AuditLog.objects.filter(actor_id=adv.pk, action__in=["account.signup", "billing.signup_grant"]).count(), 2)

        # 3. 광고주 1: 캠페인 → 광고그룹(A·B·C) 입찰 30 → 소재(실제 PNG). 광고주 2: 입찰 25
        def launch(adv, name, bid, color):
            camp = campaigns.create_campaign(adv, f"{name} 캠페인", NOW - DAY, NOW + 30 * DAY, 5_000, now=NOW)
            group = campaigns.create_ad_group(adv, camp.campaign_id, f"{name} 그룹", IMP, [sid["A"], sid["B"], sid["C"]], bid_amount=bid, now=NOW)
            creative = campaigns.create_creative(adv, group.ad_group_id, f"{name} 광고", f"https://{name}.example/landing", png_file(color), now=NOW)
            return camp, group, creative

        camp1, group1, creative1 = launch(adv1, "one", 30, (200, 30, 30))
        camp2, group2, creative2 = launch(adv2, "two", 25, (30, 30, 200))
        click_group = campaigns.create_ad_group(adv1, camp1.campaign_id, "클릭 그룹", "CLICK", [sid["D"]], bid_amount=10, now=NOW)
        campaigns.create_creative(adv1, click_group.ad_group_id, "클릭 광고", "https://one.example/click", png_file((9, 9, 9)), now=NOW)
        with self.assertRaises(campaigns.UnitMismatch):  # 단위가 섞인 광고그룹은 만들 수 없다
            campaigns.create_ad_group(adv1, camp1.campaign_id, "섞임", IMP, [sid["A"], sid["D"]], now=NOW)

        def decide(slot, seed=1, now=NOW):
            return records.decide(media.media_id, sid[slot], subject_id="learner-7", now=now, rng=Random(seed))

        # 4. 슬롯별 결과: A 는 30 vs 25 로 광고주 1(적용 30), B 는 상한 20 으로 둘 다 20(동점), C 는 하한 40 이라 둘 다 제외
        on_a = decide("A")
        self.assertEqual((on_a.chosen.campaign_id, on_a.chosen.applied_amount, on_a.chosen.bid_amount), (camp1.campaign_id, 30, 30))
        on_c = decide("C")
        self.assertIsNone(on_c.chosen)
        self.assertEqual((on_c.candidate_count, on_c.rejected_counts), (2, {"below_floor": 2}))
        winners = set()
        for seed in range(40):
            on_b = decide("B", seed)
            self.assertEqual(on_b.chosen.applied_amount, 20)
            winners.add(on_b.chosen.campaign_id)
        self.assertEqual(winners, {camp1.campaign_id, camp2.campaign_id})  # 동점이면 두 광고주가 고르게 뽑힌다
        self.assertEqual(decide("D").chosen.pricing_unit, "CLICK")  # 슬롯 단위에 맞는 광고그룹만

        # 노출 한 건 과금: 지갑·일 소진액·원장
        charge = billing.charge_for_reaction(adv1.pk, camp1.campaign_id, IMP, IMP, on_a.chosen.applied_amount, f"{media.media_id}:reaction-1", now=NOW)
        self.assertEqual((charge.charged, billing.get_wallet(adv1, now=NOW).balance, billing.get_wallet(adv1, now=NOW).spent_today), (30, 49_970, 30))
        self.assertIsNone(billing.charge_for_reaction(adv1.pk, camp1.campaign_id, "CLICK", IMP, 30, "x:y", now=NOW))  # 단위가 다른 반응은 과금 없음

        # 5. 정책·입찰·소재를 고치고 중단해도 첫 결정은 그대로, 중단된 캠페인의 이미지는 서빙 404
        saved = records.get_decision(media.media_id, on_a.decision_id)
        raw = list(Decision.objects.filter(decision_id=on_a.decision_id).values())
        campaigns.add_bid(adv1, group1.ad_group_id, 90, expected_version=1, now=NOW)
        masters.add_policy_version(admin, sid["A"], 1, 2, 3, "대폭 변경", expected_version=1)
        campaigns.update_creative(adv1, creative1.creative_id, {"title": "다른 제목"}, now=NOW)
        campaigns.suspend_campaign(admin, camp1.campaign_id, "부적절", now=NOW)
        with override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable"):
            self.assertEqual(Client().get(f"/assets/{creative1.image_name}").status_code, 404)  # 중단 즉시
            self.assertEqual(Client().get(f"/assets/{creative2.image_name}").status_code, 200)  # 다른 광고주 이미지는 그대로
        self.assertEqual(records.get_decision(media.media_id, on_a.decision_id), saved)
        self.assertEqual(list(Decision.objects.filter(decision_id=on_a.decision_id).values()), raw)
        self.assertEqual(saved.chosen.title, "one 광고")
        after = decide("B")
        self.assertEqual(after.chosen.campaign_id, camp2.campaign_id)  # 중단된 광고주 1 은 후보에서 빠진다

        # 6. 광고주 2 의 조기 종료: 모든 쓰기가 ended, 이후 결정에서 제외
        campaigns.end_campaign(adv2, camp2.campaign_id, now=NOW)
        for write in (
            lambda: campaigns.update_campaign(adv2, camp2.campaign_id, {"name": "x"}, now=NOW),
            lambda: campaigns.add_bid(adv2, group2.ad_group_id, 99, expected_version=1, now=NOW),
            lambda: campaigns.update_creative(adv2, creative2.creative_id, {"title": "x"}, now=NOW),
        ):
            with self.assertRaises(campaigns.CampaignEnded):
                write()
        none_left = decide("B")
        self.assertIsNone(none_left.chosen)
        self.assertEqual(none_left.candidate_count, 0)

        # 7. 정합성: 잔액 = 원장 합계, 감사 로그에 관리자·광고주 행위가 남음
        self.assertEqual(billing.check_ledger(quiescent=True), [])
        call_command("check_ledger", quiescent=True)
        seen = set(AuditLog.objects.values_list("action", flat=True))
        for action in ("masters.slot_created", "masters.policy_added", "campaign.suspended", "campaign.ended_early", "bid.added", "creative.created"):
            self.assertIn(action, seen)
