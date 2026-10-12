import unittest
import uuid
from random import Random

from engine.api import DEFAULT_POLICY, Selection, UnknownName, decide, register_policy, unregister_policy
from tests.engine_factory import SLOT, cand, request


def pick(candidates, seed=1, policy=DEFAULT_POLICY, **req):
    return decide(candidates, request(**req), Random(seed), policy=policy)


class HighestBidTests(unittest.TestCase):
    def test_highest_bid_picks_max_applied_amount(self):
        low, mid, high = cand(bid_amount=15), cand(bid_amount=30), cand(bid_amount=45)
        result = pick([low, mid, high])
        self.assertEqual(result.selection.chosen.ad_group_id, high.ad_group_id)
        self.assertEqual(result.selection.chosen.applied_amount, 45)
        self.assertEqual(result.selection.trace["policy"], "highest-bid/v1")
        self.assertEqual(result.selection.trace["tied"], [str(high.ad_group_id)])

    def test_bids_above_cap_tie_at_cap(self):
        a, b = cand(bid_amount=80, cap=50), cand(bid_amount=500, cap=50)  # 둘 다 상한 50 → 동점
        trace = pick([a, b]).selection.trace
        self.assertEqual(trace["max_applied_amount"], 50)
        self.assertEqual(sorted(trace["tied"]), sorted([str(a.ad_group_id), str(b.ad_group_id)]))
        self.assertIn(trace["picked"], trace["tied"])

    def test_below_floor_bid_never_beats_an_eligible_one(self):
        eligible, excluded = cand(bid_amount=12), cand(bid_amount=9)
        self.assertEqual(pick([excluded, eligible]).selection.chosen.ad_group_id, eligible.ad_group_id)

    def test_no_candidates_returns_none(self):
        result = pick([])
        self.assertIsNone(result.selection.chosen)
        self.assertEqual((result.considered, result.rejected), (0, {}))
        self.assertEqual(result.selection.trace["policy"], "highest-bid/v1")

    def test_tie_break_reproducible_with_seed_and_independent_of_input_order(self):
        group = [cand() for _ in range(5)]
        first = pick(group, seed=42).selection.chosen.ad_group_id
        self.assertEqual(pick(group, seed=42).selection.chosen.ad_group_id, first)
        self.assertEqual(pick(list(reversed(group)), seed=42).selection.chosen.ad_group_id, first)
        others = {pick(group, seed=s).selection.chosen.ad_group_id for s in range(30)}
        self.assertGreater(len(others), 1)  # 시드가 다르면 다른 후보도 뽑힌다

    def test_tie_break_is_uniform(self):
        group = [cand() for _ in range(3)]
        rng = Random(20261007)
        counts = {c.ad_group_id: 0 for c in group}
        for _ in range(3000):
            counts[decide(group, request(), rng).selection.chosen.ad_group_id] += 1
        for n in counts.values():
            self.assertTrue(850 <= n <= 1150, counts)  # 기대 1000, 표준편차 약 26

    def test_subject_id_does_not_change_result(self):
        group = [cand(), cand(), cand(bid_amount=20)]
        base = pick(group, seed=7, subject_id=None).selection
        for subject in ("a", "b", "x" * 50):
            self.assertEqual(pick(group, seed=7, subject_id=subject).selection, base)


class _FirstPolicy:
    name = "first/v1"

    def select(self, candidates, request, rng):
        return Selection(candidates[0] if candidates else None, {"policy": self.name, "note": "dummy"})


class PolicyRegistryTests(unittest.TestCase):
    def test_policy_swappable_by_name(self):
        register_policy(_FirstPolicy())
        self.addCleanup(unregister_policy, "first/v1")
        low, high = cand(bid_amount=12), cand(bid_amount=45)
        by_name = pick([low, high], policy="first/v1").selection
        self.assertEqual(by_name.chosen.ad_group_id, low.ad_group_id)  # 다른 알고리즘이 돌았다
        self.assertEqual(by_name.trace["policy"], "first/v1")
        self.assertEqual(pick([low, high]).selection.chosen.ad_group_id, high.ad_group_id)  # 기본은 그대로
        self.assertEqual(set(vars(by_name)), {"chosen", "trace"})  # Selection 구조는 같다

    def test_unknown_policy_raises_even_without_candidates(self):
        with self.assertRaises(UnknownName):
            pick([], policy="no-such/v9")

    def test_duplicate_registration_rejected(self):
        with self.assertRaises(ValueError):
            register_policy(type("Dup", (), {"name": "highest-bid/v1", "select": None})())

    def test_slot_constant_sanity(self):
        self.assertIsInstance(SLOT, uuid.UUID)
