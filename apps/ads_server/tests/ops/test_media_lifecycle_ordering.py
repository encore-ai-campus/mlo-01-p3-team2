"""매체 생명주기 잠금(설계 §10 "매체 비활성화와 판정·결정의 순서", 6-2): 매체 비활성화가 **아직 커밋되지 않았을 때** 판정·결정이 커밋 전 상태로 굳지 않는다.

외부 검토(7c4714b) P2: 비활성화 시각 뒤에 접수된 두 반응 중 비활성화 커밋 전에 판정한 쪽은 인정·과금되고, 커밋 뒤에 판정한 쪽은 `media_deactivated` 로
거부됐다 — 판정의 일반 조회가 비활성화의 커밋을 기다리지 않아서다(6-2a). 같은 구간의 결정 요청은 매체를 활성으로 보고 비활성화보다 뒤의 결정을 만들어,
다시 켠 뒤 그 결정의 반응이 인정됐다(구현 세션 재현, 6-2b). 실제 MySQL 연결을 스레드마다 하나씩 쓰고, 비활성화 트랜잭션의 커밋을 미뤄 순서를 고정한다(시각은 `now=` 로 주입).
"""
import threading
import uuid
from random import Random

from django.test import TransactionTestCase, override_settings, tag

from billing.models import LedgerEntry
from foundation.api import errors
from masters import api as masters
from records import api as records
from records.models import Decision, Reaction
from tests.support.concurrency import BLOCKED, WAIT, Uncommitted, Worker, arriving_before, pausing_before
from tests.support.factories import SUBJECT, World, at

OTHER_SUBJECT = "0197a5c0-0000-7000-8000-000000000002"
THIRD_SUBJECT = "0197a5c0-0000-7000-8000-000000000003"


class MediaLifecycleBase(TransactionTestCase):
    def setUp(self):
        self.w = World()
        self.media = self.w.slot.media_id
        self.decision = self.decide(self.w, SUBJECT)

    def decide(self, world, subject, when=0):
        return records.decide(world.slot.media_id, world.slot.slot_id, subject_id=subject, now=at(when), rng=Random(1))

    def receive(self, when, decision=None, media=None):
        decision = decision or self.decision
        view, _ = records.receive_reaction(media or decision.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", at(when), {}, now=at(when))
        return view

    def deactivation(self, when):
        """이 매체를 `when` 초에 끄는 트랜잭션(커밋을 미룬다)."""
        return Uncommitted(lambda: masters.set_media_active(self.w.admin, self.media, False, now=at(when)))

    def blocked(self, work, what, fragment="FOR SHARE"):
        """별도 연결에서 `work` 를 시작하고, 매체 행에 대한 `fragment` 질의에 닿은 뒤 **거기서 막혀 있음**을 확인한다(느린 실행이 아니라 잠금 대기)."""
        arrived = threading.Event()
        worker = Worker(arriving_before(fragment, "masters_media", work, arrived))
        worker.start()
        self.assertTrue(arrived.wait(WAIT), worker.errors)
        worker.join(BLOCKED)
        self.assertTrue(worker.is_alive(), f"{what}: 진행 중인 트랜잭션을 기다리지 않았다")
        return worker

    def finishes(self, work, what):
        """상대 트랜잭션이 커밋되기 전에 끝난다(= 기다리지 않는다). 막히면 상대가 `WAIT` 뒤 스스로 풀리기 전까지 끝나지 않는다."""
        worker = Worker(work)
        worker.start()
        worker.join(10)
        self.assertFalse(worker.is_alive(), f"{what}: 막혔다")
        self.assertEqual(worker.errors, [])
        return worker.result

    def row(self, view):
        return Reaction.objects.get(pk=view.inbox_id)


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class JudgmentWaitsForDeactivationTests(MediaLifecycleBase):
    """판정 쪽(6-2a): 판정 앞 대기가 결정 행 다음에 결정 소유 매체 행을 공유 잠금으로 지나간다."""

    def judging(self, view, when):
        return self.blocked(lambda: records.process_reaction(view.inbox_id, now=at(when)), "판정")

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


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class DecisionWaitsForDeactivationTests(MediaLifecycleBase):
    """결정 쪽(6-2b): 결정 저장 트랜잭션이 매체 행을 공유 잠금으로 다시 읽고 커밋까지 쥔다."""

    def decisions(self):
        return Decision.objects.filter(media_id=self.media).count()

    def test_a_decision_requested_during_an_in_flight_deactivation_waits_and_is_forbidden(self):
        """재현: +10 에 끄는 트랜잭션이 커밋 전일 때 +15 결정 요청 — 전에는 활성으로 보고 비활성화보다 뒤의 결정을 만들었다. 이제 커밋을 기다린 뒤 403, 결정 없음."""
        before = self.decisions()
        with self.deactivation(10) as off:
            worker = self.blocked(lambda: self.decide(self.w, OTHER_SUBJECT, when=15), "결정")
            off.commit()
        worker.join(WAIT)
        self.assertEqual([type(error) for error in worker.errors], [errors.Forbidden])
        self.assertEqual(self.decisions(), before)

    def test_a_deactivation_waits_for_an_in_flight_decision_which_it_then_ends(self):
        """진행 중인 결정이 있으면 비활성화가 그 커밋을 기다린다 — 그 결정은 비활성화보다 앞이 되고, 다시 켠 뒤 접수된 반응은 `media_deactivated`.
        결정을 **저장 직전**에 멈춘다(결정이 스스로 연 트랜잭션): 활성 확인의 잠금이 그 트랜잭션 끝까지 쥐어져 있어야 한다."""
        paused, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        decision = Worker(pausing_before("INSERT", "records_decision", lambda: self.decide(self.w, OTHER_SUBJECT, when=15), paused, release))
        decision.start()
        self.assertTrue(paused.wait(WAIT), decision.errors)
        worker = self.blocked(lambda: masters.set_media_active(self.w.admin, self.media, False, now=at(20)), "비활성화", fragment="UPDATE")
        release.set()
        decision.join(WAIT)
        worker.join(WAIT)
        self.assertEqual((decision.errors, worker.errors), ([], []))
        masters.set_media_active(self.w.admin, self.media, True, now=at(25))
        view = self.receive(30, decision.result)
        self.assertEqual(records.process_reaction(view.inbox_id, now=at(30)), "REJECTED")
        self.assertEqual(self.row(view).reason_code, "media_deactivated")

    def test_decisions_do_not_block_each_other(self):
        """공유 잠금끼리는 충돌하지 않는다: 진행 중인 결정이 같은 매체의 다른 결정을 막지 않는다(배타 잠금이면 매체 하나의 결정이 줄을 선다)."""
        with Uncommitted(lambda: self.decide(self.w, OTHER_SUBJECT, when=15)):
            self.finishes(lambda: self.decide(self.w, THIRD_SUBJECT, when=16), "같은 매체의 다른 결정")

    def test_another_medias_decision_does_not_wait(self):
        """잠금은 매체 단위다: 이 매체를 끄는 중이어도 다른 매체의 결정은 막히지 않는다."""
        other = World()
        with self.deactivation(10):
            self.finishes(lambda: self.decide(other, SUBJECT, when=15), "다른 매체의 결정")
