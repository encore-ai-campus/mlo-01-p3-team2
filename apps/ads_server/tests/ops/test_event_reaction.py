"""Step 4-1c: 반응 이벤트 — 접수(`ad.reaction_received`)와 판정(`ad.reaction`)은 각자의 상태 변경과 같은 트랜잭션에서 outbox 에 쓰인다."""
import uuid
from datetime import timedelta
from unittest import mock

from django.test import TransactionTestCase, tag

from events import schemas
from events.models import EventOutbox
from records import api as records
from records.models import Reaction
from tests.support.factories import NOW, SUBJECT
from tests.ops.test_records_processing import ProcessingBase
from tests.support.cases import Cases


def events_of(name):
    return list(EventOutbox.objects.filter(event_name=name).order_by("created_at"))


@tag("security")
class ReceivedEventTests(Cases, ProcessingBase):
    def case_a_report_leaves_one_received_event_with_the_reported_facts(self):
        view = self.receive("IMPRESSION")
        row = self.row(view)
        (event,) = events_of(schemas.REACTION_RECEIVED)
        self.assertEqual(event.event_id, schemas.event_id_of(schemas.REACTION_RECEIVED, row.inbox_id))
        self.assertEqual(event.aggregate_id, self.decision.decision_id)
        p = event.payload
        self.assertEqual((p["inbox_id"], p["reaction_id"], p["media_id"], p["decision_id"], p["type"], p["source"]),
                         (str(row.inbox_id), str(row.reaction_id), str(row.media_id), str(row.decision_id), "IMPRESSION", "media"))
        self.assertEqual((p["raw"], p["subject_id"], p["received_at"]), (row.raw, None, "2026-10-07T12:00:00+00:00"))
        self.assertNotIn("person_id", p)  # 접수는 판정이 아니다

    def case_a_resend_of_the_same_report_adds_no_event(self):
        rid = uuid.uuid4()
        self.receive("IMPRESSION", reaction_id=rid)
        again, created = records.receive_reaction(self.media, self.decision.decision_id, rid, "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        self.assertFalse(created)
        self.assertEqual(len(events_of(schemas.REACTION_RECEIVED)), 1)

    def case_a_report_for_an_unknown_decision_is_still_received(self):
        """없는 결정의 보고도 받는다(유실 방지) — 이벤트도 남는다."""
        self.receive("IMPRESSION", decision_id=uuid.uuid4())
        self.assertEqual(len(events_of(schemas.REACTION_RECEIVED)), 1)

    def case_a_server_observed_click_is_a_received_event_with_source_server(self):
        row = self.click(self.decision.decision_id)
        (event,) = events_of(schemas.REACTION_RECEIVED)
        self.assertEqual((event.payload["source"], event.payload["type"], event.payload["inbox_id"]), ("server", "CLICK", str(row.inbox_id)))

    def case_held_reactions_are_visible_before_they_are_judged(self):
        """보류·대기 중인 반응도 접수 이벤트로 바로 보인다(Bronze 입력)."""
        click = self.click()  # 서버가 관측한 클릭이 노출보다 먼저 왔다
        self.assertEqual(records.process_reaction(click.inbox_id, now=NOW), "PENDING")  # 노출이 아직 없어 보류
        self.assertEqual((len(events_of(schemas.REACTION_RECEIVED)), len(events_of(schemas.REACTION))), (1, 0))

    def test_received_event(self):
        self.run_cases()


@tag("security")
class JudgedEventTests(Cases, ProcessingBase):
    def case_an_accepted_reaction_leaves_one_judged_event_with_the_basis(self):
        view = self.receive("IMPRESSION")
        self.assertEqual(self.process(view), "ACCEPTED")
        row = self.row(view)
        (event,) = events_of(schemas.REACTION)
        self.assertEqual(event.event_id, schemas.event_id_of(schemas.REACTION, row.inbox_id))
        p = event.payload
        self.assertEqual((p["status"], p["reason_code"], p["applied_rule"]), ("ACCEPTED", None, None))
        self.assertEqual((p["person_id"], p["audience"]), (row.person_id, "individual"))
        self.assertEqual(p["basis"], row.basis)  # 판정 근거가 그대로 실린다
        self.assertEqual(event.created_at, NOW)

    def case_a_rejected_reaction_is_an_event_too_with_the_reason(self):
        view = self.receive("IMPRESSION", decision_id=uuid.uuid4())
        self.assertEqual(self.process(view), "REJECTED")
        (event,) = events_of(schemas.REACTION)
        p = event.payload
        self.assertEqual((p["status"], p["reason_code"], p["applied_rule"]), ("REJECTED", "unknown_decision", "known-decision"))
        self.assertEqual((p["person_id"], p["audience"]), (None, None))  # null 규칙: 없는 결정
        self.assertEqual(event.aggregate_id, uuid.UUID(p["decision_id"]))

    def case_the_reported_subject_is_not_the_judged_person(self):
        """보고된 사람(subject_id)과 판정 단위의 사람(person_id)은 따로 실린다."""
        reported = "0197a5c0-0000-7000-8000-0000000000ff"  # 결정의 사람과 다른 사람이라고 보고
        view, _ = records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, subject_id=reported, now=NOW)
        self.assertEqual(self.process(view), "REJECTED")
        p = events_of(schemas.REACTION)[0].payload
        self.assertEqual((p["subject_id"], p["person_id"]), (reported, SUBJECT))  # 거부 행의 person_id 열은 비어 있어도 이벤트는 basis 의 판정 단위 사람을 싣는다
        self.assertIsNone(self.row(view).person_id)

    def case_nothing_while_held_and_one_event_once_judged(self):
        click = self.click(at=NOW + timedelta(seconds=1))
        self.assertEqual(records.process_reaction(click.inbox_id, now=NOW + timedelta(seconds=2)), "PENDING")
        self.assertEqual(len(events_of(schemas.REACTION)), 0)  # 보류는 판정이 아니다
        imp = self.receive("IMPRESSION")
        self.process(imp)
        self.assertEqual(records.process_reaction(click.inbox_id, now=NOW + timedelta(seconds=3)), "ACCEPTED")
        self.assertEqual(sorted(e.payload["type"] for e in events_of(schemas.REACTION)), ["CLICK", "IMPRESSION"])

    def case_processing_again_adds_no_event(self):
        view = self.receive("IMPRESSION")
        self.process(view)
        self.assertIsNone(self.process(view))  # 이미 처리됨
        self.assertEqual(len(events_of(schemas.REACTION)), 1)

    def test_judged_event(self):
        self.run_cases()


