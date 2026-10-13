"""청크로 나눠 읽는 조회가 청크 크기를 넘는 입력에서도 빠짐없이·중복 없이 답한다(경계를 넘는 마지막 덜 찬 청크 포함)."""
import datetime
import uuid
from unittest import mock

from django.test import TestCase

from billing import api as billing
from billing.models import EntryType, LedgerEntry, Wallet
from events import api as events
from events import relay, store
from events.models import EventOutbox
from records import api as records
from records.models import Decision
from tests.factories import NOW, SUBJECT, make_advertiser
from tests.mongo_support import MongoDatabaseMixin
from tests.test_event_relay import enqueue_decisions

T0 = datetime.datetime(2026, 10, 10, 3, 0, tzinfo=datetime.timezone.utc)


def sent_outbox_rows(n):
    rows = [EventOutbox(event_id=uuid.uuid4(), event_name="ad.decision", schema_version=1, aggregate_id=uuid.uuid4(), payload={}, created_at=T0, sent_at=T0)
            for _ in range(n)]
    EventOutbox.objects.bulk_create(rows)
    return rows


class RelayLookupChunkTests(MongoDatabaseMixin, TestCase):
    def setUp(self):
        super().setUp()
        store.ensure()

    def test_missing_event_ids_answers_across_chunks_in_input_order(self):
        in_outbox = enqueue_decisions(2)
        relay.relay_batch(now=T0)
        in_mongo_only = enqueue_decisions(2, start=T0 + datetime.timedelta(minutes=1))
        relay.relay_batch(now=T0)
        EventOutbox.objects.filter(aggregate_id__in=in_mongo_only).delete()  # 보존 정리로 outbox 에서 지워지고 MongoDB 에만 남은 이벤트
        event_ids = {d: events.event_id_for("ad.decision", d) for d in in_outbox + in_mongo_only}
        absent = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        wanted = [absent[0], event_ids[in_outbox[0]], event_ids[in_mongo_only[0]], absent[1], event_ids[in_outbox[1]], event_ids[in_mongo_only[1]], absent[2]]
        self.assertEqual(relay.missing_event_ids(wanted, chunk=2), absent)

    def test_sent_but_not_in_mongo_crosses_the_1000_row_batches(self):
        rows = sent_outbox_rows(1002)
        present = rows[1001]  # 마지막 덜 찬 묶음에 MongoDB 에 있는 행 하나
        store.collection().insert_one(relay.to_document(present))
        everything = relay.sent_but_not_in_mongo(limit=None)
        self.assertEqual((len(everything), len(set(everything))), (1001, 1001))
        self.assertEqual(set(everything), {r.event_id for r in rows} - {present.event_id})
        for limit in (5, 1000, 1001, 5000):
            self.assertEqual(relay.sent_but_not_in_mongo(limit=limit), everything[:limit], limit)
        self.assertEqual(relay.sent_but_not_in_mongo(), everything[:1000])  # 기본 상한


class LedgerLookupChunkTests(TestCase):
    def test_charge_lookups_cross_the_500_key_chunks(self):
        wallet = Wallet.objects.create(owner=make_advertiser(), balance=0)
        campaign_id = uuid.uuid4()
        entries = [LedgerEntry(wallet=wallet, seq=n, entry_type=EntryType.CHARGE, amount=-n, balance_after=0, campaign_id=campaign_id,
                               reaction_ref=f"ref-{n}", charge_policy="share/v1", created_at=T0) for n in range(1, 503)]
        LedgerEntry.objects.bulk_create(entries)
        refs = [f"ref-{n}" for n in range(1, 503)] + ["ref-unknown"]
        self.assertEqual(billing.charged_amounts(refs), {f"ref-{n}": n for n in range(1, 503)})
        found = billing.charge_entries([e.entry_id for e in entries] + [uuid.uuid4()])
        self.assertEqual(len(found), 502)
        self.assertEqual({(f.entry_id, f.charged, f.reaction_ref) for f in found}, {(e.entry_id, -e.amount, e.reaction_ref) for e in entries})


class EventGapsChunkTests(MongoDatabaseMixin, TestCase):
    def test_event_gaps_reports_every_row_across_the_2000_row_chunks(self):
        decisions = [Decision(media_id=uuid.uuid4(), slot_id=uuid.uuid4(), subject_id=SUBJECT, audience="individual", selection_policy="highest-bid/v1",
                              trace={}, candidate_count=0, rejected_counts={}, decided_at=T0) for _ in range(2003)]
        Decision.objects.bulk_create(decisions)
        stats = {}
        gaps = list(records.event_gaps(stats))
        self.assertEqual(stats, {"decision": 2003, "reaction": 0, "ledger_charge": 0})
        self.assertEqual(len(gaps), 2003)
        self.assertEqual({g["source_id"] for g in gaps}, {str(d.decision_id) for d in decisions})
        self.assertEqual({g["event_id"] for g in gaps}, {str(events.event_id_for("ad.decision", d.decision_id)) for d in decisions})


class ChunkSizeContractTests(TestCase):
    """청크 크기가 1 미만이면 '없다'·'할 일 없음'으로 답하지 않고 무엇이 잘못됐는지 알리며 실패한다(계획 4-4a, R6)."""

    def test_missing_event_ids_refuses_a_chunk_below_one(self):
        for chunk in (0, -1):
            with self.assertRaisesRegex(ValueError, "chunk"):
                relay.missing_event_ids([uuid.uuid4()], chunk=chunk)
            with self.assertRaisesRegex(ValueError, "chunk"):
                relay.missing_event_ids([], chunk=chunk)  # 입력이 비어도 같은 계약

    def test_backfill_refuses_a_chunk_below_one_before_reading_the_input(self):
        for chunk in (0, -1):
            with self.assertRaisesRegex(ValueError, "chunk"):
                records.backfill_events("/nonexistent/event_gaps.manifest.json", chunk=chunk)


class MissingEventIdsTests(TestCase):
    def test_ids_all_found_in_the_outbox_do_not_touch_mongodb(self):
        rows = EventOutbox.objects.bulk_create([
            EventOutbox(event_id=uuid.uuid4(), event_name="ad.decision", schema_version=1, aggregate_id=uuid.uuid4(), payload={}, created_at=NOW)
            for _ in range(3)
        ])
        with mock.patch("events.store.collection", side_effect=AssertionError("MongoDB 에 묻지 않아야 한다")):
            self.assertEqual(events.missing_event_ids([r.event_id for r in rows], chunk=2), [])
