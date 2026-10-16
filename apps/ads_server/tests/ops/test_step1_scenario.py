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
from tests.support.factories import DAY, NOW, PW, SHARES, make_admin, png_file

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
        # 1. 관리자: 매체 1·슬롯 A·B·C·D·정책 A 100~500, B 100~200, C 400~1,000(비율은 모두 노출 98% — 과금 단위는 6-10d 에 없어졌다)
        admin = make_admin()
        media = masters.create_media(admin, "메타버스")
        slots = {
            name: masters.create_slot(admin, media.media_id, name, floor, base, cap, "초기 정책", audience="individual", **SHARES)
            for name, floor, base, cap in (("A", 100, 200, 500), ("B", 100, 150, 200), ("C", 400, 500, 1_000), ("D", 100, 150, 300))
        }
        sid = {name: s.slot_id for name, s in slots.items()}

        # 2. 광고주 두 명 가입: 각각 50,000 지급, 가입·지급 감사 로그
        adv1, adv2 = signup("scenario_one", "10.7.0.1"), signup("scenario_two", "10.7.0.2")
        for adv in (adv1, adv2):
            self.assertEqual(billing.get_wallet(adv, now=NOW).balance, 50_000)
            self.assertEqual(AuditLog.objects.filter(actor_id=adv.pk, action__in=["account.signup", "billing.signup_grant"]).count(), 2)

        # 3. 광고주 1: 캠페인 → 광고그룹(A·B·C) 입찰 300 → 소재(실제 PNG). 광고주 2: 입찰 250
        def launch(adv, name, bid, color):
            camp = campaigns.create_campaign(adv, f"{name} 캠페인", NOW - DAY, None, 5_000, now=NOW)  # 무기한: 아래 /assets/ 는 실제 시계로 판정한다(6-16b)
            group = campaigns.create_ad_group(adv, camp.campaign_id, f"{name} 그룹", [sid["A"], sid["B"], sid["C"]], bid_amount=bid, now=NOW)
            creative = campaigns.create_creative(adv, group.ad_group_id, f"{name} 광고", f"https://{name}.example/landing", png_file(color), now=NOW)
            return camp, group, creative

        camp1, group1, creative1 = launch(adv1, "one", 300, (200, 30, 30))
        camp2, group2, creative2 = launch(adv2, "two", 250, (30, 30, 200))
        click_group = campaigns.create_ad_group(adv1, camp1.campaign_id, "클릭 그룹", [sid["D"]], bid_amount=100, now=NOW)
        campaigns.create_creative(adv1, click_group.ad_group_id, "클릭 광고", "https://one.example/click", png_file((9, 9, 9)), now=NOW)

        def decide(slot, seed=1, now=NOW):
            return records.decide(media.media_id, sid[slot], subject_id="learner-7", now=now, rng=Random(seed))

        # 4. 슬롯별 결과(가중 추첨, 6-14): A 는 300 vs 250 — 둘 다 나갈 수 있고 이 시드에서는 광고주 1(적용 300), B 는 상한 200 으로 둘 다 200(같은 확률), C 는 하한 400 이라 둘 다 제외
        on_a = decide("A")
        self.assertEqual((on_a.chosen.campaign_id, on_a.chosen.applied_amount, on_a.chosen.bid_amount), (camp1.campaign_id, 300, 300))
        on_c = decide("C")
        self.assertIsNone(on_c.chosen)
        self.assertEqual((on_c.candidate_count, on_c.rejected_counts), (2, {"below_floor": 2}))
        winners = set()
        for seed in range(40):
            on_b = decide("B", seed)
            self.assertEqual(on_b.chosen.applied_amount, 200)
            winners.add(on_b.chosen.campaign_id)
        self.assertEqual(winners, {camp1.campaign_id, camp2.campaign_id})  # 같은 적용 금액이면 두 광고주가 같은 확률로 뽑힌다
        self.assertEqual(decide("D").chosen.ad_group_id, click_group.ad_group_id)  # D 에 놓인 광고는 클릭 그룹뿐이다

        # 노출·클릭 한 건씩 과금(결정에 남긴 비율로): 지갑·일 소진액·원장
        shares = on_a.chosen.charge_shares
        self.assertEqual(shares, {"IMPRESSION": 98, "CLICK": 1, "CONVERSION": 1})
        charge = billing.charge_for_reaction(adv1.pk, camp1.campaign_id, IMP, shares, on_a.chosen.applied_amount, f"{media.media_id}:reaction-1", now=NOW)
        click = billing.charge_for_reaction(adv1.pk, camp1.campaign_id, "CLICK", shares, on_a.chosen.applied_amount, f"{media.media_id}:reaction-2", now=NOW)
        wallet = billing.get_wallet(adv1, now=NOW)
        self.assertEqual((charge.charged, click.charged, wallet.balance, wallet.spent_today), (294, 3, 49_703, 297))

        # 5. 정책·입찰·소재를 고치고 중단해도 첫 결정은 그대로, 중단된 캠페인의 이미지는 서빙 404
        saved = records.get_decision(media.media_id, on_a.decision_id)
        raw = list(Decision.objects.filter(decision_id=on_a.decision_id).values())
        campaigns.add_bid(adv1, group1.ad_group_id, 900, expected_version=1, now=NOW)
        masters.add_policy_version(admin, sid["A"], 400, 500, 600, "대폭 변경", expected_version=1, impression_share=1, click_share=1, conversion_share=98)
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
            lambda: campaigns.update_ad_group(adv2, group2.ad_group_id, {"name": "x"}, now=NOW),
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
