import threading
import uuid

from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings, tag

from billing import api
from billing.models import CampaignSpend, LedgerEntry
from foundation.errors import InvalidRequest, NotFound
from tests.factories import DAY, NOW, make_advertiser

IMPRESSION, CLICK = "IMPRESSION", "CLICK"


def funded(points=10_000):
    adv = make_advertiser()
    with override_settings(SIGNUP_GRANT_POINTS=points):
        api.grant_signup(adv, now=NOW)
    return adv


def charge(adv, amount, ref, campaign, rtype=IMPRESSION, unit=IMPRESSION, now=NOW):
    return api.charge_for_reaction(adv.pk, campaign, rtype, unit, amount, ref, now=now)


@tag("security")
class ChargeTests(TestCase):
    def test_charge_idempotent_by_reaction_ref(self):
        adv, camp = funded(), uuid.uuid4()
        first = charge(adv, 40, "m1:r1", camp)
        again = charge(adv, 40, "m1:r1", camp)
        self.assertFalse(first.duplicate)
        self.assertTrue(again.duplicate)
        self.assertEqual((again.entry.entry_id, again.charged), (first.entry.entry_id, 40))  # 처음 결과 그대로
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 9_960)  # 한 번만 차감
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 1)
        self.assertEqual(api.spend_today([camp], now=NOW), {camp: 40})  # 소진액도 한 번만
        self.assertEqual(charge(adv, 999, "m1:r1", camp).charged, 40)  # 금액이 달라도 처음 결과(재전송은 같은 내용이어야 한다는 것은 Step 2 의 몫)
        self.assertEqual(api.check_ledger(), [])

    def test_charge_policy_by_unit(self):
        adv, camp = funded(), uuid.uuid4()
        self.assertIsNone(charge(adv, 40, "r-click", camp, rtype=CLICK, unit=IMPRESSION))  # 단위가 다른 반응은 과금 없음
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 0)
        hit = charge(adv, 55, "r-imp", camp, rtype=CLICK, unit=CLICK)
        self.assertEqual((hit.charged, hit.entry.charge_policy), (55, "by-unit/v1"))  # 정책 이름 기록
        self.assertEqual(hit.entry.campaign_id, camp)
        conversion = charge(adv, 9, "r-conv", camp, rtype="CONVERSION", unit="CONVERSION")
        self.assertEqual(conversion.charged, 9)

    def test_charge_policy_swappable_by_setting(self):
        class FlatOne:
            name = "flat-one/v1"

            def amount_for(self, reaction_type, pricing_unit, applied_amount):
                return 1

        api.register_charge_policy(FlatOne())
        self.addCleanup(api.unregister_charge_policy, "flat-one/v1")
        adv, camp = funded(), uuid.uuid4()
        with override_settings(BILLING_CHARGE_POLICY="flat-one/v1"):
            result = charge(adv, 500, "flat-r1", camp, rtype=CLICK, unit=IMPRESSION)  # 기본 정책이면 과금 없는 조합
        self.assertEqual((result.charged, result.entry.charge_policy), (1, "flat-one/v1"))
        with override_settings(BILLING_CHARGE_POLICY="no-such/v9"):
            with self.assertRaises(api.UnknownChargePolicy):
                charge(adv, 5, "x", camp)
        with self.assertRaises(ValueError):
            api.register_charge_policy(FlatOne())  # 이름 중복

    def test_charge_updates_campaign_spend_but_not_for_shortfall(self):
        adv, camp, other = funded(100), uuid.uuid4(), uuid.uuid4()
        charge(adv, 70, "a", camp)
        charge(adv, 70, "b", camp)  # 잔액 30 만 받는다
        charge(adv, 5, "c", other)  # 잔액 0: 소진 없음
        self.assertEqual(api.spend_today([camp, other], now=NOW), {camp: 100})  # 실제 차감액만 센다
        self.assertEqual(LedgerEntry.objects.get(reaction_ref="b").shortfall, 40)
        self.assertEqual(CampaignSpend.objects.count(), 1)

    def test_charge_validation_and_unknown_wallet(self):
        adv, camp = funded(), uuid.uuid4()
        for ref in ("", None, 5, "x" * 101):
            with self.assertRaises(InvalidRequest, msg=ref):
                charge(adv, 5, ref, camp)
        with self.assertRaises(NotFound):
            api.charge_for_reaction(uuid.uuid4(), camp, IMPRESSION, IMPRESSION, 5, "no-wallet", now=NOW)
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 10_000)
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 0)  # 실패한 시도는 흔적이 없다

    def test_balances_and_spend_today_are_single_queries(self):
        users = [funded(100 * (i + 1)) for i in range(3)]
        camps = [uuid.uuid4() for _ in range(3)]
        for u, c, i in zip(users, camps, range(3)):
            charge(u, 10 * (i + 1), f"r{i}", c)
        with self.assertNumQueries(1):
            got = api.balances([u.pk for u in users] + [uuid.uuid4()])
        self.assertEqual(got, {users[0].pk: 90, users[1].pk: 180, users[2].pk: 270})  # 지갑 없는 ID 는 결과에 없다
        with self.assertNumQueries(1):
            spent = api.spend_today(camps + [uuid.uuid4()], now=NOW)
        self.assertEqual(spent, {camps[0]: 10, camps[1]: 20, camps[2]: 30})


class ConcurrentChargeTests(TransactionTestCase):
    def test_charge_concurrent_same_ref_once(self):
        adv, camp = funded(1_000), uuid.uuid4()
        barrier, outcomes = threading.Barrier(2), []

        def worker():
            try:
                barrier.wait(timeout=5)
                outcomes.append(charge(adv, 100, "same-ref", camp))
            except Exception as e:  # noqa: BLE001
                outcomes.append(type(e).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        [t.start() for t in threads]
        [t.join(timeout=15) for t in threads]
        charge(adv, 100, "same-ref", camp)  # 실패한 쪽은 매체처럼 재시도한다(최소 한 번 전달)
        self.assertEqual(LedgerEntry.objects.filter(reaction_ref="same-ref").count(), 1)
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 900)  # 한 번만 차감
        self.assertEqual(api.spend_today([camp], now=NOW), {camp: 100})
        self.assertEqual(api.check_ledger(), [])
        self.assertTrue(any(getattr(o, "duplicate", None) is False for o in outcomes), outcomes)  # 처음 처리한 쪽이 있다
