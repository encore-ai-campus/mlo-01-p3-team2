import unittest
import uuid
from random import Random

from engine.api import DEFAULT_POLICY, Selection, UnknownName, decide, register_policy, unregister_policy
from tests.support.engine_factory import cand, request
from tests.support.cases import Cases


def pick(candidates, seed=1, policy=DEFAULT_POLICY, **req):
    return decide(candidates, request(**req), Random(seed), policy=policy)


class WeightedByBidTests(Cases, unittest.TestCase):
    """상한 근접 가중 추첨(6-14, 설계 §4.3): 가중치 = (상한 − 하한) + 2 × (적용 금액 − 하한), 하한 = 상한이면 모두 1. 도우미 후보는 하한 10·상한 50."""

    def case_weights_grow_toward_the_cap_and_a_floor_bid_is_never_zero(self):
        at_floor, mid, at_cap, above_cap = cand(bid_amount=10), cand(bid_amount=30), cand(bid_amount=50), cand(bid_amount=80)
        expected = {at_floor.ad_group_id: 40, mid.ad_group_id: 80, at_cap.ad_group_id: 120, above_cap.ad_group_id: 120}  # 1 : 2 : 3 : 3
        seen = {}
        for seed in range(200):
            trace = pick([at_floor, mid, at_cap, above_cap], seed=seed).selection.trace
            self.assertEqual((trace["total"], trace["candidates"], trace["k"]), (360, 4, 2))
            self.assertLess(trace["draw"], trace["total"])
            seen[uuid.UUID(trace["picked"])] = trace["weight"]
        self.assertEqual(seen, expected)  # 하한에 있는 광고도 뽑힌다

    def case_a_slot_whose_floor_equals_its_cap_is_uniform(self):
        group = [cand(floor=50, cap=50, bid_amount=50), cand(floor=50, cap=50, bid_amount=90)]
        trace = pick(group).selection.trace
        self.assertEqual((trace["total"], trace["weight"]), (2, 1))
        rng = Random(20261014)
        first = sum(decide(group, request(), rng).selection.chosen.ad_group_id == min(group, key=lambda c: str(c.ad_group_id)).ad_group_id for _ in range(3000))
        self.assertLess(abs(first - 1500), 150)  # 반반 — 가중치 합이 작아도 난수 범위가 한쪽으로 쏠리지 않는다

    def case_the_trace_is_a_summary_that_gives_the_chosen_probability(self):
        result = pick([cand(bid_amount=10), cand(bid_amount=50)], seed=3)
        trace = result.selection.trace
        self.assertEqual(set(trace), {"policy", "candidates", "k", "total", "weight", "draw", "picked"})  # 후보 목록은 남기지 않는다
        self.assertEqual(trace["policy"], "weighted-by-bid/v1")
        self.assertEqual(trace["picked"], str(result.selection.chosen.ad_group_id))
        self.assertEqual(trace["weight"], 40 + 2 * (result.selection.chosen.applied_amount - 10))

    def case_frequencies_follow_the_weights(self):
        group = [cand(bid_amount=10), cand(bid_amount=30), cand(bid_amount=50)]  # 가중치 40 · 80 · 120 → 1/6 · 1/3 · 1/2
        rng = Random(20261014)
        counts = {c.ad_group_id: 0 for c in group}
        for _ in range(6000):
            counts[decide(group, request(), rng).selection.chosen.ad_group_id] += 1
        for c, expected in zip(group, (1000, 2000, 3000)):
            self.assertLess(abs(counts[c.ad_group_id] - expected), 200, counts)  # 표준편차 약 29 · 37 · 39

    def case_no_candidates_returns_none(self):
        result = pick([])
        self.assertIsNone(result.selection.chosen)
        self.assertEqual((result.considered, result.rejected), (0, {}))
        self.assertEqual(result.selection.trace, {"policy": "weighted-by-bid/v1", "candidates": 0})

    def case_the_draw_is_reproducible_with_a_seed_and_independent_of_input_order(self):
        group = [cand(bid_amount=b) for b in (10, 20, 30, 40, 50)]
        first = pick(group, seed=42).selection
        self.assertEqual(pick(group, seed=42).selection, first)
        self.assertEqual(pick(list(reversed(group)), seed=42).selection, first)
        others = {pick(group, seed=s).selection.chosen.ad_group_id for s in range(30)}
        self.assertGreater(len(others), 1)  # 시드가 다르면 다른 후보도 뽑힌다

    def case_subject_id_does_not_change_result(self):
        group = [cand(), cand(), cand(bid_amount=20)]
        base = pick(group, seed=7, subject_id=None).selection
        for subject in ("a", "b", "x" * 50):
            self.assertEqual(pick(group, seed=7, subject_id=subject).selection, base)

    def test_weighted_by_bid(self):
        self.run_cases()


class _FirstPolicy:
    name = "first/v1"

    def select(self, candidates, request, rng):
        return Selection(candidates[0] if candidates else None, {"policy": self.name, "note": "dummy"})


class PolicyRegistryTests(Cases, unittest.TestCase):
    def case_policy_swappable_by_name(self):
        register_policy(_FirstPolicy())
        self.addCleanup(unregister_policy, "first/v1")
        low, high = cand(bid_amount=12), cand(bid_amount=45)
        by_name = pick([low, high], policy="first/v1").selection
        self.assertEqual(by_name.chosen.ad_group_id, low.ad_group_id)  # 다른 알고리즘이 돌았다
        self.assertEqual(by_name.trace["policy"], "first/v1")
        self.assertEqual(pick([low, high]).selection.trace["policy"], DEFAULT_POLICY)  # 기본은 그대로
        self.assertEqual(set(vars(by_name)), {"chosen", "trace"})  # Selection 구조는 같다

    def case_unknown_policy_raises_even_without_candidates(self):
        with self.assertRaises(UnknownName):
            pick([], policy="no-such/v9")

    def case_duplicate_registration_rejected(self):
        with self.assertRaises(ValueError):
            register_policy(type("Dup", (), {"name": DEFAULT_POLICY, "select": None})())

    def test_policy_registry(self):
        self.run_cases()
