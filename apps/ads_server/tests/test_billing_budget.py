import uuid
from datetime import date, datetime, timedelta, timezone

from django.test import TestCase, TransactionTestCase, override_settings

from billing import api
from billing.models import CampaignSpend, LedgerEntry
from tests.factories import DAY, NOW, make_advertiser

UTC = timezone.utc


def at(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


class BudgetDayTests(TestCase):
    def test_budget_day_boundary_default_utc(self):
        self.assertEqual(api.budget_day_of(at(2026, 10, 7, 0, 0, 0)), date(2026, 10, 7))  # 00:00:00Z 가 새 날
        self.assertEqual(api.budget_day_of(at(2026, 10, 6, 23, 59, 59)), date(2026, 10, 6))
        self.assertEqual(api.next_reset(at(2026, 10, 7, 12)), at(2026, 10, 8))  # KST 09:00 리셋
        self.assertEqual(api.next_reset(at(2026, 10, 7, 0, 0, 0)), at(2026, 10, 8))

    @override_settings(BUDGET_DAY_OFFSET_HOURS=9)
    def test_budget_day_offset_kst_midnight(self):
        self.assertEqual(api.budget_day_of(at(2026, 10, 7, 14, 59, 59)), date(2026, 10, 7))  # KST 23:59:59
        self.assertEqual(api.budget_day_of(at(2026, 10, 7, 15, 0, 0)), date(2026, 10, 8))  # KST 자정
        self.assertEqual(api.next_reset(at(2026, 10, 7, 20)), at(2026, 10, 8, 15))  # KST 자정 = 15:00Z

    def test_resets_at_is_in_the_future_and_within_a_day(self):
        for hour in (0, 5, 14, 23):
            now = at(2026, 10, 7, hour, 30)
            reset = api.next_reset(now)
            self.assertGreater(reset, now)
            self.assertLessEqual(reset - now, DAY)


class SpendTests(TestCase):
    def setUp(self):
        self.adv = make_advertiser()
        with override_settings(SIGNUP_GRANT_POINTS=1_000_000):
            api.grant_signup(self.adv, now=at(2026, 10, 1))
        self.camp, self.other = uuid.uuid4(), uuid.uuid4()
        self.instants = [at(2026, 10, 7, 1), at(2026, 10, 7, 14, 59, 59), at(2026, 10, 7, 15), at(2026, 10, 7, 23, 59, 59), at(2026, 10, 8, 0, 0, 1)]
        for i, t in enumerate(self.instants):
            api.charge_for_reaction(self.adv.pk, self.camp if i % 2 == 0 else self.other, "IMPRESSION", "IMPRESSION", 10 * (i + 1), f"r{i}", now=t)

    def expected_from_ledger(self):
        totals = {}
        for campaign_id, created_at, amount in LedgerEntry.objects.filter(entry_type="CHARGE").values_list("campaign_id", "created_at", "amount"):
            key = (campaign_id, api.budget_day_of(created_at))
            totals[key] = totals.get(key, 0) - amount
        return {k: v for k, v in totals.items() if v > 0}

    def stored(self):
        return {(s.campaign_id, s.budget_day): s.spent for s in CampaignSpend.objects.all()}

    def test_spent_today_resets_at_boundary(self):
        self.assertEqual(api.spend_today([self.camp, self.other], now=at(2026, 10, 7, 12)), {self.camp: 10 + 30, self.other: 20 + 40})
        self.assertEqual(api.spend_today([self.camp, self.other], now=at(2026, 10, 8, 0, 0, 0)), {self.camp: 50})  # 어제 몫 제외
        self.assertEqual(api.spend_today([self.camp], now=at(2026, 10, 9)), {})
        wallet = api.get_wallet(self.adv, now=at(2026, 10, 7, 12))
        self.assertEqual((wallet.spent_today, wallet.budget_day, wallet.resets_at), (10 + 20 + 30 + 40, date(2026, 10, 7), at(2026, 10, 8)))
        self.assertEqual(api.get_wallet(self.adv, now=at(2026, 10, 8, 1)).spent_today, 50)

    def test_recompute_matches_ledger_for_the_current_boundary(self):
        self.assertEqual(self.stored(), self.expected_from_ledger())
        CampaignSpend.objects.create(campaign_id=uuid.uuid4(), budget_day=date(2026, 1, 1), spent=999)  # 어긋난 파생값
        api.recompute_spend()
        self.assertEqual(self.stored(), self.expected_from_ledger())  # 오래된·틀린 행은 사라진다
        before = self.stored()
        api.recompute_spend()
        self.assertEqual(self.stored(), before)  # 멱등

    def test_budget_day_offset_change_then_recompute_matches_ledger(self):
        """경계를 UTC 자정 → KST 자정으로 바꾼 뒤 재계산하면 소진액이 원장의 새 경계 집계와 일치한다."""
        utc_view = self.stored()
        with override_settings(BUDGET_DAY_OFFSET_HOURS=9):
            api.recompute_spend()
            kst_view = self.stored()
            self.assertEqual(kst_view, self.expected_from_ledger())
            self.assertNotEqual(kst_view, utc_view)  # 경계가 바뀌었으니 날짜별 합이 달라진다
            self.assertEqual(sum(kst_view.values()), sum(utc_view.values()))  # 총합은 같다
            # KST 10/8 05:00 = 10/7 20:00Z: 새 경계에서는 15:00Z 이후 줄이 '오늘'이다
            self.assertEqual(api.spend_today([self.camp, self.other], now=at(2026, 10, 7, 20)), {self.camp: 30 + 50, self.other: 40})
        api.recompute_spend()  # 설정을 되돌리고 재계산하면 원래대로
        self.assertEqual(self.stored(), utc_view)


class RecomputeIsOneWriteTransactionTests(TransactionTestCase):
    def test_recompute_reads_the_ledger_inside_the_write_transaction(self):
        """원장 읽기가 트랜잭션 밖이면 그 사이에 커밋된 새 과금이 파생값에서 빠진다. (캠페인, 날)마다 읽기부터 교체까지 한 트랜잭션이어야 한다(경쟁은 test_recompute_race.py).
        키를 모으는 첫 읽기는 쓰기 전이라 트랜잭션 밖이어도 되고, 합계를 읽는 나머지는 모두 안이어야 한다."""
        from django.db import connection

        from billing import services

        seen = []
        real = services.LedgerEntry

        class Probe:
            class objects:  # noqa: N801
                @staticmethod
                def filter(*args, **kwargs):
                    seen.append(connection.in_atomic_block)  # TestCase 가 아니라서 바깥 트랜잭션이 없다: 서비스가 연 것만 보인다
                    return real.objects.filter(*args, **kwargs)

        adv = make_advertiser()
        api.grant_signup(adv, now=at(2026, 10, 1))
        api.charge_for_reaction(adv.pk, uuid.uuid4(), "IMPRESSION", "IMPRESSION", 10, "r1", now=at(2026, 10, 7, 1))
        services.LedgerEntry = Probe
        try:
            api.recompute_spend()
        finally:
            services.LedgerEntry = real
        self.assertGreaterEqual(len(seen), 2)
        self.assertTrue(all(seen[1:]), seen)  # 키 수집 이후의 원장 읽기는 모두 쓰기 트랜잭션 안
        self.assertEqual(CampaignSpend.objects.get().spent, 10)
