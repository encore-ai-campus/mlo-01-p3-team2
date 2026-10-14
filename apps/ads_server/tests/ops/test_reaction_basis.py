"""2-13 판정 근거(`Reaction.basis`, 설계 §10 "판정 근거 기록"): 인정·거부를 정하는 같은 트랜잭션에서 한 번 쓰고 이후 바꾸지 않는다. 보류에는 쓰지 않는다.

목적은 분쟁·감사 때 이후에 쌓이거나 바뀐 데이터로 다시 계산하지 않고 **그때의 판정을 그대로 설명**하는 것이다.
"""
import copy
import json
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import override_settings, tag

from campaigns.models import Campaign
from records import api as records
from records.models import Decision, Reaction
from records.processing import _finish
from tests.support.factories import NOW, SUBJECT, at
from tests.ops.test_funnel_rules import A, FunnelBase
from tests.support.cases import Cases


@tag("security")
class BasisContentTests(Cases, FunnelBase):
    def case_an_accepted_impression_records_what_the_verdict_used(self):
        row = self.accept_impression(when=1)
        basis = row.basis
        self.assertEqual(basis["v"], 3)
        self.assertIsNone(basis["media_deactivated_at"])  # 결정 뒤에 매체를 끈 적이 없다(6-1b)
        self.assertEqual(basis["verdict"], {"rule": None, "reason": None})
        self.assertEqual((basis["person"], basis["audience"], basis["decided_at"]), (SUBJECT, "individual", NOW.isoformat()))
        self.assertEqual(basis["reaction"], {"type": "IMPRESSION", "source": "media", "reported_subject_id": None, "occurred_at": at(1).isoformat(), "received_at": at(1).isoformat()})
        self.assertEqual(basis["judged_at"], at(1).isoformat())
        self.assertEqual(basis["limits_seconds"], {"click_window": 300.0, "display_grace": 5.0, "conversion_window": 30 * 86400.0, "occurred_at_tolerance": 60.0, "hold": 300.0})
        self.assertEqual(basis["campaign_ends_at"], Campaign.objects.get().ends_at.isoformat() if Campaign.objects.get().ends_at else None)
        self.assertEqual(  # 노출은 앞 단계가 없다
            (basis["prerequisite_accepted"], basis["prerequisites_waiting"], basis["prerequisites_waiting_count"], basis["display_signal"]), (None, [], 0, None),
        )

    def case_a_clicks_basis_names_the_impression_it_stood_on(self):
        impression = self.accept_impression(when=0)
        click = self.click(when=3)
        self.judge(click, 3)
        self.assertEqual(click.status, "ACCEPTED")
        self.assertEqual(click.basis["prerequisite_accepted"], {"inbox_id": str(impression.inbox_id), "received_at": at(0).isoformat()})
        self.assertEqual((click.basis["prerequisites_waiting"], click.basis["prerequisites_waiting_count"]), ([], 0))
        self.assertEqual(click.basis["reaction"]["source"], "server")

    def case_a_rejection_records_the_rule_the_reason_and_the_display_signal(self):
        self.accept_impression(when=0)
        second = self.decide(self.w.slot, SUBJECT, when=at(10))
        replacement = self.report("IMPRESSION", second, when=20)  # 다음 광고의 노출이 20초에 도착
        late = self.click(when=30)
        self.judge(late, 30)
        self.assertEqual(self.verdict(late), ("REJECTED", "display_ended", "funnel-window"))
        self.assertEqual(late.basis["verdict"], {"rule": "funnel-window", "reason": "display_ended"})
        self.assertEqual(late.basis["display_signal"], {"received_at": at(20).isoformat(), "inbox_id": str(replacement.inbox_id)})  # 신호가 된 노출까지 남는다
        self.assertEqual(late.basis["limits_seconds"]["display_grace"], 5.0)

    def case_a_report_for_an_unknown_decision_has_no_person_or_audience_only_the_reported_value(self):
        """검토 2-13 보완 ①: 결정이 없으면 판정 단위의 사람이 없다. 보고된 사람은 `reaction.reported_subject_id` 에만 남고 `person` 으로 올라가지 않는다."""
        view, _ = records.receive_reaction(self.media, uuid.uuid4(), uuid.uuid4(), "IMPRESSION", NOW, {}, subject_id=A, now=NOW)
        row = Reaction.objects.get(pk=view.inbox_id)
        self.judge(row, 1)
        self.assertEqual((row.status, row.reason_code), ("REJECTED", "unknown_decision"))
        basis = row.basis
        self.assertEqual((basis["verdict"]["reason"], basis["person"], basis["audience"], basis["decided_at"]), ("unknown_decision", None, None, None))
        self.assertEqual(basis["reaction"]["reported_subject_id"], A)
        self.assertEqual(json.dumps(basis).count(A), 1)  # 보고된 값은 그 한 곳에만 있다
        self.assertEqual((basis["prerequisite_accepted"], basis["prerequisites_waiting"], basis["display_signal"]), (None, [], None))
        self.assertIsNone(row.person_id)

    def case_a_missing_person_in_a_shared_slot_nulls_only_the_person(self):
        """일괄 슬롯에서 사람 없이 보고하면 `subject_required` 로 거부된다. 결정은 있으므로 슬롯 성격·결정 시각은 남고 `person` 만 null 이다."""
        slot, decision = self.shared()
        row = self.report("IMPRESSION", decision, when=1)  # 사람 없는 보고
        self.judge(row, 1)
        self.assertEqual((row.status, row.reason_code), ("REJECTED", "subject_required"))
        basis = row.basis
        self.assertEqual((basis["person"], basis["audience"], basis["decided_at"]), (None, "shared", NOW.isoformat()))
        self.assertIsNone(basis["reaction"]["reported_subject_id"])

    def case_a_shared_slot_report_with_a_person_keeps_it_as_the_judged_person(self):
        slot, decision = self.shared()
        row = self.report("IMPRESSION", decision, when=1, subject=A)
        self.judge(row, 1)
        self.assertEqual(row.status, "ACCEPTED")
        self.assertEqual((row.basis["person"], row.basis["reaction"]["reported_subject_id"]), (A, A))

    def case_waiting_candidates_are_capped_but_the_accepted_one_is_always_kept(self):
        """처리 전 노출 21개와 제때 도착해 인정된 노출 1개: 클릭은 인정되고, 인정된 노출은 상한 없이 남으며, 대기 목록은 상한과 총 개수를 남긴다."""
        accepted = self.accept_impression(when=1)
        waiting = [self.report("IMPRESSION", when=n + 2) for n in range(21)]
        click = self.click(when=30)
        self.judge(click, 30)
        self.assertEqual(click.status, "ACCEPTED")
        basis = click.basis
        self.assertEqual(basis["prerequisite_accepted"], {"inbox_id": str(accepted.inbox_id), "received_at": at(1).isoformat()})
        self.assertEqual((len(basis["prerequisites_waiting"]), basis["prerequisites_waiting_count"], basis["prerequisites_waiting_limit"]), (20, 21, 20))
        self.assertEqual([ref["inbox_id"] for ref in basis["prerequisites_waiting"]], [str(w.inbox_id) for w in waiting[:20]])  # 먼저 도착한 순서
        self.assertNotIn(str(accepted.inbox_id), [ref["inbox_id"] for ref in basis["prerequisites_waiting"]])  # 인정된 것은 대기 목록에 섞이지 않는다

    def test_basis_content(self):
        self.run_cases()


