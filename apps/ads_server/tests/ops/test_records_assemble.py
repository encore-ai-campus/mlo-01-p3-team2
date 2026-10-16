from django.test import TestCase

from campaigns import api as campaigns
from masters import api as masters
from records.assemble import assemble
from tests.support.factories import NOW, WHOLE, World, make_advertiser, png_file
from billing import api as billing
from tests.support.cases import Cases



class AssembleTests(Cases, TestCase):
    def slot_view(self, w):
        return masters.get_slot(w.slot.slot_id)

    def case_assemble_maps_facts_policy_wallet_and_remaining_budget(self):
        w = World()
        billing.charge_for_reaction(w.adv.pk, w.campaign.campaign_id, "IMPRESSION", WHOLE, 1_200, "m:r1", now=NOW)
        candidates, by_group = assemble(self.slot_view(w), NOW)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual((c.floor, c.cap, c.policy_version), (100, 500, 1))
        self.assertEqual((c.bid_amount, c.bid_version, c.campaign_status, c.ad_group_enabled), (300, 1, "ACTIVE", True))
        self.assertEqual(c.wallet_balance, 50_000 - 1_200)
        self.assertEqual(c.remaining_daily_budget, 50_000 - 1_200)  # 일예산 - 오늘 소진
        self.assertEqual(by_group[c.ad_group_id].title, "제목")

    def case_each_candidate_carries_its_own_advertisers_balance_and_campaigns_budget(self):
        """6-18b(R28): 광고주가 둘이면 후보마다 그 광고주의 잔액·그 캠페인의 남은 예산이다 — 첫 후보의 값을 모두에 쓰면 한쪽만 잔액 부족·예산 소진인 경우를 거르지 못한다."""
        w = World()
        other = make_advertiser()
        billing.grant_signup(other, now=NOW)
        camp = campaigns.create_campaign(other, "c2", NOW, None, 1_000, now=NOW)
        group = campaigns.create_ad_group(other, camp.campaign_id, "g2", [w.slot.slot_id], bid_amount=200, now=NOW)
        campaigns.create_creative(other, group.ad_group_id, "t2", "https://b.example", png_file((9, 9, 9)), now=NOW)
        billing.charge_for_reaction(other.pk, camp.campaign_id, "IMPRESSION", WHOLE, 900, "m:r2", now=NOW)
        got = {c.ad_group_id: (c.wallet_balance, c.remaining_daily_budget) for c in assemble(self.slot_view(w), NOW)[0]}
        self.assertEqual(got, {w.group.ad_group_id: (50_000, 50_000), group.ad_group_id: (50_000 - 900, 1_000 - 900)})

    def case_remaining_budget_never_negative(self):
        w = World()
        billing.charge_for_reaction(w.adv.pk, w.campaign.campaign_id, "IMPRESSION", WHOLE, 5_000, "m:r1", now=NOW)
        campaigns.update_campaign(w.adv, w.campaign.campaign_id, {"daily_budget": 100}, now=NOW)  # 이미 쓴 금액보다 작게 줄임
        self.assertEqual(assemble(self.slot_view(w), NOW)[0][0].remaining_daily_budget, 0)

    def case_assemble_query_count_independent_of_candidates(self):
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

    def case_assemble_with_no_facts_returns_empty_without_extra_queries(self):
        w = World(with_creative=False)
        slot = self.slot_view(w)
        with self.assertNumQueries(1):  # 후보 사실 조회만. 잔액·소진액은 후보가 없으면 읽지 않는다
            self.assertEqual(assemble(slot, NOW), ([], {}))

    def test_assemble(self):
        self.run_cases()
