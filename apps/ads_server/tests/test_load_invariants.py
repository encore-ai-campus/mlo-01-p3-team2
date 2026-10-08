"""부하 시험(`scripts/load_test.py`)의 **불변식 검사기 자체**를 시험한다: 깨끗한 상태는 통과시키고, 유실·이중 과금·어긋난 잔액은 놓치지 않는다.

검사기가 아무것도 못 잡으면 부하 시험의 '모두 충족'은 의미가 없다.
"""
import importlib.util
import uuid
from pathlib import Path
from random import Random

from django.db import connection
from django.test import TestCase, tag

from billing.models import CampaignSpend, LedgerEntry
from records import api as records
from records.models import Reaction
from tests.factories import NOW, World

_spec = importlib.util.spec_from_file_location("load_test", Path(__file__).resolve().parent.parent / "scripts" / "load_test.py")
load_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load_test)


def sql(statement, *params):
    with connection.cursor() as cur:
        cur.execute(statement, params)


@tag("security")
class InvariantCheckerTests(TestCase):
    def setUp(self):
        self.w = World()
        self.media = self.w.slot.media_id
        self.decision = records.decide(self.media, self.w.slot.slot_id, now=NOW, rng=Random(1))
        self.view, _ = records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        records.process_reaction(self.view.inbox_id, now=NOW)  # 인정·과금 30

    def problems(self, **kw):
        return load_test.verify_invariants(
            kw.pop("decisions", {self.decision.decision_id}), kw.pop("reactions", {self.view.reaction_id: self.decision.decision_id}), **kw
        )

    def test_a_clean_state_passes(self):
        self.assertEqual(self.problems(), [])

    def test_an_acknowledged_but_missing_decision_or_reaction_is_a_loss(self):
        self.assertTrue(any("결정" in p and "유실" in p for p in self.problems(decisions={uuid.uuid4()})))
        self.assertTrue(any("반응" in p and "유실" in p for p in self.problems(reactions={uuid.uuid4(): uuid.uuid4()})))

    def test_a_missing_charge_is_found(self):
        sql("DELETE FROM billing_ledger_entry WHERE entry_type = 'CHARGE'")  # ORM 의 추가 전용 가드를 우회(운영 사고 모사)
        self.assertTrue(any("과금이 없다" in p for p in self.problems()))

    def test_a_charge_without_an_accepted_reaction_is_found(self):
        sql("UPDATE records_reaction SET status = 'RECEIVED', processed_at = NULL, reason_code = NULL, applied_rule = NULL")
        self.assertTrue(any("인정되지 않은 반응에 대한 과금" in p for p in self.problems(expect_drained=False)))

    def test_a_double_charge_is_found(self):
        charge = LedgerEntry.objects.get(entry_type="CHARGE")
        sql("DROP INDEX billing_charge_once_per_reaction")  # 유일 제약이 없는 저장소를 가정하고 같은 키를 한 번 더 넣는다
        sql(
            "INSERT INTO billing_ledger_entry (entry_id, wallet_id, seq, entry_type, amount, balance_after, campaign_id, reaction_ref, charge_policy, shortfall, note, created_at) "
            "SELECT ?, wallet_id, seq + 1, entry_type, amount, balance_after, campaign_id, reaction_ref, charge_policy, shortfall, note, created_at FROM billing_ledger_entry WHERE entry_id = ?",
            uuid.uuid4().hex, charge.entry_id.hex,
        )
        self.assertTrue(any("이중 과금" in p for p in self.problems()))

    def test_a_balance_that_differs_from_the_ledger_is_found(self):
        sql("UPDATE billing_wallet SET balance = balance + 5")
        self.assertTrue(any("잔액" in p for p in self.problems()))

    def test_a_spend_that_differs_from_the_ledger_is_found(self):
        CampaignSpend.objects.update(spent=999)
        self.assertTrue(any("일 소진액" in p for p in self.problems()))

    def test_an_unprocessed_reaction_is_reported_only_when_the_queue_should_be_empty(self):
        extra, _ = records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "CLICK", NOW, {}, now=NOW)
        self.assertTrue(any("RECEIVED" in p for p in self.problems()))
        self.assertEqual(self.problems(expect_drained=False), [])
        self.assertEqual(Reaction.objects.get(pk=extra.inbox_id).status, "RECEIVED")

    def test_two_accepted_reactions_of_the_same_type_are_found(self):
        second, _ = records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        sql("DROP INDEX records_reaction_one_accepted_per_type")
        sql("UPDATE records_reaction SET status = 'ACCEPTED', processed_at = %s WHERE inbox_id = %s" % ("'2026-10-07 12:00:00'", "'" + second.inbox_id.hex + "'"))
        self.assertTrue(any("두 번 이상 인정" in p for p in self.problems()))