@tag("security")
class BasisLifecycleTests(Cases, FunnelBase):
    def case_a_hold_writes_no_basis_and_the_verdict_writes_it_once(self):
        click = self.click(when=0)
        self.assertEqual(self.judge(click, 1), "PENDING")
        self.assertIsNone(click.basis)  # 보류는 판정이 아니다
        self.assertEqual(click.status, "RECEIVED")
        self.accept_impression(when=2)
        self.assertEqual(self.judge(click, 3), "ACCEPTED")
        self.assertEqual(click.basis["judged_at"], at(3).isoformat())  # 보류 때가 아니라 판정 때의 사실
        self.assertIsNotNone(click.basis["prerequisite_accepted"])

    def case_nothing_that_happens_after_the_verdict_changes_the_basis(self):
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

    def case_a_reaction_cannot_be_finished_without_a_basis(self):
        row = self.report("IMPRESSION", when=0)
        for missing in (None, {}):
            with self.assertRaises(RuntimeError):
                _finish(row, "REJECTED", at(1), missing, reason="x", rule="x")
        self.assertEqual(Reaction.objects.get(pk=row.pk).status, "RECEIVED")

    def case_the_database_requires_a_basis_exactly_when_the_reaction_is_decided(self):
        row = self.accept_impression(when=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reaction.objects.filter(pk=row.pk).update(basis=None)  # 판정한 행에서 근거를 지울 수 없다
        waiting = self.click(when=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reaction.objects.filter(pk=waiting.pk).update(basis={"v": 1})  # 판정 전에 근거를 미리 쓸 수 없다

    def case_the_decision_snapshot_is_untouched_by_judging(self):
        before = Decision.objects.values().get(pk=self.decision.decision_id)
        self.accept_impression(when=0)
        self.assertEqual(Decision.objects.values().get(pk=self.decision.decision_id), before)

    def test_basis_lifecycle(self):
        self.run_cases()
