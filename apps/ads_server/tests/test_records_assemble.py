from django.test import TestCase

from campaigns import api as campaigns
from masters import api as masters
from records.assemble import assemble
from tests.factories import NOW, WHOLE, World, make_advertiser, png_file
from billing import api as billing



class AssembleTests(TestCase):
    def slot_view(self, w):
        return masters.get_slot(w.slot.slot_id)

    def test_assemble_maps_facts_policy_wallet_and_remaining_budget(self):
        w = World()
        billing.charge_for_reaction(w.adv.pk, w.campaign.campaign_id, "IMPRESSION", WHOLE, 1_200, "m:r1", now=NOW)
        candidates, by_creative = assemble(self.slot_view(w), NOW)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual((c.floor, c.base, c.cap, c.policy_version), (100, 200, 500, 1))
        self.assertEqual((c.bid_amount, c.bid_version, c.campaign_status, c.ad_group_enabled), (300, 1, "ACTIVE", True))
        self.assertEqual(c.wallet_balance, 50_000 - 1_200)
        self.assertEqual(c.remaining_daily_budget, 50_000 - 1_200)  # 일예산 - 오늘 소진
        self.assertEqual(by_creative[c.creative_id].title, "제목")

    def test_remaining_budget_never_negative(self):
        w = World()
        billing.charge_for_reaction(w.adv.pk, w.campaign.campaign_id, "IMPRESSION", WHOLE, 5_000, "m:r1", now=NOW)
        campaigns.update_campaign(w.adv, w.campaign.campaign_id, {"daily_budget": 100}, now=NOW)  # 이미 쓴 금액보다 작게 줄임
        self.assertEqual(assemble(self.slot_view(w), NOW)[0][0].remaining_daily_budget, 0)

    def test_assemble_query_count_independent_of_candidates(self):
        w = World()
        slot = self.slot_view(w)
        with self.assertNumQueries(3):  # 후보 사실, 잔액, 오늘 소진액(슬롯 정책 조회는 호출자 몫)
            self.assertEqual(len(assemble(slot, NOW)[0]), 1)
        # 광고주 25명이 같은 슬롯에 광고를 낸다
        for i in range(25):
            adv = make_advertiser()
            billing.grant_signup(adv, now=NOW)
            camp = campaigns.create_campaign(adv, f"c{i}", NOW, None, 1_000, now=NOW)
            group = campaigns.create_ad_group(adv, camp.campaign_id, f"g{i}", [w.slot.slot_id], bid_amount=200 + i, now=NOW)
            campaigns.create_creative(adv, group.ad_group_id, f"t{i}", "https://a.example", png_file((i, 2 * i % 256, 7)), now=NOW)
        with self.assertNumQueries(3):  # 후보가 1 → 26 이어도 질의 수는 같다
            self.assertEqual(len(assemble(slot, NOW)[0]), 26)

    def test_assemble_with_no_facts_returns_empty_without_extra_queries(self):
        w = World(with_creative=False)
        slot = self.slot_view(w)
        with self.assertNumQueries(1):  # 후보 사실 조회만. 잔액·소진액은 후보가 없으면 읽지 않는다
            self.assertEqual(assemble(slot, NOW), ([], {}))
