import uuid
from datetime import date

from django.test import TestCase, override_settings

from billing import api
from billing.models import LedgerEntry
from tests.support.factories import DAY, WHOLE, make_advertiser, utc
from tests.support.cases import Cases


class BudgetDayTests(Cases, TestCase):
    def case_budget_day_boundary_default_utc(self):
        self.assertEqual(api.budget_day_of(utc(2026, 10, 7, 0, 0, 0)), date(2026, 10, 7))  # 00:00:00Z 가 새 날
        self.assertEqual(api.budget_day_of(utc(2026, 10, 6, 23, 59, 59)), date(2026, 10, 6))
        self.assertEqual(api.next_reset(utc(2026, 10, 7, 12)), utc(2026, 10, 8))  # KST 09:00 리셋
        self.assertEqual(api.next_reset(utc(2026, 10, 7, 0, 0, 0)), utc(2026, 10, 8))

    @override_settings(BUDGET_DAY_OFFSET_HOURS=9)
    def case_budget_day_offset_kst_midnight(self):
        self.assertEqual(api.budget_day_of(utc(2026, 10, 7, 14, 59, 59)), date(2026, 10, 7))  # KST 23:59:59
        self.assertEqual(api.budget_day_of(utc(2026, 10, 7, 15, 0, 0)), date(2026, 10, 8))  # KST 자정
        self.assertEqual(api.next_reset(utc(2026, 10, 7, 20)), utc(2026, 10, 8, 15))  # KST 자정 = 15:00Z

    def case_resets_at_is_in_the_future_and_within_a_day(self):
        for hour in (0, 5, 14, 23):
            now = utc(2026, 10, 7, hour, 30)
            reset = api.next_reset(now)
            self.assertGreater(reset, now)
            self.assertLessEqual(reset - now, DAY)

    def test_budget_day(self):
        self.run_cases()


class SpendTests(Cases, TestCase):
    def setUp(self):
        self.adv = make_advertiser()
        with override_settings(SIGNUP_GRANT_POINTS=1_000_000):
            api.grant_signup(self.adv, now=utc(2026, 10, 1))
        self.camp, self.other = uuid.uuid4(), uuid.uuid4()
        self.instants = [utc(2026, 10, 7, 1), utc(2026, 10, 7, 14, 59, 59), utc(2026, 10, 7, 15), utc(2026, 10, 7, 23, 59, 59), utc(2026, 10, 8, 0, 0, 1)]
        for i, t in enumerate(self.instants):
            api.charge_for_reaction(self.adv.pk, self.camp if i % 2 == 0 else self.other, "IMPRESSION", WHOLE, 10 * (i + 1), f"r{i}", now=t)

    def expected_from_ledger(self):
        totals = {}
        for campaign_id, created_at, amount in LedgerEntry.objects.filter(entry_type="CHARGE").values_list("campaign_id", "created_at", "amount"):
            key = (campaign_id, api.budget_day_of(created_at))
            totals[key] = totals.get(key, 0) - amount
        return {k: v for k, v in totals.items() if v > 0}

    def by_day(self):
        return api.spend_by_day([self.camp, self.other], date(2026, 10, 1), date(2026, 10, 10))

    def expected_by_day(self):
        totals = {}
        for (_, day), spent in self.expected_from_ledger().items():
            totals[day] = totals.get(day, 0) + spent
        return totals

    def case_spent_today_resets_at_boundary(self):
        self.assertEqual(api.spend_today([self.camp, self.other], now=utc(2026, 10, 7, 12)), {self.camp: 10 + 30, self.other: 20 + 40})
        self.assertEqual(api.spend_today([self.camp, self.other], now=utc(2026, 10, 8, 0, 0, 0)), {self.camp: 50})  # 어제 몫 제외
        self.assertEqual(api.spend_today([self.camp], now=utc(2026, 10, 9)), {})
        wallet = api.get_wallet(self.adv, now=utc(2026, 10, 7, 12))
        self.assertEqual((wallet.spent_today, wallet.budget_day, wallet.resets_at), (10 + 20 + 30 + 40, date(2026, 10, 7), utc(2026, 10, 8)))
        self.assertEqual(api.get_wallet(self.adv, now=utc(2026, 10, 8, 1)).spent_today, 50)

    def case_spend_is_the_ledger_sum_of_each_budget_day(self):
        """6-16f: 캠페인 일 소진액은 따로 쌓지 않고 원장의 과금 줄을 예산 일로 묶어 센다 — 어긋날 파생값이 없다."""
        self.assertEqual(self.by_day(), self.expected_by_day())
        per_campaign = {}
        for (campaign_id, _), spent in self.expected_from_ledger().items():
            per_campaign[campaign_id] = per_campaign.get(campaign_id, 0) + spent
        self.assertEqual(api.spend_by_campaign([self.camp, self.other], date(2026, 10, 1), date(2026, 10, 10)), per_campaign)

    def case_changing_the_budget_day_offset_needs_no_recompute(self):
        """경계를 UTC 자정 → KST 자정으로 바꾸면 소진액이 바로 새 경계로 묶인다(전에는 재계산 명령을 돌려야 했다)."""
        utc_view = self.by_day()
        with override_settings(BUDGET_DAY_OFFSET_HOURS=9):
            kst_view = self.by_day()
            self.assertEqual(kst_view, self.expected_by_day())
            self.assertNotEqual(kst_view, utc_view)  # 경계가 바뀌었으니 날짜별 합이 달라진다
            self.assertEqual(sum(kst_view.values()), sum(utc_view.values()))  # 총합은 같다
            # KST 10/8 05:00 = 10/7 20:00Z: 새 경계에서는 15:00Z 이후 줄이 '오늘'이다
            self.assertEqual(api.spend_today([self.camp, self.other], now=utc(2026, 10, 7, 20)), {self.camp: 30 + 50, self.other: 40})
        self.assertEqual(self.by_day(), utc_view)  # 되돌리면 그대로

    def test_spend(self):
        self.run_cases()
