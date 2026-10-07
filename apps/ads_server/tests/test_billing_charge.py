import threading
import time
import uuid

from django.db import OperationalError, connection
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


    def test_concurrent_charges_on_one_wallet_get_distinct_gapless_seqs(self):
        adv, camp = funded(10_000), uuid.uuid4()
        barrier, errors = threading.Barrier(4), []

        def worker(n):
            try:
                barrier.wait(timeout=5)
                for i in range(3):
                    for _attempt in range(200):  # 테스트 DB(인메모리 공유 캐시)는 테이블 잠금이 바로 오류가 된다. 매체처럼 재시도한다
                        try:
                            charge(adv, 10, f"w{n}-{i}", camp)
                            break
                        except OperationalError:
                            time.sleep(0.002)
                    else:
                        raise AssertionError("재시도 한도 초과")
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        [t.start() for t in threads]
        [t.join(timeout=30) for t in threads]
        self.assertEqual(errors, [])
        seqs = list(LedgerEntry.objects.filter(wallet__owner=adv).order_by("seq").values_list("seq", flat=True))
        self.assertEqual(seqs, list(range(1, 14)))  # 지급 1 + 과금 12, 빈틈·중복 없음
        self.assertEqual(api.check_ledger(), [])


@tag("security")
class ChargeInputValidationTests(TestCase):
    def snapshot(self, adv):
        return (
            LedgerEntry.objects.count(), api.get_wallet(adv, now=NOW).balance, list(CampaignSpend.objects.values_list("campaign_id", "spent")),
        )

    def test_charge_rejects_non_integer_or_out_of_range_amounts_and_changes_nothing(self):
        adv, camp = funded(), uuid.uuid4()
        before = self.snapshot(adv)
        for bad in (0.5, 1.0, True, False, "5", None, 0, -1, 2**53, 2**63):
            with self.assertRaises(InvalidRequest, msg=bad):
                charge(adv, bad, f"bad-{bad!r}", camp)
        self.assertEqual(self.snapshot(adv), before)  # 원장·잔액·소진액 모두 그대로
        self.assertEqual(api.check_ledger(), [])
        self.assertEqual(charge(adv, 5, "good", camp).charged, 5)  # 이후 정상 호출은 영향 없음

    def test_charge_rejects_bad_policy_results_and_changes_nothing(self):
        class Broken:
            name = "broken/v1"

            def __init__(self, value):
                self.value = value

            def amount_for(self, reaction_type, pricing_unit, applied_amount):
                return self.value

        adv, camp = funded(), uuid.uuid4()
        before = self.snapshot(adv)
        for i, bad in enumerate((0.5, True, -3, 2**53, "9", None)):
            api.register_charge_policy(Broken(bad))
            try:
                with override_settings(BILLING_CHARGE_POLICY="broken/v1"):
                    with self.assertRaises(ValueError, msg=bad):
                        charge(adv, 5, f"policy-{i}", camp)
            finally:
                api.unregister_charge_policy("broken/v1")
        self.assertEqual(self.snapshot(adv), before)
        self.assertEqual(api.check_ledger(), [])

    def test_balance_never_exceeds_max_amount(self):
        from foundation.api import MAX_AMOUNT
        from foundation.errors import InvalidRequest as Invalid
        from tests.factories import make_admin
        from django.db import IntegrityError, transaction

        adv, admin = funded(1), make_admin()
        with self.assertRaises(Invalid):  # 개별 금액은 범위 안이지만 합산하면 MAX + 1
            api.adjust(admin, adv.pk, MAX_AMOUNT, "한도 시험", now=NOW)
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 1)
        api.adjust(admin, adv.pk, MAX_AMOUNT - 1, "정확히 한도까지", now=NOW)
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, MAX_AMOUNT)
        with self.assertRaises(Invalid):
            api.adjust(admin, adv.pk, 1, "한도 초과", now=NOW)
        from billing.models import Wallet

        with self.assertRaises(IntegrityError), transaction.atomic():  # DB 도 같은 범위를 지킨다
            Wallet.objects.filter(owner=adv).update(balance=MAX_AMOUNT + 1)
        self.assertEqual(api.check_ledger(), [])

    def test_signup_grant_setting_must_be_a_sane_integer(self):
        from django.core.exceptions import ImproperlyConfigured
        from foundation.api import MAX_AMOUNT

        for bad in (-1, 1.5, True, "50000", MAX_AMOUNT + 1):
            with override_settings(SIGNUP_GRANT_POINTS=bad):
                with self.assertRaises(ImproperlyConfigured, msg=bad):
                    api.grant_signup(make_advertiser(), now=NOW)
        self.assertEqual(LedgerEntry.objects.count(), 0)
