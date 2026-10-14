"""Step 4-1b: 결정 이벤트(`ad.decision`)는 결정과 같은 트랜잭션에서 outbox 에 쓰인다."""
import uuid
from unittest import mock

from django.db import OperationalError, connection
from django.test import TestCase, TransactionTestCase, tag
from django.test.utils import CaptureQueriesContext

from events import schemas
from events.models import EventOutbox
from masters import api as masters
from records import api as records
from records.models import Decision
from tests.support.factories import NOW, SHARES, SUBJECT, World
from tests.ops.test_serving_decisions import DecisionApiBase


def decide(w, **kw):
    return records.decide(w.slot.media_id, w.slot.slot_id, subject_id=kw.pop("subject_id", SUBJECT), now=NOW, **kw)


@tag("security")
class DecisionEventTests(TestCase):
    def test_one_event_per_decision_matching_the_stored_snapshot(self):
        """입찰을 상한(500) 위로 둔다 — 이벤트는 입찰 금액과 적용 금액(과금의 근거)을 따로 싣는다."""
        w = World()
        w.api.add_bid(w.adv, w.group.ad_group_id, 800, expected_version=1, now=NOW)
        view = decide(w)
        row = EventOutbox.objects.get()
        d = Decision.objects.get(pk=view.decision_id)
        self.assertEqual((row.event_name, row.aggregate_id, row.event_id), ("ad.decision", d.decision_id, schemas.event_id_of(schemas.DECISION, d.decision_id)))
        p = row.payload
        self.assertEqual((p["decision_id"], p["media_id"], p["slot_id"], p["audience"], p["subject_id"]), (str(d.decision_id), str(d.media_id), str(d.slot_id), "individual", SUBJECT))
        self.assertEqual(p["selected"], {
            "campaign_id": str(d.campaign_id), "ad_group_id": str(d.ad_group_id), "creative_id": str(d.creative_id),
            "charge_shares": {"IMPRESSION": d.impression_share, "CLICK": d.click_share, "CONVERSION": d.conversion_share},
            "bid_id": str(d.bid_id), "bid_version": d.bid_version, "bid_policy_id": str(d.bid_policy_id), "policy_version": d.policy_version,
            "bid_amount": d.bid_amount, "applied_amount": d.applied_amount,
        })
        self.assertEqual((d.bid_amount, d.applied_amount), (800, 500))
        self.assertEqual((p["selection_policy"], p["candidate_count"], p["rejected_counts"]), (d.selection_policy, d.candidate_count, d.rejected_counts))
        self.assertNotIn(str(d.owner_id), str(p))  # 광고주 계정은 싣지 않는다

    def test_a_decision_without_an_ad_is_still_an_event(self):
        w = World(with_creative=False)
        decide(w)
        row = EventOutbox.objects.get()
        self.assertIsNone(row.payload["selected"])
        self.assertEqual(row.payload["candidate_count"], 0)

    def test_shared_slot_decision_has_no_subject(self):
        w = World()
        shared = masters.create_slot(w.admin, w.slot.media_id, "일괄", 100, 200, 500, "초기", audience="shared", **SHARES)
        records.decide(shared.media_id, shared.slot_id, now=NOW)
        row = EventOutbox.objects.get()
        self.assertEqual((row.payload["audience"], row.payload["subject_id"]), ("shared", None))

    def test_failed_lookups_leave_no_event(self):
        w = World()
        with self.assertRaises(Exception):
            records.decide(uuid.uuid4(), w.slot.slot_id, subject_id=SUBJECT, now=NOW)  # 다른 매체의 슬롯 = 없는 것
        self.assertEqual(EventOutbox.objects.count(), 0)

    def test_outbox_adds_exactly_one_query_to_a_decision(self):
        w = World()
        with CaptureQueriesContext(connection) as q:
            decide(w)
        writes = [x["sql"] for x in q.captured_queries if x["sql"].lstrip().upper().startswith("INSERT")]
        self.assertEqual(sum("events_outbox" in s for s in writes), 1)
        self.assertEqual(sum("records_decision" in s for s in writes), 1)


class DecisionEventAtomicityTests(TransactionTestCase):
    def test_if_the_event_cannot_be_written_the_decision_is_not_stored(self):
        """저장은 됐는데 이벤트가 없는 상태가 생기지 않는다 — 트랜잭션 밖에서 불러도 결정과 이벤트는 함께 되돌려진다."""
        w = World()
        with mock.patch("records.services.events.record_decision", side_effect=RuntimeError("outbox 실패")):
            with self.assertRaises(RuntimeError):
                decide(w)
        self.assertEqual(Decision.objects.count(), 0)
        self.assertEqual(EventOutbox.objects.count(), 0)

    def test_if_the_decision_cannot_be_stored_there_is_no_event(self):
        w = World()
        with mock.patch("records.services.Decision.objects.create", side_effect=RuntimeError("저장 실패")):
            with self.assertRaises(RuntimeError):
                decide(w)
        self.assertEqual(EventOutbox.objects.count(), 0)


@tag("security")
class DecisionEventHttpTests(DecisionApiBase):
    def test_the_event_of_a_201_names_the_decision_in_the_response(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(str(EventOutbox.objects.get().aggregate_id), response.json()["decision_id"])

    def test_if_the_outbox_cannot_be_written_the_answer_is_503_and_nothing_is_saved(self):
        with mock.patch("records.services.events.record_decision", side_effect=OperationalError("disk full")):
            response = self.post()
        self.assertEqual(response.status_code, 503)  # 커밋 전의 실패: 결정과 이벤트를 함께 되돌린다
        self.assertNotIn("decision_id", response.json())
        self.assertEqual((Decision.objects.count(), EventOutbox.objects.count()), (0, 0))
        self.assertEqual(self.post().status_code, 201)
