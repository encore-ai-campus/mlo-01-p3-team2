import unittest
from datetime import timedelta

from engine.api import DEFAULT_FILTERS, UnknownName, decide
from random import Random

from tests.engine_factory import NOW, cand, request


def run(*candidates, filters=DEFAULT_FILTERS):
    return decide(candidates, request(), Random(1), filters=filters)


class FilterTests(unittest.TestCase):
    def test_each_filter_rejects_with_reason(self):
        cases = {
            "campaign_not_active": dict(campaign_status="PAUSED"),
            "ad_group_disabled": dict(ad_group_enabled=False),
            "not_started": dict(period_start=NOW + timedelta(seconds=1)),
            "expired": dict(period_end=NOW),
            "below_floor": dict(bid_amount=9),
            "budget_exhausted": dict(remaining_daily_budget=29),
            "insufficient_balance": dict(wallet_balance=29),
        }
        for reason, kw in cases.items():
            result = run(cand(**kw))
            self.assertIsNone(result.selection.chosen, reason)
            self.assertEqual(result.rejected, {reason: 1}, reason)
            self.assertEqual(result.considered, 1)
        for status in ("SUSPENDED", "ENDED"):
            self.assertEqual(run(cand(campaign_status=status)).rejected, {"campaign_not_active": 1})

    def test_stale_active_campaign_past_end_is_rejected_by_period(self):
        """저장된 상태가 아직 ACTIVE 여도 기간이 지났으면 걸러진다(상태 갱신이 늦은 구간)."""
        self.assertEqual(run(cand(campaign_status="ACTIVE", period_end=NOW - timedelta(minutes=5))).rejected, {"expired": 1})

    def test_open_ended_campaign_passes_period(self):
        self.assertIsNotNone(run(cand(period_end=None)).selection.chosen)

    def test_budget_and_balance_boundary(self):
        self.assertIsNotNone(run(cand(remaining_daily_budget=30, wallet_balance=30)).selection.chosen)  # 같으면 통과
        self.assertEqual(run(cand(remaining_daily_budget=29)).rejected, {"budget_exhausted": 1})  # 1 모자라면 거절
        self.assertEqual(run(cand(wallet_balance=29)).rejected, {"insufficient_balance": 1})

    def test_budget_and_balance_use_applied_amount_not_bid(self):
        # 입찰 80 이지만 상한 50 으로 적용된다: 잔액·예산 50 이면 통과
        result = run(cand(bid_amount=80, cap=50, wallet_balance=50, remaining_daily_budget=50))
        self.assertEqual(result.selection.chosen.applied_amount, 50)

    def test_filter_order_first_failure_wins_and_counts_by_reason(self):
        both = cand(campaign_status="PAUSED", bid_amount=1)  # 상태와 하한 둘 다 걸리지만 먼저 걸린 상태로만 센다
        result = run(both, cand(bid_amount=1), cand(bid_amount=1), cand(), cand(wallet_balance=0))
        self.assertEqual(result.rejected, {"campaign_not_active": 1, "below_floor": 2, "insufficient_balance": 1})
        self.assertEqual(result.considered, 5)
        self.assertEqual(result.selection.trace["candidates"], 1)

    def test_filter_names_are_configurable_and_unknown_names_fail_fast(self):
        paused = cand(campaign_status="PAUSED")
        self.assertIsNotNone(run(paused, filters=("period", "floor", "budget", "balance")).selection.chosen)  # status 를 뺌
        with self.assertRaises(UnknownName):
            run(paused, filters=("status", "no-such-filter"))

    def test_floor_filter_is_required_when_budget_filters_are_used(self):
        with self.assertRaises(ValueError):  # 하한 미만 후보가 적용 금액 없이 남는 설정 오류
            run(cand(bid_amount=1), filters=("status", "period", "budget", "balance"))

    def test_candidate_for_another_slot_is_an_error(self):
        import uuid

        with self.assertRaises(ValueError):
            run(cand(slot_id=uuid.uuid4()))
