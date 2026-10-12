import dataclasses
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from engine.api import AdRequest, Eligible, effect_of, is_expired
from tests.engine_factory import NOW, SLOT, cand


class EffectTests(unittest.TestCase):
    def test_effect_table_design_example(self):
        """설계 §4.6: 입찰 30 → 슬롯 A(10~50)는 30, B(10~20)는 20(상한), C(40~100)는 제외."""
        a, b, c = effect_of(30, 10, 50), effect_of(30, 10, 20), effect_of(30, 40, 100)
        self.assertEqual((a.eligible, a.applied_amount, a.reason), (True, 30, "within_range"))
        self.assertEqual((b.eligible, b.applied_amount, b.reason), (True, 20, "capped_at_cap"))
        self.assertEqual((c.eligible, c.applied_amount, c.reason), (False, None, "below_floor"))

    def test_effect_boundaries(self):
        self.assertEqual(effect_of(10, 10, 50).applied_amount, 10)  # 하한과 같으면 노출
        self.assertEqual(effect_of(50, 10, 50).applied_amount, 50)  # 상한과 같으면 그대로
        self.assertEqual(effect_of(51, 10, 50).applied_amount, 50)  # 상한 + 1 → 상한
        self.assertFalse(effect_of(9, 10, 50).eligible)  # 하한 - 1 → 제외
        self.assertEqual(effect_of(5, 5, 5).applied_amount, 5)  # 하한 = 상한

    def test_effect_rejects_non_integers(self):
        for bad in (1.5, True, "30", None):
            with self.assertRaises(TypeError, msg=bad):
                effect_of(bad, 10, 50)
        with self.assertRaises(ValueError):
            effect_of(-1, 10, 50)


class IsExpiredTests(unittest.TestCase):
    def test_is_expired_boundaries(self):
        self.assertTrue(is_expired(NOW, NOW))  # 종료 시각은 미포함: 같으면 종료
        self.assertTrue(is_expired(NOW - timedelta(seconds=1), NOW))
        self.assertFalse(is_expired(NOW + timedelta(seconds=1), NOW))
        self.assertFalse(is_expired(None, NOW))  # 무기한


class TypeTests(unittest.TestCase):
    def test_types_reject_bad_values(self):
        naive = datetime(2026, 10, 7, 12, 0, 0)
        kst = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        bad = [
            dict(bid_amount=30.0), dict(bid_amount=True), dict(bid_amount=-1), dict(floor=1.5), dict(wallet_balance="1"),
            dict(remaining_daily_budget=None), dict(bid_version=0), dict(policy_version=0),
            dict(floor=30, base=20, cap=50), dict(base=60), dict(pricing_unit="DAILY"), dict(campaign_status="DONE"),
            dict(ad_group_enabled=1), dict(period_start=naive), dict(period_end=naive), dict(bid_created_at=kst),
            dict(campaign_id="not-a-uuid"), dict(slot_id=None),
        ]
        for kw in bad:
            with self.assertRaises((TypeError, ValueError), msg=kw):
                cand(**kw)
        for kw in (dict(slot_id="x"), dict(now=naive), dict(now=kst)):
            with self.assertRaises((TypeError, ValueError), msg=kw):
                AdRequest(**{"slot_id": SLOT, "now": NOW, **kw})

    def test_types_are_immutable_and_period_end_may_be_none(self):
        c = cand(period_end=None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            c.bid_amount = 99
        e = Eligible.of(c, 25)
        self.assertEqual((e.applied_amount, e.bid_amount, e.ad_group_id), (25, c.bid_amount, c.ad_group_id))
        with self.assertRaises(ValueError):
            Eligible.of(c, 0)  # 적용 금액은 1 이상

    def test_request_subject_is_optional(self):
        self.assertIsNone(AdRequest(slot_id=SLOT, now=NOW).subject_id)
        self.assertIsInstance(uuid.uuid4(), uuid.UUID)
