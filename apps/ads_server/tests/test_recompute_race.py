"""DB-1c(검토 DB-1a P2): `recompute_spend` 와 과금의 경쟁 — MySQL 에서는 `atomic()` 이 다른 연결의 과금을 막지 못한다.

재계산이 원장을 읽은 뒤 다른 연결이 과금을 커밋하면, 재계산이 읽은 값으로 소진액을 덮어써 **원장 합계와 `CampaignSpend` 가 어긋난다**(지갑과 원장은 맞아서 예전 `check_ledger` 는 못 잡았다).
실제 연결을 스레드마다 하나씩 쓰고, 재계산이 원장을 읽은 직후(스레드 훅)에 다른 연결이 과금을 커밋하게 해 순서를 고정한다.
"""
import threading
import uuid
from datetime import date

from django.db import connection
from django.test import TransactionTestCase, override_settings, tag

from billing import api
from billing.models import CampaignSpend, LedgerEntry
from tests.factories import NOW, make_advertiser
from tests.test_receipt_ordering import BLOCKED, WAIT, Worker

DAY = date(2026, 10, 7)


@tag("security")
class RecomputeVersusChargeTests(TransactionTestCase):
    def setUp(self):
        self.adv = make_advertiser()
        with override_settings(SIGNUP_GRANT_POINTS=10_000):
            api.grant_signup(self.adv, now=NOW)
        self.camp = uuid.uuid4()

    def charge(self, amount, ref, campaign=None):
        return api.charge_for_reaction(self.adv.pk, campaign or self.camp, "IMPRESSION", "IMPRESSION", amount, ref, now=NOW)

    def spent(self, campaign=None):
        row = CampaignSpend.objects.filter(campaign_id=campaign or self.camp, budget_day=DAY).first()
        return row.spent if row else 0

    def ledger_total(self, campaign=None):
        return -sum(LedgerEntry.objects.filter(entry_type="CHARGE", campaign_id=campaign or self.camp).values_list("amount", flat=True))

    def recompute_with_hook(self, nth_select, during):
        """재계산 중 `billing_ledger_entry` 의 `nth_select` 번째 SELECT 가 끝난 직후 `during()` 을 실행한다. 훅이 실제로 불렸는지 돌려준다."""
        seen, fired = [], []

        def hook(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if "billing_ledger_entry" in sql and sql.lstrip().upper().startswith("SELECT"):
                seen.append(sql)
                if len(seen) == nth_select and not fired:
                    fired.append(1)
                    during()
            return result

        with connection.execute_wrapper(hook):
            api.recompute_spend()
        return bool(fired)

    def test_a_charge_committed_right_after_the_ledger_is_read_is_not_lost(self):
        """검토 재현: 첫 과금 10 커밋 → 재계산이 원장(10)을 읽음 → 다른 연결이 20 을 과금·커밋 → 재개. 소진액은 원장 합계(30)와 같아야 한다."""
        self.charge(10, "m:r1")
        api.recompute_spend()  # 소진액 행이 이미 있는 상태
        workers = []

        def another_connection_charges():
            worker = Worker(lambda: self.charge(20, "m:r2"))
            worker.start()
            worker.join(BLOCKED)  # 재계산이 그 행을 쥐고 있으면 여기서 기다린다 — 끝났든 기다리든 재개 뒤에 합쳐진다
            workers.append(worker)

        self.assertTrue(self.recompute_with_hook(1, another_connection_charges))
        for worker in workers:
            worker.join(WAIT)
            self.assertEqual(worker.errors, [])
        self.assertEqual(self.ledger_total(), 30)
        self.assertEqual(self.spent(), 30)
        self.assertEqual(api.check_ledger(), [])

    def test_a_charge_in_flight_while_the_row_is_locked_waits_and_adds_on_top(self):
        """재계산이 소진액 행을 잠그고 원장 합계를 읽은 뒤에 들어온 과금은, 행 잠금을 기다렸다가 그 위에 더해진다."""
        self.charge(10, "m:r1")
        api.recompute_spend()
        workers = []

        def another_connection_charges():
            worker = Worker(lambda: self.charge(20, "m:r2"))
            worker.start()
            worker.join(BLOCKED)
            self.assertTrue(worker.is_alive(), "소진액 행을 쥔 재계산을 기다리지 않았다")
            workers.append(worker)

        self.assertTrue(self.recompute_with_hook(2, another_connection_charges))  # 두 번째 원장 SELECT = 행을 잠근 뒤의 합계 조회
        for worker in workers:
            worker.join(WAIT)
            self.assertEqual(worker.errors, [])
        self.assertEqual((self.ledger_total(), self.spent()), (30, 30))
        self.assertEqual(api.check_ledger(), [])

    def test_a_pair_without_a_spend_row_gets_one_even_while_a_charge_arrives(self):
        """새 캠페인·새 날짜: 소진액 행이 없는 (캠페인, 날)에 원장 과금이 있으면 재계산이 행을 만들고, 그때 들어온 과금과도 합이 맞는다."""
        self.charge(10, "m:r1")
        CampaignSpend.objects.all().delete()  # 행이 없는 상태
        workers = []

        def another_connection_charges():
            worker = Worker(lambda: self.charge(20, "m:r2"))
            worker.start()
            worker.join(BLOCKED)
            workers.append(worker)

        self.assertTrue(self.recompute_with_hook(1, another_connection_charges))
        for worker in workers:
            worker.join(WAIT)
            self.assertEqual(worker.errors, [])
        self.assertEqual((self.ledger_total(), self.spent()), (30, 30))
        self.assertEqual(CampaignSpend.objects.filter(campaign_id=self.camp, budget_day=DAY).count(), 1)

    def test_a_brand_new_campaign_charged_during_the_recompute_keeps_its_spend(self):
        """재계산이 시작할 때 없던 캠페인의 과금은 재계산이 건드리지 않는다(그 과금이 스스로 소진액을 쌓는다)."""
        self.charge(10, "m:r1")
        fresh = uuid.uuid4()
        workers = []

        def new_campaign_is_charged():
            worker = Worker(lambda: self.charge(7, "m:fresh", campaign=fresh))
            worker.start()
            worker.join(WAIT)
            workers.append(worker)

        self.assertTrue(self.recompute_with_hook(1, new_campaign_is_charged))
        self.assertEqual(workers[0].errors, [])
        self.assertEqual((self.spent(), self.spent(fresh)), (10, 7))
        self.assertEqual(api.check_ledger(), [])

    def test_a_stale_row_is_removed_without_losing_a_charge_that_arrives_meanwhile(self):
        """오래된·틀린 행(원장에 없는 캠페인)은 지우되, 그 (캠페인, 날)에 막 들어온 과금의 소진액은 남는다."""
        stale = uuid.uuid4()
        CampaignSpend.objects.create(campaign_id=stale, budget_day=DAY, spent=999)
        workers = []

        def charge_the_stale_pair():
            worker = Worker(lambda: self.charge(5, "m:stale", campaign=stale))
            worker.start()
            worker.join(BLOCKED)
            workers.append(worker)

        self.assertTrue(self.recompute_with_hook(1, charge_the_stale_pair))
        for worker in workers:
            worker.join(WAIT)
            self.assertEqual(worker.errors, [])
        self.assertEqual((self.ledger_total(stale), self.spent(stale)), (5, 5))
        self.assertEqual(api.check_ledger(), [])


    def test_a_charge_paused_before_its_spend_update_is_not_lost_when_the_recompute_deletes_the_row(self):
        """과금이 소진액 행을 읽은(또는 갱신하려는) 순간 재계산이 그 행을 지우고 커밋해도, 과금의 증가분은 새 행으로 남는다(행의 키로 갱신하고 없을 때만 만든다)."""
        stale = uuid.uuid4()
        CampaignSpend.objects.create(campaign_id=stale, budget_day=DAY, spent=999)
        paused, resume = threading.Event(), threading.Event()

        def charge_paused_before_the_spend_update():
            def hook(execute, sql, params, many, context):
                if sql.lstrip().upper().startswith("UPDATE") and "billing_campaign_spend" in sql and not paused.is_set():
                    paused.set()
                    resume.wait(WAIT)
                return execute(sql, params, many, context)

            with connection.execute_wrapper(hook):
                return self.charge(5, "m:late", campaign=stale)

        worker = Worker(charge_paused_before_the_spend_update)
        worker.start()
        self.assertTrue(paused.wait(WAIT), worker.errors)
        api.recompute_spend()  # 원장에는 아직 그 과금이 안 보인다(미커밋) → 행(999)을 지운다
        self.assertFalse(CampaignSpend.objects.filter(campaign_id=stale).exists())
        resume.set()
        worker.join(WAIT)
        self.assertEqual(worker.errors, [])
        self.assertEqual((self.ledger_total(stale), self.spent(stale)), (5, 5))
        self.assertEqual(api.check_ledger(), [])


    def test_a_charge_that_finds_no_row_and_loses_the_creation_race_adds_to_the_row_the_recompute_made(self):
        """과금이 '행 없음'을 보고 만들려는 사이에 재계산이 같은 (캠페인, 날)의 행을 먼저 만들어 커밋해도, 과금은 유일 제약 충돌 뒤 그 행에 더한다."""
        self.charge(10, "m:r1")
        CampaignSpend.objects.all().delete()
        paused, resume = threading.Event(), threading.Event()

        def charge_that_pauses_after_finding_no_row():
            def hook(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if sql.lstrip().upper().startswith("UPDATE") and "billing_campaign_spend" in sql and not paused.is_set():
                    paused.set()  # 갱신이 0 행에 닿았다 — 이제 만들려는 참이다
                    resume.wait(WAIT)
                return result

            with connection.execute_wrapper(hook):
                return self.charge(20, "m:r2")

        worker = Worker(charge_that_pauses_after_finding_no_row)
        worker.start()
        self.assertTrue(paused.wait(WAIT), worker.errors)
        api.recompute_spend()  # 원장에 커밋된 10 으로 행을 만든다(진행 중인 20 은 아직 안 보인다)
        self.assertEqual(self.spent(), 10)
        resume.set()
        worker.join(WAIT)
        self.assertEqual(worker.errors, [])
        self.assertEqual((self.ledger_total(), self.spent()), (30, 30))
        self.assertEqual(CampaignSpend.objects.filter(campaign_id=self.camp, budget_day=DAY).count(), 1)


@tag("security")
class CheckLedgerSeesSpendDriftTests(TransactionTestCase):
    def test_a_spend_total_that_differs_from_the_ledger_is_reported(self):
        adv = make_advertiser()
        with override_settings(SIGNUP_GRANT_POINTS=1_000):
            api.grant_signup(adv, now=NOW)
        camp = uuid.uuid4()
        api.charge_for_reaction(adv.pk, camp, "IMPRESSION", "IMPRESSION", 30, "m:r1", now=NOW)
        self.assertEqual(api.check_ledger(), [])
        CampaignSpend.objects.filter(campaign_id=camp).update(spent=10)  # 재계산 경쟁이 남기던 상태
        problems = api.check_ledger()
        self.assertTrue(any("소진액" in p and str(camp) in p for p in problems), problems)
        CampaignSpend.objects.create(campaign_id=uuid.uuid4(), budget_day=DAY, spent=5)  # 원장에 없는 캠페인의 소진액
        self.assertEqual(sum("소진액" in p for p in api.check_ledger()), 2)
