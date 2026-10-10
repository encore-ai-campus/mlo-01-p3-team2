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
