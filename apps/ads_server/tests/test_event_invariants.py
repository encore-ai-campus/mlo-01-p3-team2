"""부하·장애 시험의 **이벤트 검사기 자체**(`scripts/load_test.py` 의 `verify_events`)를 시험한다: 일대일이면 통과시키고, 빠진 이벤트·남는 이벤트·미전송·MongoDB 불일치를 잡는다."""
import importlib.util
import uuid
from pathlib import Path
from random import Random

from django.test import TestCase, tag

from events import schemas, store
from events.models import EventOutbox
from events.relay import relay_batch
from records import api as records
from tests.factories import NOW, SUBJECT, World
from tests.mongo_support import MongoDatabaseMixin

_spec = importlib.util.spec_from_file_location("load_test_events", Path(__file__).resolve().parent.parent / "scripts" / "load_test.py")
load_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load_test)


@tag("security")
class EventInvariantTests(MongoDatabaseMixin, TestCase):
    def setUp(self):
        super().setUp()
        store.ensure()
        w = World()
        decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW)  # 결정 1 + 접수 1 + 판정 1 + 과금 1 = 이벤트 4건

    def test_one_to_one_passes_before_and_after_relaying(self):
        self.assertEqual(EventOutbox.objects.count(), 4)
        self.assertEqual(load_test.verify_events(), [])
        self.assertIn("MongoDB 로 보내지 않은 이벤트 4건", " ".join(load_test.verify_events(relayed=True)))  # 아직 안 보냈다
        relay_batch()
        self.assertEqual(load_test.verify_events(relayed=True), [])

    def test_a_missing_event_is_caught_for_each_kind(self):
        for name in (schemas.DECISION, schemas.REACTION_RECEIVED, schemas.REACTION, schemas.CHARGE):
            row = EventOutbox.objects.get(event_name=name)
            kept = dict(event_id=row.event_id, event_name=row.event_name, schema_version=1, aggregate_id=row.aggregate_id, payload=row.payload, created_at=row.created_at)
            row.delete()  # (삭제하면 인스턴스의 pk 가 지워진다 — 복원용 값은 미리 챙겨 둔다)
            self.assertEqual(len(load_test.verify_events()), 1, name)
            self.assertIn("이벤트가 없는 원본 행 1건", load_test.verify_events()[0])
            EventOutbox.objects.create(**kept)

    def test_an_event_without_a_source_row_is_caught(self):
        EventOutbox.objects.create(event_id=uuid.uuid4(), event_name="ad.decision", schema_version=1, aggregate_id=uuid.uuid4(), payload={})
        self.assertIn("원본 행이 없는 이벤트 1건", " ".join(load_test.verify_events()))

    def test_mongodb_must_match_the_outbox(self):
        relay_batch()
        gone = store.collection().find_one({"event_name": "ad.charge"})
        store.collection().delete_one({"_id": gone["_id"]})
        self.assertIn("없음 1건", " ".join(load_test.verify_events(relayed=True)))
        store.collection().insert_one({**gone})
        store.collection().insert_one({"_id": uuid.uuid4(), "event_name": "ad.decision", "schema_version": 1, "produced_at": NOW, "payload": {}})
        self.assertIn("더 있음 1건", " ".join(load_test.verify_events(relayed=True)))


@tag("security")
class EventContentTests(MongoDatabaseMixin, TestCase):
    """검토: 이벤트의 존재·개수만이 아니라 **내용**이 원본과 맞고 MongoDB 에 같은 내용이 전달됐는지까지 증명해야 한다."""

    def setUp(self):
        super().setUp()
        store.ensure()
        w = World()
        decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW)
        relay_batch()

    def problems(self):
        return load_test.verify_events(relayed=True)

    def tamper_outbox(self, name, change):
        row = EventOutbox.objects.get(event_name=name)
        payload = row.payload
        change(payload)
        EventOutbox.objects.filter(pk=row.pk).update(payload=payload)
        return row

    def tamper_mongo(self, event_id, change):
        doc = store.collection().find_one({"_id": event_id})
        change(doc["payload"])
        store.collection().replace_one({"_id": event_id}, doc)

    def test_untouched_data_passes(self):
        self.assertEqual(self.problems(), [])

    def test_only_mongodb_changed_is_caught_by_the_outbox_comparison(self):
        """검토 재현 1: 원장·outbox 는 30 인데 MongoDB 의 charged_amount 만 999."""
        row = EventOutbox.objects.get(event_name="ad.charge")
        self.tamper_mongo(row.event_id, lambda p: p.update(charged_amount=999))
        problems = " ".join(self.problems())
        self.assertIn("MongoDB 문서가 outbox 와 내용이 다른 이벤트 1건", problems)
        self.assertIn("charged_amount", problems)

    def test_outbox_and_mongodb_changed_to_the_same_wrong_value_is_caught_by_the_source_comparison(self):
        """검토 재현 2: 원장은 30 인데 outbox 와 MongoDB 의 과금액을 둘 다 999 로 — 두 사본이 서로 같아도 원본과 다르다."""
        row = self.tamper_outbox("ad.charge", lambda p: p.update(charged_amount=999))
        self.tamper_mongo(row.event_id, lambda p: p.update(charged_amount=999))
        problems = " ".join(self.problems())
        self.assertIn("원본 행과 내용이 다른 ad.charge 이벤트 1건", problems)
        self.assertNotIn("MongoDB 문서가 outbox 와", problems)  # outbox ↔ MongoDB 는 서로 같다

    def test_a_wrong_value_in_each_event_kind_is_caught(self):
        for name, change in (
            ("ad.decision", lambda p: p.update(candidate_count=99)),
            ("ad.reaction_received", lambda p: p["raw"].update(type="CLICK")),
            ("ad.reaction", lambda p: p.update(status="REJECTED")),
            ("ad.reaction", lambda p: p["basis"].update(person="누군가")),
            ("ad.charge", lambda p: p.update(shortfall=5)),
            ("ad.charge", lambda p: p.update(budget_day="2020-01-01")),
        ):
            with self.subTest(name=name):
                row = EventOutbox.objects.get(event_name=name)
                original = row.payload
                import copy

                self.tamper_outbox(name, change)
                self.assertIn(f"원본 행과 내용이 다른 {name} 이벤트 1건", " ".join(load_test.verify_events()), name)
                EventOutbox.objects.filter(pk=row.pk).update(payload=copy.deepcopy(original))
                self.assertEqual(load_test.verify_events(), [])

    def test_a_json_type_difference_is_caught(self):
        self.tamper_outbox("ad.decision", lambda p: p["selected"].update(bid_version=True if p["selected"]["bid_version"] == 1 else 1))
        self.assertIn("원본 행과 내용이 다른 ad.decision", " ".join(load_test.verify_events()))

    def test_the_wrong_message_key_is_caught(self):
        EventOutbox.objects.filter(event_name="ad.charge").update(aggregate_id=uuid.uuid4())
        self.assertIn("원본 행과 내용이 다른 ad.charge", " ".join(load_test.verify_events()))

    def test_a_changed_envelope_in_mongodb_is_caught(self):
        row = EventOutbox.objects.get(event_name="ad.decision")
        store.collection().update_one({"_id": row.event_id}, {"$set": {"schema_version": 2}})
        self.assertIn("MongoDB 문서가 outbox 와 내용이 다른 이벤트 1건", " ".join(self.problems()))
