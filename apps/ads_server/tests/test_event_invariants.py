"""부하·장애 시험의 **이벤트 검사기 자체**(`scripts/load_test.py` 의 `verify_events`)를 시험한다: 일대일이면 통과시키고, 빠진 이벤트·남는 이벤트·미전송·MongoDB 불일치를 잡는다."""
import datetime
import importlib.util
import uuid
from pathlib import Path
from random import Random

from django.test import TestCase, TransactionTestCase, tag

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
            kept = dict(event_id=row.event_id, event_name=row.event_name, schema_version=row.schema_version, aggregate_id=row.aggregate_id, payload=row.payload, created_at=row.created_at)
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
        records.process_reaction(view.inbox_id, now=NOW + datetime.timedelta(seconds=7))  # 처리 시각이 수신 시각과 다르다 — 이벤트 생성 시각의 기준을 구분해 본다
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
        store.collection().update_one({"_id": row.event_id}, {"$set": {"schema_version": 9}})
        self.assertIn("MongoDB 문서가 outbox 와 내용이 다른 이벤트 1건", " ".join(self.problems()))

    def test_envelope_changed_identically_in_outbox_and_mongodb_is_caught(self):
        """재검토 재현: outbox 와 MongoDB 의 봉투를 같은 잘못된 값으로 바꾸면 두 사본의 비교는 통과한다 — 현재 계약·원본 시각과 맞는지는 원본 대조가 본다."""
        from events import schemas

        for name in ("ad.decision", "ad.reaction_received", "ad.reaction", "ad.charge"):
            with self.subTest(name=name, field="schema_version"):
                row = EventOutbox.objects.get(event_name=name)
                EventOutbox.objects.filter(pk=row.pk).update(schema_version=9999)
                store.collection().update_one({"_id": row.event_id}, {"$set": {"schema_version": 9999}})
                problems = " ".join(self.problems())
                self.assertIn(f"원본 행과 내용이 다른 {name} 이벤트 1건", problems)
                self.assertIn("schema_version", problems)
                self.assertNotIn("MongoDB 문서가 outbox 와", problems)  # 두 사본은 서로 같다
                EventOutbox.objects.filter(pk=row.pk).update(schema_version=schemas.SCHEMA_VERSIONS[name])
                store.collection().update_one({"_id": row.event_id}, {"$set": {"schema_version": schemas.SCHEMA_VERSIONS[name]}})
                self.assertEqual(self.problems(), [])
            with self.subTest(name=name, field="produced_at"):
                row = EventOutbox.objects.get(event_name=name)
                later = row.created_at + datetime.timedelta(days=1)
                EventOutbox.objects.filter(pk=row.pk).update(created_at=later)
                store.collection().update_one({"_id": row.event_id}, {"$set": {"produced_at": later.replace(microsecond=later.microsecond // 1000 * 1000)}})
                problems = " ".join(self.problems())
                self.assertIn(f"원본 행과 내용이 다른 {name} 이벤트 1건", problems)
                self.assertIn("produced_at", problems)
                self.assertNotIn("MongoDB 문서가 outbox 와", problems)
                EventOutbox.objects.filter(pk=row.pk).update(created_at=row.created_at)
                store.collection().update_one({"_id": row.event_id}, {"$set": {"produced_at": row.created_at.replace(microsecond=row.created_at.microsecond // 1000 * 1000)}})
                self.assertEqual(self.problems(), [])

    def test_the_envelope_time_is_the_origin_time_per_kind(self):
        """생성 시각의 기준: 결정 = 결정 시각, 접수 = 수신 시각, 판정·과금 = 처리 시각."""
        from billing.models import LedgerEntry
        from records.models import Decision, Reaction

        decision, reaction = Decision.objects.get(), Reaction.objects.get()
        created = {e.event_name: e.created_at for e in EventOutbox.objects.all()}
        self.assertEqual(created["ad.decision"], decision.decided_at)
        self.assertEqual(created["ad.reaction_received"], reaction.received_at)
        self.assertEqual(created["ad.reaction"], reaction.processed_at)
        self.assertEqual(created["ad.charge"], reaction.processed_at)
        self.assertNotEqual(reaction.processed_at, reaction.received_at)
        self.assertEqual(LedgerEntry.objects.get(entry_type="CHARGE").created_at, reaction.received_at)  # (원장 시각은 수신 시각 — 과금 이벤트의 기준과 다르다)


@tag("security")
class LagSamplerTests(TransactionTestCase):
    """4-3d: 이벤트가 생성 시각 뒤 얼마 만에 보이는지 재는 표본기가 정확히 재고, 여유를 넘은 이벤트와 못 본 이벤트를 센다."""

    def add(self, age_seconds):
        import datetime as dt

        from django.db import transaction
        from django.utils import timezone

        with transaction.atomic():
            row = EventOutbox.objects.create(event_id=uuid.uuid4(), event_name="ad.decision", schema_version=1, aggregate_id=uuid.uuid4(), payload={},
                                             created_at=timezone.now() - dt.timedelta(seconds=age_seconds))
        return row

    def sample(self, ages, grace=120, horizon=150.0):
        import time

        sampler = load_test.LagSampler(interval=0.05, horizon=horizon)
        sampler.start()
        time.sleep(0.2)
        for age in ages:
            self.add(age)
        time.sleep(0.4)
        sampler.stop()
        import datetime as dt

        from django.utils import timezone

        sampler.started = timezone.now() - dt.timedelta(seconds=1000)  # (시험이 일부러 과거의 생성 시각으로 만든 이벤트도 보고 범위에 넣는다)
        return sampler.report(grace)

    def test_measures_the_gap_between_production_and_visibility(self):
        report = self.sample([3.0, 10.0])
        self.assertEqual((report["events"], report["late"], report["unobserved"]), (2, 0, 0))
        self.assertGreaterEqual(report["max_lag_s"], 10.0)
        self.assertLess(report["max_lag_s"], 11.5)

    def test_events_that_became_visible_after_the_grace_are_counted_late(self):
        report = self.sample([30.0, 3.0], grace=20)
        self.assertEqual((report["late"], report["unobserved"]), (1, 0))

    def test_an_event_older_than_the_scan_horizon_is_counted_as_unobserved_not_hidden(self):
        report = self.sample([3.0, 400.0], horizon=60.0)
        self.assertEqual((report["events"], report["unobserved"]), (2, 1))  # 훑는 범위보다 늦게 나타난 이벤트도 놓치지 않고 센다
