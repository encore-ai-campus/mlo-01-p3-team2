"""부하 시험(`scripts/load_test.py`)의 **불변식 검사기 자체**를 시험한다: 깨끗한 상태는 통과시키고, 유실·이중 과금·어긋난 잔액은 놓치지 않는다.

검사기가 아무것도 못 잡으면 부하 시험의 '모두 충족'은 의미가 없다.
"""
import importlib.util
import uuid
from pathlib import Path
from random import Random

from django.db import connection
from django.test import TestCase, TransactionTestCase, tag

from billing import api as billing
from billing.models import LedgerEntry
from records import api as records
from records.models import Reaction
from tests.factories import NOW, SUBJECT, World

_spec = importlib.util.spec_from_file_location("load_test", Path(__file__).resolve().parent.parent / "scripts" / "load_test.py")
load_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load_test)


def billing_wallet_id(user):
    from billing.models import Wallet

    return Wallet.objects.get(owner=user).wallet_id.hex


def sql(statement, *params):
    with connection.cursor() as cur:
        cur.execute(statement, params)


class InvariantMixin:
    def setUp(self):
        self.w = World()
        self.media = self.w.slot.media_id
        self.decision = records.decide(self.media, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        self.view, _ = records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        records.process_reaction(self.view.inbox_id, now=NOW)  # 인정·과금 294(입찰 300 × 노출 98%)

    def problems(self, **kw):
        acked = {(str(self.media), str(self.view.reaction_id)): (str(self.decision.decision_id), "IMPRESSION")}
        return load_test.verify_invariants(kw.pop("decisions", {self.decision.decision_id}), kw.pop("reactions", acked), quiescent=True, **kw)


class InvariantBase(InvariantMixin, TestCase):
    pass


@tag("security")
class DoubleChargeCheckerTests(InvariantMixin, TransactionTestCase):
    """유일 제약을 빼는 DDL 은 MySQL 에서 트랜잭션을 끝내 버리므로(암묵적 커밋) 롤백에 기댈 수 없다 — 이 시험만 TransactionTestCase 로 하고, 뺀 제약은 반드시 되돌린다."""

    def test_a_double_charge_is_found(self):
        charge = LedgerEntry.objects.get(entry_type="CHARGE")
        sql("ALTER TABLE billing_ledger_entry DROP INDEX billing_charge_once_per_reaction")  # 유일 제약이 없는 저장소를 가정하고 같은 키를 한 번 더 넣는다
        duplicate = uuid.uuid4().hex

        def restore():  # 같은 키가 두 줄이면 제약을 다시 걸 수 없으므로 넣은 줄부터 지운다
            sql("DELETE FROM billing_ledger_entry WHERE entry_id = %s", duplicate)
            sql("ALTER TABLE billing_ledger_entry ADD CONSTRAINT billing_charge_once_per_reaction UNIQUE (reaction_ref)")

        self.addCleanup(restore)
        sql(
            "INSERT INTO billing_ledger_entry (entry_id, wallet_id, seq, entry_type, amount, balance_after, campaign_id, reaction_ref, charge_policy, shortfall, note, created_at) "
            "SELECT %s, wallet_id, seq + 1, entry_type, amount, balance_after, campaign_id, reaction_ref, charge_policy, shortfall, note, created_at FROM billing_ledger_entry WHERE entry_id = %s",
            duplicate, charge.entry_id.hex,
        )
        self.assertTrue(any("이중 과금" in p for p in self.problems()))


@tag("security")
class InvariantCheckerTests(InvariantBase):
    def test_a_clean_state_passes(self):
        self.assertEqual(self.problems(), [])

    def test_an_acknowledged_but_missing_decision_or_reaction_is_a_loss(self):
        self.assertTrue(any("결정" in p and "유실" in p for p in self.problems(decisions={uuid.uuid4()})))
        self.assertTrue(any("반응" in p and "유실" in p for p in self.problems(reactions={(str(self.media), str(uuid.uuid4())): (str(self.decision.decision_id), "IMPRESSION")})))

    def test_a_missing_charge_is_found(self):
        sql("DELETE FROM billing_ledger_entry WHERE entry_type = 'CHARGE'")  # ORM 의 추가 전용 가드를 우회(운영 사고 모사)
        self.assertTrue(any("과금이 없다" in p for p in self.problems()))

    def test_a_charge_without_an_accepted_reaction_is_found(self):
        sql("UPDATE records_reaction SET status = 'RECEIVED', processed_at = NULL, reason_code = NULL, applied_rule = NULL, accepted_key = NULL, basis = NULL")
        self.assertTrue(any("인정되지 않은 반응에 대한 과금" in p for p in self.problems(expect_drained=False)))

    def test_a_charge_whose_amount_differs_from_the_decision_is_found_even_if_the_ledger_is_consistent(self):
        """원장 내부 수치(잔액·balance_after)를 맞춰 놓아도 결정의 적용 금액 × 비율(294)과 다르면 잡는다."""
        sql("UPDATE billing_ledger_entry SET amount = -295, balance_after = balance_after - 1 WHERE entry_type = 'CHARGE'")
        sql("UPDATE billing_wallet SET balance = balance - 1")
        self.assertEqual(billing.check_ledger(quiescent=True), [])  # 원장만 보면 멀쩡하다
        self.assertTrue(any("적용 금액" in p for p in self.problems()), self.problems())

    def test_a_legitimate_shortfall_is_not_flagged(self):
        """잔액이 모자라 덜 받은 과금(부족분)은 정상이다: 받은 금액 + 부족분 = 적용 금액 × 비율이고 잔액은 0 이 된다."""
        second = records.decide(self.media, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(3))  # 잔액이 충분할 때 만든 결정
        billing.adjust(self.w.admin, self.w.adv.pk, -(50_000 - 294 - 15), "잔액을 15 로", now=NOW)
        view, _ = records.receive_reaction(self.media, second.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW)
        charge = LedgerEntry.objects.get(reaction_ref=f"{self.media}:{view.reaction_id}")
        self.assertEqual((charge.amount, charge.shortfall, charge.balance_after), (-15, 294 - 15, 0))
        self.assertEqual(self.problems(), [])

    def test_a_fake_shortfall_with_money_left_is_found(self):
        sql("UPDATE billing_ledger_entry SET amount = -289, shortfall = 5, balance_after = 49711 WHERE entry_type = 'CHARGE'")
        sql("UPDATE billing_wallet SET balance = 49711")
        self.assertEqual(billing.check_ledger(quiescent=True), [])
        self.assertTrue(any("부족분" in p for p in self.problems()), self.problems())

    def test_a_charge_on_another_advertisers_wallet_is_found_even_if_both_ledgers_are_consistent(self):
        other = World()
        other_wallet = billing_wallet_id(other.adv)
        mine = billing_wallet_id(self.w.adv)
        sql("UPDATE billing_ledger_entry SET wallet_id = %s, seq = 2, balance_after = 49706 WHERE entry_type = 'CHARGE'", other_wallet)
        sql("UPDATE billing_wallet SET balance = 49706 WHERE wallet_id = %s", other_wallet)
        sql("UPDATE billing_wallet SET balance = 50000 WHERE wallet_id = %s", mine)
        self.assertEqual(billing.check_ledger(quiescent=True), [])
        self.assertTrue(any("광고주" in p for p in self.problems()), self.problems())

    def test_a_charge_on_another_campaign_or_time_is_found(self):
        sql("UPDATE billing_ledger_entry SET campaign_id = %s WHERE entry_type = 'CHARGE'", uuid.uuid4().hex)
        self.assertTrue(any("캠페인" in p for p in self.problems()))
        sql("UPDATE billing_ledger_entry SET created_at = '2020-01-01 00:00:00' WHERE entry_type = 'CHARGE'")
        self.assertTrue(any("접수 시각" in p for p in self.problems()))

    def test_a_reaction_linked_to_another_valid_decision_is_found(self):
        """수신 확인한 (매체, 반응 ID, 결정 ID, 유형)이 저장된 행과 다르면 잡는다 — 같은 광고주의 다른 유효한 결정이라도."""
        other_decision = records.decide(self.media, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(2))
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

    def test_an_unprocessed_reaction_is_reported_only_when_the_queue_should_be_empty(self):
        extra, _ = records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "CLICK", NOW, {}, now=NOW)
        self.assertTrue(any("RECEIVED" in p for p in self.problems()))
        self.assertEqual(self.problems(expect_drained=False), [])
        self.assertEqual(Reaction.objects.get(pk=extra.inbox_id).status, "RECEIVED")

    def test_two_accepted_reactions_of_the_same_type_are_found(self):
        second, _ = records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        # 유일 제약이 막는 상태를 만들려면 서로 다른 인정 키가 필요하다(제약이 없는 저장소를 가정한 사고 모사)
        sql("UPDATE records_reaction SET status = 'ACCEPTED', processed_at = %s, person_id = %s, accepted_key = %s, basis = '{\"v\": 1}' WHERE inbox_id = %s" % (
            "'2026-10-07 12:00:00'", "'" + SUBJECT + "'", "'other-key'", "'" + second.inbox_id.hex + "'"))
        self.assertTrue(any("두 번 이상 인정" in p for p in self.problems()))


