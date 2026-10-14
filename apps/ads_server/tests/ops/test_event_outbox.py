"""이벤트 outbox (Step 4-1a): 같은 트랜잭션에서만 쓰고, 이벤트 ID 는 결정적이며, 같은 이벤트는 한 줄만 남는다."""
import datetime
import json
import uuid

from django.db import transaction
from django.test import TestCase, TransactionTestCase, tag

from events import api as events
from events import schemas
from events.models import EventOutbox
from events.outbox import enqueue
from tests.support.cases import Cases

NOW = datetime.datetime(2026, 10, 10, 3, 0, 0, 123456, tzinfo=datetime.timezone.utc)
DECISION = uuid.UUID("0199ee00-0000-7000-8000-000000000001")


def decision_fields(**override):
    fields = dict(
        decision_id=DECISION, media_id=uuid.uuid4(), slot_id=uuid.uuid4(), decided_at=NOW, audience="individual", subject_id="s1",
        selected={"campaign_id": uuid.uuid4(), "ad_group_id": uuid.uuid4(), "creative_id": uuid.uuid4(), "charge_shares": {"IMPRESSION": 98, "CLICK": 1, "CONVERSION": 1},
                  "bid_id": uuid.uuid4(), "bid_version": 1, "bid_policy_id": uuid.uuid4(), "policy_version": 2, "bid_amount": 300, "applied_amount": 300},
        selection_policy="weighted-by-bid/v1", candidate_count=3, rejected_counts={"budget": 1},
    )
    return {**fields, **override}


@tag("security")
class EventIdTests(Cases, TestCase):
    def case_id_is_deterministic_per_source_and_kind(self):
        a = schemas.event_id_of(schemas.DECISION, DECISION)
        self.assertEqual(a, schemas.event_id_of(schemas.DECISION, DECISION))
        self.assertNotEqual(a, schemas.event_id_of(schemas.REACTION, DECISION))  # 종류가 다르면 다른 이벤트
        self.assertNotEqual(a, schemas.event_id_of(schemas.DECISION, uuid.uuid4()))  # 원천이 다르면 다른 이벤트
        self.assertEqual(a.version, 5)

    def case_reaction_received_and_judged_events_of_one_inbox_row_differ(self):
        inbox = uuid.uuid4()
        self.assertNotEqual(schemas.event_id_of(schemas.REACTION_RECEIVED, inbox), schemas.event_id_of(schemas.REACTION, inbox))

    def test_event_id(self):
        self.run_cases()


