"""2-13 판정 사실의 매체 격리(설계 §10 "판정 사실의 범위"): 판정에 쓰는 반응은 **결정 소유 매체가 보낸 것**(개인 슬롯은 + 보고된 사람이 없거나 결정의 사람)뿐이다.

접수는 존재를 알리지 않으려고 남의 결정에 대한 보고도 저장한다. 그래서 범위가 없으면 다른 매체의 노출이 (가) 기존 광고의 클릭 창을 닫고 (나) 처리 전인 동안 클릭을 보류시킨다.
시각은 모두 고정한다(결정 `NOW`, 반응은 `NOW + 몇 초`에 수신, 판정은 `now=` 로 주입).
"""
import uuid

from django.test import tag

from records import api as records
from records.models import Reaction
from tests.factories import SUBJECT, World
from tests.test_funnel_rules import A, B, FunnelBase, at


class ScopeBase(FunnelBase):
    def foreign_impression(self, decision, when):
        """다른 매체가 **우리 결정**에 대해 노출을 보고했다(접수는 존재를 알리지 않으므로 저장된다)."""
        self.other = getattr(self, "other", None) or World()
        view, created = records.receive_reaction(self.other.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", at(when), {}, now=at(when))
        self.assertTrue(created)
        return Reaction.objects.get(pk=view.inbox_id)

    def probe(self, decision, seconds):
        Reaction.objects.filter(decision_id=decision.decision_id, type="CLICK").delete()
        row = self.click(decision, when=seconds)
        self.judge(row, seconds)
        return row.reason_code or row.status


@tag("security")
class DisplaySignalScopeTests(ScopeBase):
    def test_another_medias_impression_is_not_a_display_replacement_signal(self):
        self.accept_impression()
        second = self.decide(self.w.slot, SUBJECT, when=at(10))  # 같은 슬롯·사람의 다음 결정
        self.foreign_impression(second, when=20)  # 다른 매체가 그 결정에 노출을 보고
        self.assertEqual(self.probe(self.decision, 100), "ACCEPTED")  # 기존 광고의 클릭 창이 닫히지 않는다

    def test_an_impression_reported_for_another_person_in_an_individual_slot_is_not_a_signal(self):
        self.accept_impression()
        second = self.decide(self.w.slot, SUBJECT, when=at(10))
        self.report("IMPRESSION", second, when=20, subject=A)  # 같은 매체지만 다른 사람이라고 보고
        self.assertEqual(self.probe(self.decision, 100), "ACCEPTED")
        self.report("IMPRESSION", second, when=30, subject=SUBJECT)  # 이 사람이라고 보고하면 신호다
        self.assertEqual(self.probe(self.decision, 100), "display_ended")

    def test_a_new_decision_without_an_impression_keeps_the_current_display(self):
        self.accept_impression()
        self.decide(self.w.slot, SUBJECT, when=at(10))
        self.assertEqual(self.probe(self.decision, 100), "ACCEPTED")

    def test_in_a_normal_shared_slot_any_viewers_impression_of_the_same_media_is_a_signal(self):
        slot, decision = self.shared()
        self.accept_impression(decision, subject=A)
        later = self.decide(slot, None, when=at(10))
        self.foreign_impression(later, when=11)  # 다른 매체의 노출은 신호가 아니다
        self.assertEqual(self.probe_viewer(decision, A, 15), "ACCEPTED")
        self.report("IMPRESSION", later, when=16, subject=B)  # 같은 매체의 다른 시청자(B)의 노출은 신호다
        self.assertEqual(self.probe_viewer(decision, A, 22), "display_ended")

    def probe_viewer(self, decision, viewer, seconds):
        Reaction.objects.filter(decision_id=decision.decision_id, type="CLICK", subject_id=viewer).delete()
        row = self.click(decision, when=seconds, viewer=viewer)
        self.judge(row, seconds)
        return row.reason_code or row.status


@tag("security")
class PrerequisiteScopeTests(ScopeBase):
    def test_another_medias_unprocessed_impression_does_not_hold_a_click(self):
        """처리 전인 남의 노출이 '앞 단계가 곧 올 것'으로 보여 클릭을 보류시키면 판정 시점이 남의 처리 순서에 따라 달라진다."""
        click = self.click(when=0)  # 우리 노출은 없다
        self.foreign_impression(self.decision, when=1)  # 다른 매체의 노출: 처리 전(RECEIVED)
        hold = 300
        self.assertEqual(self.judge(click, hold), "REJECTED")  # 기한에 맞춰 missing_prerequisite
        self.assertEqual(self.verdict(click), ("REJECTED", "missing_prerequisite", "funnel-order"))

    def test_an_impression_reported_for_another_person_is_not_a_prerequisite_of_this_persons_click(self):
        click = self.click(when=0)
        self.report("IMPRESSION", when=1, subject=A)  # 이 결정(SUBJECT)에 다른 사람이라고 보고된 노출 — 처리 전
        self.assertEqual(self.judge(click, 300), "REJECTED")
        self.assertEqual(click.reason_code, "missing_prerequisite")

    def test_the_accepted_types_lookup_is_scoped_too(self):
        """인정된 유형 조회도 범위를 거친다: 다른 매체가 같은 결정에 남긴 행(인정으로 위조된 행 포함)은 '이미 인정'으로 세지 않는다."""
        from records import facts

        forged = self.foreign_impression(self.decision, when=1)
        Reaction.objects.filter(pk=forged.pk).update(
            status="ACCEPTED", processed_at=at(1), person_id=SUBJECT, accepted_key=f"forged:{uuid.uuid4()}", basis={"v": 1},
        )
        row = self.report("IMPRESSION", when=2)
        self.assertEqual(facts.gather(row, self.decision_row(), at(2)).accepted_types, frozenset())

    def decision_row(self):
        from records.models import Decision

        return Decision.objects.get(pk=self.decision.decision_id)
