"""매체 생명주기 잠금(설계 §10 "매체 비활성화와 판정·결정의 순서", 6-2): 매체 비활성화가 **아직 커밋되지 않았을 때** 판정이 커밋 전 상태로 굳지 않는다.

외부 검토(a70d769) P2: 비활성화 시각 뒤에 접수된 두 반응 중 비활성화 커밋 전에 판정한 쪽은 인정·과금되고, 커밋 뒤에 판정한 쪽은 `media_deactivated` 로
거부됐다 — 판정의 일반 조회가 비활성화의 커밋을 기다리지 않아서다. 실제 MySQL 연결을 스레드마다 하나씩 쓰고, 비활성화 트랜잭션의 커밋을 미뤄 순서를 고정한다(시각은 `now=` 로 주입).
"""
import threading
import uuid
from datetime import timedelta
from random import Random

from django.test import TransactionTestCase, override_settings, tag

from billing.models import LedgerEntry
from masters import api as masters
from records import api as records
from records.models import Reaction
from tests.concurrency import BLOCKED, WAIT, Uncommitted, Worker, arriving_before
from tests.factories import NOW, SUBJECT, World

OTHER_SUBJECT = "0197a5c0-0000-7000-8000-000000000002"


def at(seconds):
    return NOW + timedelta(seconds=seconds)


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class JudgmentWaitsForDeactivationTests(TransactionTestCase):
    def setUp(self):
        self.w = World()
        self.media = self.w.slot.media_id
        self.decision = self.decide(self.w, SUBJECT)

    def decide(self, world, subject):
        return records.decide(world.slot.media_id, world.slot.slot_id, subject_id=subject, now=NOW, rng=Random(1))

    def receive(self, when, decision=None, media=None):
        decision = decision or self.decision
        view, _ = records.receive_reaction(media or decision.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", at(when), {}, now=at(when))
        return view

    def deactivation(self, when):
        """이 매체를 `when` 초에 끄는 트랜잭션(커밋을 미룬다)."""
        return Uncommitted(lambda: masters.set_media_active(self.w.admin, self.media, False, now=at(when)))

    def judging(self, view, when):
        """별도 연결에서 판정을 시작하고, 매체 행 공유 잠금에 닿을 때까지 기다린다(그 뒤의 `is_alive()` 는 그 잠금에서의 대기다)."""
        arrived = threading.Event()
        worker = Worker(arriving_before("FOR SHARE", "masters_media", lambda: records.process_reaction(view.inbox_id, now=at(when)), arrived))
        worker.start()
        self.assertTrue(arrived.wait(WAIT), worker.errors)
        worker.join(BLOCKED)
        self.assertTrue(worker.is_alive(), "판정이 진행 중인 비활성화를 기다리지 않았다")
        return worker

    def finishes(self, work, what):
        """비활성화가 커밋되기 전에 끝난다(= 기다리지 않는다). 막히면 비활성화가 `WAIT` 뒤 스스로 풀리기 전까지 끝나지 않는다."""
        worker = Worker(work)
        worker.start()
        worker.join(10)
        self.assertFalse(worker.is_alive(), f"{what}: 다른 매체의 비활성화에 막혔다")
        self.assertEqual(worker.errors, [])
        return worker.result

    def row(self, view):
        return Reaction.objects.get(pk=view.inbox_id)

    def test_the_review_scenario_judges_both_reactions_the_same_whatever_the_order(self):
        """검토 재현: +10 에 끄는 트랜잭션이 커밋 전일 때 +20 에 접수된 두 반응 — 커밋 전에 시작한 판정도 커밋을 기다렸다가 거부한다.
        커밋 뒤에 판정한 반응과 상태·사유·근거가 같고 과금은 없다."""
        second_decision = self.decide(self.w, OTHER_SUBJECT)  # 같은 유형 1회 조건과 섞이지 않게 사람을 나눈다
        with self.deactivation(10) as off:
            first, second = self.receive(20), self.receive(20, second_decision)
            worker = self.judging(first, 20)
            off.commit()
        worker.join(WAIT)
        self.assertEqual((worker.errors, worker.result), ([], "REJECTED"))
        self.assertEqual(records.process_reaction(second.inbox_id, now=at(20)), "REJECTED")
        for view in (first, second):
            row = self.row(view)
            self.assertEqual((row.reason_code, row.applied_rule, row.basis["media_deactivated_at"]), ("media_deactivated", "media-period", at(10).isoformat()))
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 0)

    def test_a_reaction_received_before_the_in_flight_deactivation_is_still_accepted(self):
        """기다려도 비활성화 전에 접수된 반응의 판정은 그대로다(늦게 판정해도 인정)."""
        view = self.receive(5)
        with self.deactivation(10) as off:
            worker = self.judging(view, 30)
            off.commit()
        worker.join(WAIT)
        self.assertEqual((worker.errors, worker.result), ([], "ACCEPTED"))
        self.assertIsNone(self.row(view).basis["media_deactivated_at"])

    def test_another_medias_report_on_this_decision_does_not_wait(self):
        """남의 결정에 대한 보고는 기다리지 않는다(판정은 어차피 매체 불일치) — 다른 매체가 이 매체의 비활성화 대기에 끼지 않는다."""
        other = World()
        view = self.receive(20, media=other.slot.media_id)
        with self.deactivation(10):
            outcome = self.finishes(lambda: records.process_reaction(view.inbox_id, now=at(20)), "남의 보고의 판정")
        self.assertEqual((outcome, self.row(view).reason_code), ("REJECTED", "media_mismatch"))

    def test_judging_another_medias_reaction_does_not_wait(self):
        """잠금은 매체 단위다: 이 매체를 끄는 중이어도 다른 매체 반응의 판정은 막히지 않는다."""
        other = World()
        view = self.receive(20, self.decide(other, SUBJECT))
        with self.deactivation(10):
            outcome = self.finishes(lambda: records.process_reaction(view.inbox_id, now=at(20)), "다른 매체 반응의 판정")
        self.assertEqual(outcome, "ACCEPTED")