@tag("security")
class EnqueueTests(Cases, TestCase):
    def case_writes_one_row_with_the_envelope(self):
        event_id = events.record_decision(now=NOW, **decision_fields())
        row = EventOutbox.objects.get()
        self.assertEqual((row.event_id, row.event_name, row.schema_version, row.aggregate_id, row.sent_at), (event_id, "ad.decision", 2, DECISION, None))
        self.assertEqual(schemas.SCHEMA_VERSIONS, {"ad.decision": 2, "ad.reaction_received": 1, "ad.reaction": 1, "ad.charge": 1})  # 종류별(6-10c): 결정만 2(단위 → `charge_shares`)
        self.assertEqual(row.created_at, NOW)  # produced_at = outbox 에 쓴 시각
        self.assertEqual(row.payload["decision_id"], str(DECISION))
        json.dumps(row.payload)  # JSON 으로 직렬화된다

    def case_the_same_event_twice_leaves_one_unchanged_row(self):
        events.record_decision(now=NOW, **decision_fields())
        first = EventOutbox.objects.get()
        events.record_decision(now=NOW + datetime.timedelta(hours=1), **decision_fields(candidate_count=99))  # 재처리: 같은 원천 → 같은 이벤트
        row = EventOutbox.objects.get()
        self.assertEqual((row.payload, row.created_at), (first.payload, first.created_at))  # 처음 것이 그대로다

    def case_sent_rows_stay_sent_when_re_enqueued(self):
        events.record_decision(now=NOW, **decision_fields())
        EventOutbox.objects.update(sent_at=NOW)
        events.record_decision(now=NOW, **decision_fields())
        self.assertIsNotNone(EventOutbox.objects.get().sent_at)  # 이미 보낸 이벤트를 다시 대기열로 되돌리지 않는다

    def case_payload_shapes(self):
        p = schemas.decision_payload(**decision_fields(audience="shared", subject_id=None, selected=None))
        self.assertEqual((p["selected"], p["subject_id"], p["decided_at"]), (None, None, "2026-10-10T03:00:00.123456+00:00"))
        self.assertNotIn("owner_id", json.dumps(schemas.decision_payload(**decision_fields())))  # 광고주 계정은 싣지 않는다
        basis = {"person": "p1", "audience": "individual", "v": 2}
        r = schemas.reaction_payload(
            inbox_id=uuid.uuid4(), reaction_id=uuid.uuid4(), media_id=uuid.uuid4(), decision_id=DECISION, type="CLICK", occurred_at=NOW, received_at=NOW,
            subject_id="reported", source="media", status="ACCEPTED", reason_code=None, applied_rule=None, basis=basis,
        )
        self.assertEqual((r["person_id"], r["audience"], r["subject_id"], r["basis"]), ("p1", "individual", "reported", basis))  # 사람·슬롯 성격은 basis 에서
        r = schemas.reaction_payload(
            inbox_id=uuid.uuid4(), reaction_id=uuid.uuid4(), media_id=uuid.uuid4(), decision_id=DECISION, type="CLICK", occurred_at=NOW, received_at=NOW,
            subject_id="reported", source="media", status="REJECTED", reason_code="unknown_decision", applied_rule="known-decision",
            basis={"person": None, "audience": None, "v": 2},
        )
        self.assertEqual((r["person_id"], r["audience"]), (None, None))  # null 규칙
        c = schemas.charge_payload(
            entry_id=uuid.uuid4(), campaign_id=uuid.uuid4(), charge_policy="share/v1", created_at=NOW, reaction_ref="m:r", decision_id=DECISION,
            requested_amount=30, charged_amount=20, shortfall=10, budget_day=datetime.date(2026, 10, 10),
        )
        self.assertEqual((c["budget_day"], c["requested_amount"], c["shortfall"]), ("2026-10-10", 30, 10))

    def case_received_event_carries_only_reported_facts(self):
        p = schemas.reaction_received_payload(
            inbox_id=uuid.uuid4(), reaction_id=uuid.uuid4(), media_id=uuid.uuid4(), decision_id=DECISION, type="IMPRESSION", occurred_at=NOW,
            received_at=NOW, subject_id=None, source="media", raw={"type": "IMPRESSION"},
        )
        self.assertNotIn("person_id", p)
        self.assertNotIn("audience", p)
        self.assertEqual(p["raw"], {"type": "IMPRESSION"})

    def test_enqueue(self):
        self.run_cases()


class OutsideTransactionTests(Cases, TransactionTestCase):
    def case_refuses_to_write_outside_a_transaction(self):
        with self.assertRaises(events.OutsideTransaction):
            events.record_decision(now=NOW, **decision_fields())
        self.assertEqual(EventOutbox.objects.count(), 0)

    def case_rolls_back_with_the_business_data(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                events.record_decision(now=NOW, **decision_fields())
                raise RuntimeError("업무 데이터 저장 실패")
        self.assertEqual(EventOutbox.objects.count(), 0)  # 저장은 안 됐는데 이벤트만 남지 않는다

    def case_commits_with_the_business_data(self):
        with transaction.atomic():
            events.record_decision(now=NOW, **decision_fields())
        self.assertEqual(EventOutbox.objects.count(), 1)

    def case_outbox_error_other_than_duplicate_is_not_swallowed(self):
        """길이 초과 같은 오류가 INSERT IGNORE 처럼 경고로 삼켜지지 않는다."""
        with self.assertRaises(Exception):
            with transaction.atomic():
                enqueue("x" * 100, uuid.uuid4(), DECISION, {})
        self.assertEqual(EventOutbox.objects.count(), 0)

    def test_outside_transaction(self):
        self.run_cases()