@tag("security")
class FunnelInvariantTests(InvariantBase):
    """검사기가 퍼널 약속(서버 관측 클릭만, 노출 → 클릭 → 전환, 클릭 기간)과 보류의 허용 범위를 안다."""

    def put(self, rtype, **kw):
        values = dict(
            media_id=self.media, reaction_id=uuid.uuid4(), decision_id=self.decision.decision_id, type=rtype, occurred_at=NOW, received_at=NOW,
            raw={}, status="ACCEPTED", processed_at=NOW, person_id=SUBJECT, source="server" if rtype == "CLICK" else "media",
        )
        values.update(kw)
        values.setdefault("basis", None if values["status"] == "RECEIVED" else {"v": 1})  # 판정한 행에는 근거가 있어야 한다(DB 제약)
        if values["status"] == "ACCEPTED" and "accepted_key" not in values:
            values["accepted_key"] = f"{values['decision_id']}:{values['person_id']}:{rtype}"
        row = Reaction.objects.create(**values)
        if row.status == "ACCEPTED":  # 처리처럼 인정된 반응은 결정에 남긴 비율로 과금된다(모든 유형, 6-10c)
            chosen = self.decision.chosen
            billing.charge_for_reaction(chosen.owner_id, chosen.campaign_id, rtype, chosen.charge_shares, chosen.applied_amount,
                                        f"{row.media_id}:{row.reaction_id}", now=row.received_at)
        return row

    def test_a_correct_funnel_passes(self):
        self.put("CLICK")  # 노출은 setUp 에서 인정됨
        self.put("CONVERSION")
        self.assertEqual(self.problems(), [])

    def test_an_accepted_click_reported_by_the_media_is_found(self):
        self.put("CLICK", source="media")
        self.assertTrue(any("매체가 보고한 클릭" in p for p in self.problems()))

    def test_an_accepted_click_without_an_accepted_impression_is_found(self):
        Reaction.objects.filter(type="IMPRESSION").update(person_id="0197a5c0-0000-7000-8000-0000000000a1")  # 다른 사람의 노출
        self.put("CLICK")
        self.assertTrue(any("노출 없이 클릭" in p for p in self.problems()))

    def test_an_accepted_conversion_without_an_accepted_click_is_found(self):
        self.put("CONVERSION")
        self.assertTrue(any("클릭 없이 전환" in p for p in self.problems()))

    def test_an_accepted_click_after_the_click_window_is_found(self):
        from datetime import timedelta

        self.put("CLICK", received_at=NOW + timedelta(seconds=301))
        self.assertTrue(any("클릭 기간" in p for p in self.problems()))

    def test_an_accepted_click_whose_impression_arrived_after_the_hold_window_is_found(self):
        """검토 2-9 후속 #1: 기한(접수 + 300초)을 넘겨 처음 도착한 노출로 인정된 클릭. 기한 정각은 정상이다."""
        from datetime import timedelta

        self.put("CLICK")
        Reaction.objects.filter(type="IMPRESSION").update(received_at=NOW + timedelta(seconds=300))
        self.assertEqual([p for p in self.problems() if "보류 기한" in p], [])
        Reaction.objects.filter(type="IMPRESSION").update(received_at=NOW + timedelta(seconds=301))
        self.assertTrue(any("보류 기한 뒤에야 도착한 노출" in p for p in self.problems()))

    def test_processing_late_is_not_a_violation_only_arriving_late_is(self):
        from datetime import timedelta

        self.put("CLICK", processed_at=NOW + timedelta(hours=5))  # 인정(처리)은 몇 시간 뒤여도 도착이 제때면 정상
        Reaction.objects.filter(type="IMPRESSION").update(processed_at=NOW + timedelta(hours=6))
        self.assertEqual(self.problems(), [])

    def test_an_accepted_conversion_received_before_its_click_is_found(self):
        """검토 2-9 후속 #2: 클릭보다 먼저 접수된 전환이 나중 클릭으로 인정됨. 같은 시각은 정상이다."""
        from datetime import timedelta

        self.put("CLICK", received_at=NOW + timedelta(seconds=200))
        self.put("CONVERSION", received_at=NOW + timedelta(seconds=200))
        self.assertEqual([p for p in self.problems() if "전환" in p], [])
        Reaction.objects.filter(type="CONVERSION").update(received_at=NOW + timedelta(seconds=199))
        self.assertTrue(any("전환보다 늦게 생긴 클릭" in p for p in self.problems()))

    def test_a_conversion_after_the_conversion_window_is_found(self):
        from datetime import timedelta

        self.put("CLICK")
        self.put("CONVERSION", received_at=NOW + timedelta(days=30, seconds=1))
        self.assertTrue(any("전환 기간" in p for p in self.problems()))

    def test_the_same_person_and_type_accepted_twice_is_found_but_other_people_may_repeat(self):
        self.put("IMPRESSION", person_id="0197a5c0-0000-7000-8000-0000000000a1")  # 다른 사람(일괄 슬롯의 다른 시청자)은 괜찮다
        self.assertEqual([p for p in self.problems() if "두 번 이상" in p], [])
        self.put("IMPRESSION", accepted_key="forged-second-key")  # 같은 사람의 같은 유형(유일 제약이 없는 저장소를 가정해 키만 다르게)
        self.assertTrue(any("두 번 이상 인정" in p for p in self.problems()))

    def test_waiting_for_a_prerequisite_is_normal_only_within_the_hold_time(self):
        from datetime import timedelta

        from django.utils import timezone

        self.put("CONVERSION", status="RECEIVED", processed_at=None, person_id=None, received_at=timezone.now())
        self.assertEqual(self.problems(), [])  # 앞 단계를 기다리는 전환은 정상
        self.put("CONVERSION", status="RECEIVED", processed_at=None, person_id=None, received_at=timezone.now() - timedelta(seconds=3600))
        self.assertTrue(any("RECEIVED" in p for p in self.problems()))  # 기한을 넘기고도 남은 것은 처리되지 않은 것
        Reaction.objects.filter(status="RECEIVED").delete()
        self.put("IMPRESSION", status="RECEIVED", processed_at=None, person_id=None, received_at=timezone.now())
        self.assertTrue(any("RECEIVED" in p for p in self.problems()))  # 노출은 기다릴 앞 단계가 없다


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
        harness.quiescent = True  # 이 시험은 TestCase 의 열린 트랜잭션 안이고 동시에 쓰는 연결이 없다
        with mock.patch.object(load_test, "call", fake_call), mock.patch.object(load_test, "now_utc", lambda: next(clock)), \
                mock.patch.object(load_test, "make_decisions", lambda ctx, count: [str(uuid.uuid4())] * count):
            harness.resend_storm()
        self.assertEqual(len(bodies), 6)
        self.assertEqual(len({path for path, _ in bodies}), 1)  # 같은 reaction_id
        self.assertEqual(len({str(body) for _, body in bodies}), 1, bodies)  # 본문(시각 포함)도 같다
