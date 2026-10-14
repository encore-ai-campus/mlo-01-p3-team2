"""Step 4-1d: 과금 이벤트(`ad.charge`) — 원장 CHARGE 한 줄마다 한 건, 과금과 같은 트랜잭션."""
import uuid
from datetime import timedelta
from unittest import mock

from django.test import TransactionTestCase, override_settings, tag

from billing import api as billing
from billing.models import EntryType, LedgerEntry, Wallet
from events import schemas
from events.models import EventOutbox
from records import api as records
from tests.support.factories import NOW, SUBJECT, World
from tests.ops.test_records_processing import ProcessingBase
from tests.ops.test_event_reaction import events_of


@tag("security")
class ChargeEventTests(ProcessingBase):
    def test_a_charge_leaves_one_event_matching_the_ledger_line(self):
        view = self.receive("IMPRESSION")
        self.assertEqual(self.process(view), "ACCEPTED")
        entry = LedgerEntry.objects.get(entry_type="CHARGE")
        (event,) = events_of(schemas.CHARGE)
        self.assertEqual(event.event_id, schemas.event_id_of(schemas.CHARGE, entry.entry_id))
        self.assertEqual(event.aggregate_id, self.decision.decision_id)  # 메시지 키 = 결정
        p = event.payload
        self.assertEqual((p["entry_id"], p["campaign_id"], p["charge_policy"], p["decision_id"]), (str(entry.entry_id), str(entry.campaign_id), entry.charge_policy, str(self.decision.decision_id)))
        self.assertEqual((p["charged_amount"], p["shortfall"], p["requested_amount"]), (-entry.amount, entry.shortfall, -entry.amount + entry.shortfall))
        self.assertEqual((p["reaction_ref"], p["budget_day"], p["created_at"]), (f"{self.media}:{self.row(view).reaction_id}", "2026-10-07", entry.created_at.isoformat()))
        self.assertNotIn("balance", str(p))  # 지갑 잔액·광고주 계정은 싣지 않는다

    def test_every_charge_ledger_line_has_exactly_one_event(self):
        for _ in range(3):
            self.process(self.receive("IMPRESSION", decision_id=self.new_decision(f"0197a5c0-0000-7000-8000-00000000{_:04d}").decision_id))
        entries = set(LedgerEntry.objects.filter(entry_type="CHARGE").values_list("entry_id", flat=True))
        ids = {e.payload["entry_id"] for e in events_of(schemas.CHARGE)}
        self.assertEqual(ids, {str(i) for i in entries})
        self.assertEqual(len(events_of(schemas.CHARGE)), len(entries))

    def test_a_shortfall_is_reported(self):
        Wallet.objects.update(balance=10)  # 과금액(300 × 노출 98% = 294)보다 모자란 잔액
        self.process(self.receive("IMPRESSION"))
        p = events_of(schemas.CHARGE)[0].payload
        self.assertEqual((p["requested_amount"], p["charged_amount"], p["shortfall"]), (294, 10, 284))

    def test_no_charge_no_event(self):
        """과금 정책이 0 을 돌려준 반응은 인정되지만 원장도 이벤트도 없다(하한 100 · 비율 1 이상이면 `share/v1` 은 0 을 내지 않는다 — 0 을 내는 정책으로 본다)."""
        class Zero:
            name = "zero/v1"

            def amount_for(self, reaction_type, shares, applied_amount):
                return 0

        billing.register_charge_policy(Zero())
        self.addCleanup(billing.unregister_charge_policy, "zero/v1")
        imp = self.receive("IMPRESSION")
        self.process(imp)
        before = len(events_of(schemas.CHARGE))
        click = self.click()
        with override_settings(BILLING_CHARGE_POLICY="zero/v1"):
            self.assertEqual(records.process_reaction(click.inbox_id, now=NOW + timedelta(seconds=1)), "ACCEPTED")
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), before)
        self.assertEqual(len(events_of(schemas.CHARGE)), before)

    def test_a_rejected_reaction_has_a_judged_event_but_no_charge_event(self):
        self.process(self.receive("IMPRESSION", decision_id=uuid.uuid4()))
        self.assertEqual((len(events_of(schemas.REACTION)), len(events_of(schemas.CHARGE))), (1, 0))


class ChargeEventAtomicityTests(TransactionTestCase):
    def test_if_the_charge_event_cannot_be_written_nothing_is_charged_or_judged(self):
        from random import Random

        w = World()
        decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        with mock.patch("records.processing.events.record_charge", side_effect=RuntimeError("outbox 실패")):
            with self.assertRaises(RuntimeError):
                records.process_reaction(view.inbox_id, now=NOW)
        self.assertEqual(LedgerEntry.objects.filter(entry_type=EntryType.CHARGE).count(), 0)  # 과금은 됐는데 이벤트가 없는 상태가 없다
        self.assertEqual(Wallet.objects.get().balance, 50_000)
        self.assertEqual(records.process_reaction(view.inbox_id, now=NOW), "ACCEPTED")
        self.assertEqual(EventOutbox.objects.filter(event_name=schemas.CHARGE).count(), 1)
