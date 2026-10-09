"""2-13 판정 근거(`Reaction.basis`, 설계 §10 "판정 근거 기록"): 인정·거부를 정하는 같은 트랜잭션에서 한 번 쓰고 이후 바꾸지 않는다. 보류에는 쓰지 않는다.

목적은 분쟁·감사 때 이후에 쌓이거나 바뀐 데이터로 다시 계산하지 않고 **그때의 판정을 그대로 설명**하는 것이다.
"""
import copy
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import override_settings, tag

from campaigns.models import Campaign
from records import api as records
from records.models import Decision, Reaction
from records.processing import _finish
from tests.factories import NOW, SUBJECT
from tests.test_funnel_rules import FunnelBase, at


@tag("security")
class BasisContentTests(FunnelBase):
    def test_an_accepted_impression_records_what_the_verdict_used(self):
        row = self.accept_impression(when=1)
        basis = row.basis
        self.assertEqual(basis["v"], 1)
        self.assertEqual(basis["verdict"], {"rule": None, "reason": None})
        self.assertEqual((basis["person"], basis["audience"], basis["decided_at"]), (SUBJECT, "individual", NOW.isoformat()))
        self.assertEqual(basis["reaction"], {"type": "IMPRESSION", "source": "media", "reported_subject_id": None, "occurred_at": at(1).isoformat(), "received_at": at(1).isoformat()})
        self.assertEqual(basis["judged_at"], at(1).isoformat())
        self.assertEqual(basis["limits_seconds"], {"click_window": 300.0, "display_grace": 5.0, "conversion_window": 30 * 86400.0, "occurred_at_tolerance": 60.0, "hold": 300.0})
        self.assertEqual(basis["campaign_ends_at"], Campaign.objects.get().ends_at.isoformat() if Campaign.objects.get().ends_at else None)
        self.assertEqual((basis["prerequisites"], basis["prerequisite_count"], basis["display_signal"]), ([], 0, None))  # 노출은 앞 단계가 없다

    def test_a_clicks_basis_names_the_impression_it_stood_on(self):
        impression = self.accept_impression(when=0)
        click = self.click(when=3)
        self.judge(click, 3)
        self.assertEqual(click.status, "ACCEPTED")
        ref, = click.basis["prerequisites"]
        self.assertEqual(ref, {"inbox_id": str(impression.inbox_id), "status": "ACCEPTED", "received_at": at(0).isoformat()})
        self.assertEqual(click.basis["prerequisite_count"], 1)
        self.assertEqual(click.basis["reaction"]["source"], "server")

    def test_a_rejection_records_the_rule_the_reason_and_the_display_signal(self):
        self.accept_impression(when=0)
        second = self.decide(self.w.slot, SUBJECT, when=at(10))
        replacement = self.report("IMPRESSION", second, when=20)  # 다음 광고의 노출이 20초에 도착
        late = self.click(when=30)
        self.judge(late, 30)
        self.assertEqual(self.verdict(late), ("REJECTED", "display_ended", "funnel-window"))
        self.assertEqual(late.basis["verdict"], {"rule": "funnel-window", "reason": "display_ended"})
        self.assertEqual(late.basis["display_signal"], {"received_at": at(20).isoformat(), "inbox_id": str(replacement.inbox_id)})  # 신호가 된 노출까지 남는다
        self.assertEqual(late.basis["limits_seconds"]["display_grace"], 5.0)

    def test_a_rejected_report_for_an_unknown_decision_still_has_a_basis(self):
        view, _ = records.receive_reaction(self.media, uuid.uuid4(), uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        row = Reaction.objects.get(pk=view.inbox_id)
        self.judge(row, 1)
        self.assertEqual(row.reason_code, "unknown_decision")
        self.assertEqual((row.basis["verdict"]["reason"], row.basis["audience"], row.basis["decided_at"]), ("unknown_decision", None, None))

    def test_a_long_list_of_prerequisites_is_capped_and_counted(self):
        self.accept_impression(when=1)
        for n in range(24):  # 나머지는 처리 전(RECEIVED)으로 둔다 — 인정된 노출이 하나 있으면 클릭은 통과한다
            self.report("IMPRESSION", when=n + 2)
        click = self.click(when=30)
        self.judge(click, 30)
        self.assertEqual((len(click.basis["prerequisites"]), click.basis["prerequisite_count"]), (20, 25))


@tag("security")
class BasisLifecycleTests(FunnelBase):
    def test_a_hold_writes_no_basis_and_the_verdict_writes_it_once(self):
        click = self.click(when=0)
        self.assertEqual(self.judge(click, 1), "PENDING")
        self.assertIsNone(click.basis)  # 보류는 판정이 아니다
        self.assertEqual(click.status, "RECEIVED")
        self.accept_impression(when=2)
        self.assertEqual(self.judge(click, 3), "ACCEPTED")
        self.assertEqual(click.basis["judged_at"], at(3).isoformat())  # 보류 때가 아니라 판정 때의 사실
        self.assertEqual(len(click.basis["prerequisites"]), 1)

    def test_nothing_that_happens_after_the_verdict_changes_the_basis(self):
        self.accept_impression(when=0)
        click = self.click(when=3)
        self.judge(click, 3)
        before = copy.deepcopy(Reaction.objects.get(pk=click.pk).basis)
        # 판정 뒤의 변화: 다음 광고의 노출 도착, 캠페인 연장·종료 변경, 설정 변경, 같은 반응의 재처리
        self.report("IMPRESSION", self.decide(self.w.slot, SUBJECT, when=at(10)), when=11)
        Campaign.objects.update(ends_at=NOW + timedelta(days=10))
        with override_settings(REACTION_CLICK_WINDOW_SECONDS=1, REACTION_DISPLAY_GRACE_SECONDS=0):
            self.assertIsNone(records.process_reaction(click.inbox_id, now=at(500)))  # 이미 끝난 반응은 건드리지 않는다
        self.assertEqual(Reaction.objects.get(pk=click.pk).basis, before)

    def test_finishing_a_reaction_again_cannot_overwrite_the_basis(self):
        row = self.accept_impression(when=0)
        before = copy.deepcopy(row.basis)
        with self.assertRaises(RuntimeError):
            _finish(row, "REJECTED", at(9), {"v": 1, "forged": True}, reason="x", rule="x")
        self.assertEqual(Reaction.objects.get(pk=row.pk).basis, before)

    def test_a_reaction_cannot_be_finished_without_a_basis(self):
        row = self.report("IMPRESSION", when=0)
        for missing in (None, {}):
            with self.assertRaises(RuntimeError):
                _finish(row, "REJECTED", at(1), missing, reason="x", rule="x")
        self.assertEqual(Reaction.objects.get(pk=row.pk).status, "RECEIVED")

    def test_the_database_requires_a_basis_exactly_when_the_reaction_is_decided(self):
        row = self.accept_impression(when=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reaction.objects.filter(pk=row.pk).update(basis=None)  # 판정한 행에서 근거를 지울 수 없다
        waiting = self.click(when=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reaction.objects.filter(pk=waiting.pk).update(basis={"v": 1})  # 판정 전에 근거를 미리 쓸 수 없다

    def test_the_decision_snapshot_is_untouched_by_judging(self):
        before = Decision.objects.values().get(pk=self.decision.decision_id)
        self.accept_impression(when=0)
        self.assertEqual(Decision.objects.values().get(pk=self.decision.decision_id), before)
