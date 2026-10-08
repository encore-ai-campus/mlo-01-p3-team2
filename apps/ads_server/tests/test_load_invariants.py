"""부하 시험(`scripts/load_test.py`)의 **불변식 검사기 자체**를 시험한다: 깨끗한 상태는 통과시키고, 유실·이중 과금·어긋난 잔액은 놓치지 않는다.

검사기가 아무것도 못 잡으면 부하 시험의 '모두 충족'은 의미가 없다.
"""
import importlib.util
import uuid
from pathlib import Path
from random import Random

from django.db import connection
from django.test import TestCase, tag

from billing import api as billing
from billing.models import CampaignSpend, LedgerEntry
from records import api as records
from records.models import Reaction
from tests.factories import NOW, World

_spec = importlib.util.spec_from_file_location("load_test", Path(__file__).resolve().parent.parent / "scripts" / "load_test.py")
load_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load_test)


def billing_wallet_id(user):
    from billing.models import Wallet

    return Wallet.objects.get(owner=user).wallet_id.hex


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
        acked = {(str(self.media), str(self.view.reaction_id)): (str(self.decision.decision_id), "IMPRESSION")}
        return load_test.verify_invariants(kw.pop("decisions", {self.decision.decision_id}), kw.pop("reactions", acked), **kw)

    def test_a_clean_state_passes(self):
        self.assertEqual(self.problems(), [])

    def test_an_acknowledged_but_missing_decision_or_reaction_is_a_loss(self):
        self.assertTrue(any("결정" in p and "유실" in p for p in self.problems(decisions={uuid.uuid4()})))
        self.assertTrue(any("반응" in p and "유실" in p for p in self.problems(reactions={(str(self.media), str(uuid.uuid4())): (str(self.decision.decision_id), "IMPRESSION")})))

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

    def test_a_charge_whose_amount_differs_from_the_decision_is_found_even_if_the_ledger_is_consistent(self):
        """원장 내부 수치(잔액·balance_after·소진액)를 맞춰 놓아도 결정의 적용 금액(30)과 다르면 잡는다."""
        sql("UPDATE billing_ledger_entry SET amount = -31, balance_after = balance_after - 1 WHERE entry_type = 'CHARGE'")
        sql("UPDATE billing_wallet SET balance = balance - 1")
        sql("UPDATE billing_campaign_spend SET spent = 31")
        self.assertEqual(billing.check_ledger(), [])  # 원장만 보면 멀쩡하다
        self.assertTrue(any("적용 금액" in p for p in self.problems()), self.problems())

    def test_a_legitimate_shortfall_is_not_flagged(self):
        """잔액이 모자라 덜 받은 과금(부족분)은 정상이다: 받은 금액 + 부족분 = 적용 금액이고 잔액은 0 이 된다."""
        second = records.decide(self.media, self.w.slot.slot_id, now=NOW, rng=Random(3))  # 잔액이 충분할 때 만든 결정
        billing.adjust(self.w.admin, self.w.adv.pk, -49_955, "잔액을 15 로", now=NOW)
        view, _ = records.receive_reaction(self.media, second.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW)
        charge = LedgerEntry.objects.get(reaction_ref=f"{self.media}:{view.reaction_id}")
        self.assertEqual((charge.amount, charge.shortfall, charge.balance_after), (-15, 15, 0))
        self.assertEqual(self.problems(), [])

    def test_a_fake_shortfall_with_money_left_is_found(self):
        sql("UPDATE billing_ledger_entry SET amount = -25, shortfall = 5, balance_after = 49975 WHERE entry_type = 'CHARGE'")
        sql("UPDATE billing_wallet SET balance = 49975")
        sql("UPDATE billing_campaign_spend SET spent = 25")
        self.assertEqual(billing.check_ledger(), [])
        self.assertTrue(any("부족분" in p for p in self.problems()), self.problems())

    def test_a_charge_on_another_advertisers_wallet_is_found_even_if_both_ledgers_are_consistent(self):
        other = World()
        other_wallet = billing_wallet_id(other.adv)
        mine = billing_wallet_id(self.w.adv)
        sql("UPDATE billing_ledger_entry SET wallet_id = %s, seq = 2, balance_after = 49970 WHERE entry_type = 'CHARGE'", other_wallet)
        sql("UPDATE billing_wallet SET balance = 49970 WHERE wallet_id = %s", other_wallet)
        sql("UPDATE billing_wallet SET balance = 50000 WHERE wallet_id = %s", mine)
        self.assertEqual(billing.check_ledger(), [])
        self.assertTrue(any("광고주" in p for p in self.problems()), self.problems())

    def test_a_charge_on_another_campaign_or_time_is_found(self):
        sql("UPDATE billing_ledger_entry SET campaign_id = %s WHERE entry_type = 'CHARGE'", uuid.uuid4().hex)
        self.assertTrue(any("캠페인" in p for p in self.problems()))
        sql("UPDATE billing_ledger_entry SET created_at = '2020-01-01 00:00:00' WHERE entry_type = 'CHARGE'")
        self.assertTrue(any("접수 시각" in p for p in self.problems()))

    def test_a_reaction_linked_to_another_valid_decision_is_found(self):
        """수신 확인한 (매체, 반응 ID, 결정 ID, 유형)이 저장된 행과 다르면 잡는다 — 같은 광고주의 다른 유효한 결정이라도."""
        other_decision = records.decide(self.media, self.w.slot.slot_id, now=NOW, rng=Random(2))
        sql("UPDATE records_reaction SET decision_id = %s", other_decision.decision_id.hex)
        self.assertTrue(any("다른 결정" in p for p in self.problems()), self.problems())

    def test_a_reaction_stored_under_another_media_or_type_is_found(self):
        sql("UPDATE records_reaction SET type = 'CLICK'")
        self.assertTrue(any("유형" in p for p in self.problems()))
        sql("UPDATE records_reaction SET type = 'IMPRESSION', media_id = %s", uuid.uuid4().hex)
        self.assertTrue(any("유실" in p for p in self.problems()))  # 그 매체의 그 반응 ID 는 저장돼 있지 않다

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


@tag("security")
class ResendStormBodyTests(TestCase):
    def test_every_resend_of_one_reaction_carries_the_same_body_even_across_a_second_boundary(self):
        """같은 reaction_id 의 재전송은 한 본문을 재사용한다. 호출마다 시각을 새로 만들면 초 경계에서 409 가 섞여 정상 서버에서도 게이트가 실패한다."""
        from unittest import mock

        bodies, clock = [], iter(f"2026-10-07T12:00:{second:02d}Z" for second in range(60))

        def fake_call(port, method, path, key, body=None, retry=True, give_up_after=90):
            bodies.append((path, body))
            return load_test.Outcome(201 if len(bodies) == 1 else 200, {}, {}, 0.0, 0.0, [201])

        harness = load_test.Harness(0, {"media_id": uuid.uuid4(), "slot_id": uuid.uuid4(), "key": "k", "advertisers": []}, 6, None, lambda *a: None)
        with mock.patch.object(load_test, "call", fake_call), mock.patch.object(load_test, "now_utc", lambda: next(clock)), \
                mock.patch.object(load_test, "make_decisions", lambda ctx, count: [str(uuid.uuid4())] * count):
            harness.resend_storm()
        self.assertEqual(len(bodies), 6)
        self.assertEqual(len({path for path, _ in bodies}), 1)  # 같은 reaction_id
        self.assertEqual(len({str(body) for _, body in bodies}), 1, bodies)  # 본문(시각 포함)도 같다