class JudgedEventAtomicityTests(Cases, TransactionTestCase):
    def case_if_the_event_cannot_be_written_the_reaction_stays_received_and_is_not_charged(self):
        from random import Random

        from billing.models import LedgerEntry
        from records import api as rec
        from tests.support.factories import SUBJECT, World

        w = World()
        decision = rec.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = rec.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        with mock.patch("records.processing.events.record_reaction", side_effect=RuntimeError("outbox 실패")):
            with self.assertRaises(RuntimeError):
                rec.process_reaction(view.inbox_id, now=NOW)
        self.assertEqual(Reaction.objects.get(pk=view.inbox_id).status, "RECEIVED")  # 판정은 됐는데 이벤트가 없는 상태가 없다
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 0)
        self.assertEqual(rec.process_reaction(view.inbox_id, now=NOW), "ACCEPTED")  # 복구되면 이어서 처리된다
        self.assertEqual(EventOutbox.objects.filter(event_name=schemas.REACTION).count(), 1)

    def case_if_the_received_event_cannot_be_written_the_report_is_not_stored(self):
        from random import Random

        from records import api as rec
        from tests.support.factories import SUBJECT, World

        w = World()
        decision = rec.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        with mock.patch("records.services.events.record_reaction_received", side_effect=RuntimeError("outbox 실패")):
            with self.assertRaises(RuntimeError):
                rec.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        self.assertEqual(Reaction.objects.count(), 0)  # 2xx 를 보내지 않았으니 매체가 다시 보낸다
        self.assertEqual(EventOutbox.objects.filter(event_name=schemas.REACTION_RECEIVED).count(), 0)

    def test_judged_event_atomicity(self):
        self.run_cases()
