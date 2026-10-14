"""접수와 판정의 순서 규약(`records/ordering.py`, 설계 §10 "판정 설계 기준" ②): 더 이른 `received_at` 의 반응이 **아직 커밋되지 않았을 때** 뒤의 반응이 대표로 굳지 않는다.

검토 2-13 후속 P2(0b23b86): 먼저 받은 유효한 노출이 INSERT 뒤 커밋 직전에 있고(다른 연결에서 안 보임) 뒤 노출이 먼저 커밋·처리되면 뒤 노출이 인정되고,
앞 노출은 나중에 커밋돼 `duplicate_type` 으로 거부된다 — 최종 데이터에 더 이른 유효 노출이 있는데도 클릭이 거부돼 정상 과금이 빠진다.

실제 MySQL 연결을 스레드마다 하나씩 쓰고, 접수 트랜잭션을 열어 둔 채 커밋을 미루는 방식으로 순서를 고정한다(시각은 `now=` 로 주입).
"""
import threading
import uuid

from django.db import connection
from django.test import TransactionTestCase, override_settings, tag
from django.utils import timezone

from records import api as records
from records.models import Reaction
from tests.support.concurrency import BLOCKED, WAIT, Uncommitted, Worker, arriving_before
from tests.support.factories import NOW, SUBJECT, World, at
from tests.ops.test_funnel_rules import FunnelMixin


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class ReceiptOrderingTests(FunnelMixin, TransactionTestCase):
    UNIT = "CLICK"

    def receive(self, rtype, when, decision=None, rid=None):
        decision = decision or self.decision
        return records.receive_reaction(self.media, decision.decision_id, rid or uuid.uuid4(), rtype, at(when), {}, now=at(when))

    def balance(self):
        from billing import api as billing

        return billing.get_wallet(self.w.adv, now=NOW).balance

    def assert_blocked(self, worker, what):
        worker.join(BLOCKED)
        self.assertTrue(worker.is_alive(), f"{what}: 진행 중인 접수를 기다리지 않았다")

    def test_a_later_receipt_cannot_commit_ahead_of_an_in_flight_earlier_one(self):
        """같은 결정의 접수는 결정 행 잠금으로 줄을 선다: 앞 접수가 커밋되기 전에는 뒤 접수가 끝나지 않는다."""
        with Uncommitted(lambda: self.receive("IMPRESSION", 300.9)) as early:
            later = Worker(lambda: self.receive("IMPRESSION", 301.1))
            later.start()
            self.assert_blocked(later, "뒤 접수")
            early.commit()
        later.join(WAIT)
        self.assertEqual(later.errors, [])
        self.assertEqual(Reaction.objects.filter(decision_id=self.decision.decision_id).count(), 2)

    def test_the_review_scenario_ends_with_the_earlier_impression_as_the_representative(self):
        """검토 재현: 클릭 t+1(허용 기한 t+301), 먼저 받은 노출 t+300.9(커밋 직전), 뒤 노출 t+301.1 — 최종 상태는 이른 노출 인정·클릭 인정·30 과금."""
        click = self.click(when=1)
        with Uncommitted(lambda: self.receive("IMPRESSION", 300.9)) as early:
            later = Worker(lambda: self.receive("IMPRESSION", 301.1))
            later.start()
            self.assert_blocked(later, "뒤 접수")
            early.commit()
        later.join(WAIT)
        rows = list(Reaction.objects.filter(decision_id=self.decision.decision_id, type="IMPRESSION").order_by("received_at"))
        self.assertEqual(len(rows), 2)
        for row in reversed(rows):  # 뒤 노출부터 처리해도
            self.judge(row, 303)
        for row in rows:
            if row.status == "RECEIVED":
                self.judge(row, 304)
        self.judge(click, 304)
        self.assertEqual([r.status for r in rows], ["ACCEPTED", "REJECTED"])
        self.assertEqual(rows[1].reason_code, "duplicate_type")
        self.assertEqual(click.status, "ACCEPTED")
        self.assertEqual(self.balance(), 50_000 - 3 - 294)  # 클릭 98% 세계: 노출 1% · 클릭 98%

    def test_judging_waits_for_an_in_flight_earlier_receipt_and_then_sees_it(self):
        """뒤 반응이 이미 커밋돼 있어도, 판정이 시작될 때 더 이른 시각의 접수가 진행 중이면 그 커밋을 기다린 뒤 판정한다."""
        later, _ = self.receive("IMPRESSION", 301.1)
        with Uncommitted(lambda: self.receive("IMPRESSION", 300.9)) as early:
            judging = Worker(lambda: records.process_reaction(later.inbox_id, now=at(303)))
            judging.start()
            self.assert_blocked(judging, "판정")
            early.commit()
        judging.join(WAIT)
        self.assertEqual(judging.errors, [])
        self.assertEqual(judging.result, "PENDING")  # 더 이른 유효 후보가 있으니 대표가 되지 않고 기다린다
        self.assertEqual(Reaction.objects.get(pk=later.inbox_id).status, "RECEIVED")

    def test_a_click_waits_for_an_in_flight_impression_of_a_later_decision(self):
        """표시 교체 신호(이후 결정의 노출)도 같다: 클릭 t+100 이 커밋돼 있고 이후 결정의 노출 t+90 이 진행 중이면, 판정은 그 커밋을 기다려 `display_ended` 로 거부한다(인정하면 과다 과금)."""
        self.accept_impression()
        second = self.decide(self.w.slot, SUBJECT, when=at(10))
        click = self.click(when=100)
        with Uncommitted(lambda: self.receive("IMPRESSION", 90, decision=second)) as replacement:
            judging = Worker(lambda: records.process_reaction(click.inbox_id, now=at(101)))
            judging.start()
            self.assert_blocked(judging, "클릭 판정")
            replacement.commit()
        judging.join(WAIT)
        self.assertEqual(judging.errors, [])
        self.assertEqual(judging.result, "REJECTED")
        click.refresh_from_db()
        self.assertEqual((click.reason_code, self.balance()), ("display_ended", 50_000 - 3))  # 노출(1%)만 과금

    def test_a_conversion_waits_for_an_in_flight_click_of_its_decision(self):
        self.accept_impression()
        conversion = self.report("CONVERSION", when=50)
        with Uncommitted(lambda: records.observe_click(self.decision.decision_id, None, now=at(40))) as click:
            judging = Worker(lambda: records.process_reaction(conversion.inbox_id, now=at(51)))
            judging.start()
            self.assert_blocked(judging, "전환 판정")
            click.commit()
        judging.join(WAIT)
        self.assertEqual(judging.errors, [])
        self.assertEqual(judging.result, "PENDING")  # 클릭(t+40)이 보이고 아직 처리 전이라 기다린다(클릭이 없다고 거부하지 않는다)

    def test_other_decisions_do_not_wait_for_each_other(self):
        other = self.decide(self.w.slot, "0197a5c0-0000-7000-8000-0000000000b2", when=at(1))  # 다른 사람 = 다른 표시 단위의 다른 결정
        with Uncommitted(lambda: self.receive("IMPRESSION", 10)):
            quick = Worker(lambda: self.receive("IMPRESSION", 11, decision=other))
            quick.start()
            quick.join(10)
            self.assertFalse(quick.is_alive(), "다른 결정의 접수가 막혔다")
            self.assertEqual(quick.errors, [])
            row = Reaction.objects.filter(decision_id=other.decision_id).get()
            judging = Worker(lambda: records.process_reaction(row.inbox_id, now=at(12)))
            judging.start()
            judging.join(10)
            self.assertFalse(judging.is_alive(), "다른 결정의 판정이 막혔다")
            self.assertEqual(judging.result, "ACCEPTED")

    def test_the_receipt_time_is_taken_after_the_lock_is_acquired(self):
        """시각을 잠근 뒤에 정하므로, 앞 접수를 기다린 뒤 받은 반응의 `received_at` 은 앞 접수가 풀린 시각 이후다."""
        released = []
        with Uncommitted(lambda: self.receive("IMPRESSION", 10)) as early:
            later = Worker(lambda: records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", at(11), {}))  # now 를 주입하지 않는다
            later.start()
            self.assert_blocked(later, "뒤 접수")
            released.append(timezone.now())
            early.commit()
        later.join(WAIT)
        self.assertEqual(later.errors, [])
        view, created = later.result
        self.assertTrue(created)
        self.assertGreaterEqual(view.received_at, released[0])  # 기다리기 전에 시각을 정했다면 이보다 이르다


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class ForeignReportsDoNotJoinTheOwnersOrderingTests(FunnelMixin, TransactionTestCase):
    """검토 2-13 후속 P2(974c28b): 접수는 남의 결정에 대한 보고도 저장하지만, 그런 보고가 **결정 소유 매체**의 접수·판정을 기다리게 하거나 막으면 안 된다.

    잠금은 소유 매체의 접수만 잡고(소유 확인은 잠금 전 일반 조회), 판정 앞 대기도 반응의 매체와 결정 소유 매체가 같을 때만 한다.
    """

    UNIT = "CLICK"

    def setUp(self):
        super().setUp()
        self.other = World()  # 다른 매체
        self.foreign = self.other.slot.media_id

    def foreign_receive(self, when):
        return records.receive_reaction(self.foreign, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", at(when), {}, now=at(when))

    def own_receive(self, when):
        return records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", at(when), {}, now=at(when))

    def finishes(self, work, what, seconds=10):
        worker = Worker(work)
        worker.start()
        worker.join(seconds)
        self.assertFalse(worker.is_alive(), f"{what}: 남의 보고가 끝나지 않은 접수에 막혔다")
        self.assertEqual(worker.errors, [])
        return worker.result

    def test_the_owners_receipt_does_not_wait_for_another_medias_in_flight_report(self):
        with Uncommitted(lambda: self.foreign_receive(10)):
            view, created = self.finishes(lambda: self.own_receive(11), "소유 매체의 접수")
        self.assertTrue(created)

    def test_judging_a_foreign_report_does_not_wait_for_the_owners_in_flight_receipt(self):
        foreign_view, _ = self.foreign_receive(10)
        with Uncommitted(lambda: self.own_receive(11)):
            outcome = self.finishes(lambda: records.process_reaction(foreign_view.inbox_id, now=at(12)), "남의 보고의 판정")
        self.assertEqual(outcome, "REJECTED")
        self.assertEqual(Reaction.objects.get(pk=foreign_view.inbox_id).reason_code, "media_mismatch")

    def test_the_owners_judgment_does_not_wait_for_another_medias_in_flight_report_and_does_not_count_a_failure(self):
        """잠금 대기 초과로 소유 매체의 정상 반응에 실패 횟수가 쌓이면 안 된다(자동 재처리에서 빠진다). 판정 연결의 잠금 대기 제한을 1초로 줄여도 기다리지 않는다."""
        mine, _ = self.own_receive(10)
        with Uncommitted(lambda: self.foreign_receive(11)):
            def judge():
                with connection.cursor() as cur:
                    cur.execute("SET SESSION innodb_lock_wait_timeout = 1")
                return records.process_reaction(mine.inbox_id, now=at(12))

            outcome = self.finishes(judge, "소유 매체의 판정")
        self.assertEqual(outcome, "ACCEPTED")
        self.assertEqual(Reaction.objects.get(pk=mine.inbox_id).attempts, 0)

    def test_a_report_for_a_missing_decision_takes_no_lock_and_is_still_stored(self):
        locked = threading.Event()
        view, created = arriving_before("FOR UPDATE", "records_decision", lambda: records.receive_reaction(
            self.media, uuid.uuid4(), uuid.uuid4(), "IMPRESSION", at(1), {}, now=at(1),
        ), locked)()
        self.assertTrue(created)  # 존재 여부를 이유로 접수를 거절하지 않는다(계약)
        self.assertFalse(locked.is_set(), "없는 결정에 대한 접수가 결정 행을 잠갔다")
