"""Step 4-1e: 중계 — outbox 의 미전송 이벤트를 MongoDB `ad_events` 로 멱등 저장하고 `sent_at` 을 표시한다."""
import datetime
import io
import signal
import threading
import uuid
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings, tag
from django.utils import timezone
from pymongo.errors import ServerSelectionTimeoutError

from events import api as events
from events import mongo, relay, store
from events.models import EventOutbox
from events.relay import EventConflict, relay_batch
from records import api as records
from tests.factories import NOW, SUBJECT, World
from tests.mongo_support import MongoDatabaseMixin
from tests.test_event_outbox import decision_fields
from tests.test_receipt_ordering import WAIT, Worker

T0 = datetime.datetime(2026, 10, 10, 3, 0, 0, 123456, tzinfo=datetime.timezone.utc)


def enqueue_decisions(n, start=T0):
    ids = []
    for i in range(n):
        decision_id = uuid.uuid4()
        with transaction.atomic():  # TransactionTestCase 는 자동 트랜잭션이 없다 — 운영처럼 업무 데이터의 트랜잭션 안에서 쓴다
            events.record_decision(now=start + timedelta(seconds=i), **decision_fields(decision_id=decision_id))
        ids.append(decision_id)
    return ids


def stored():
    return {d["_id"]: d for d in store.collection().find()}


class RelayBase(MongoDatabaseMixin, TestCase):
    def setUp(self):
        super().setUp()
        store.ensure()  # 운영과 같은 봉투 검증이 걸린 컬렉션


@tag("security")
class RelayTests(RelayBase):
    def test_moves_events_faithfully_and_marks_them_sent(self):
        ids = enqueue_decisions(3)
        result = relay_batch(now=T0)
        self.assertEqual((result.sent, result.duplicate), (3, 0))
        docs = stored()
        self.assertEqual(len(docs), 3)
        for row in EventOutbox.objects.all():
            doc = docs[row.event_id]  # _id = event_id (UUID)
            self.assertEqual((doc["event_name"], doc["schema_version"], doc["payload"]), (row.event_name, row.schema_version, row.payload))
            self.assertEqual(doc["produced_at"], row.created_at.replace(microsecond=row.created_at.microsecond // 1000 * 1000))  # 밀리초까지
            self.assertEqual(row.sent_at, T0)
        self.assertEqual(relay_batch(), relay.RelayResult())  # 더 없다

    def test_resending_the_same_events_passes_as_duplicates(self):
        """보낸 뒤 표시 전에 죽은 경우: 다시 보내면 같은 내용의 중복으로 통과하고 문서는 늘지 않는다."""
        enqueue_decisions(3)
        relay_batch()
        EventOutbox.objects.update(sent_at=None)
        result = relay_batch(now=T0)
        self.assertEqual((result.sent, result.duplicate), (0, 3))
        self.assertEqual(len(stored()), 3)
        self.assertEqual(EventOutbox.objects.filter(sent_at__isnull=True).count(), 0)

    def test_a_failure_after_the_write_leaves_the_rows_unsent_and_the_retry_passes(self):
        enqueue_decisions(2)
        real_write = relay._write

        def write_then_die(documents):
            real_write(documents)
            raise RuntimeError("저장 직후 죽음")

        with mock.patch("events.relay._write", write_then_die):
            with self.assertRaises(RuntimeError):
                relay_batch()
        self.assertEqual(len(stored()), 2)  # MongoDB 에는 들어갔지만
        self.assertEqual(EventOutbox.objects.filter(sent_at__isnull=True).count(), 2)  # 표시는 되돌려졌다
        result = relay_batch()
        self.assertEqual((result.sent, result.duplicate), (0, 2))

    def test_a_different_document_under_the_same_id_stops_the_relay_without_overwriting(self):
        ids = enqueue_decisions(3)
        bad = EventOutbox.objects.get(aggregate_id=ids[1])
        store.collection().insert_one({"_id": bad.event_id, "event_name": bad.event_name, "schema_version": 1, "produced_at": bad.created_at, "payload": {"decision_id": "다른 내용"}})
        with self.assertRaises(EventConflict) as raised:
            relay_batch(now=T0)
        self.assertEqual(raised.exception.event_ids, [bad.event_id])
        self.assertEqual(store.collection().find_one({"_id": bad.event_id})["payload"], {"decision_id": "다른 내용"})  # 덮어쓰지 않았다
        sent = set(EventOutbox.objects.filter(sent_at__isnull=False).values_list("aggregate_id", flat=True))
        self.assertEqual(sent, {ids[0], ids[2]})  # 충돌하지 않은 이벤트는 표시돼 있다
        self.assertIsNone(EventOutbox.objects.get(pk=bad.pk).sent_at)  # 충돌한 것은 미전송으로 남아 사람이 본다
        with self.assertRaises(EventConflict):
            relay_batch()  # 다시 해도 계속 멈춘다(건너뛰지 않는다)

    def test_a_different_json_type_is_a_conflict_not_a_duplicate(self):
        """검토: Python 에서는 1 == True 이다 — 입찰 버전 1 과 true 를 같은 내용으로 보고 잘못된 문서를 확정했다. JSON 타입까지 같아야 같은 내용이다."""
        for label, mutate in (
            ("정수 → 불리언", lambda p: p["selected"].update(bid_version=True)),
            ("0 → false", lambda p: p["rejected_counts"].update(budget=False)),
            ("정수 → 실수", lambda p: p["selected"].update(applied_amount=float(p["selected"]["applied_amount"]))),
            ("정수 → 문자열", lambda p: p["selected"].update(bid_amount=str(p["selected"]["bid_amount"]))),
            ("중첩 목록 안", lambda p: p.update(extra=[1, {"k": True}])),
        ):
            with self.subTest(label):
                store.collection().delete_many({})
                EventOutbox.objects.all().delete()
                EventOutbox.objects.update(sent_at=None)
                payload_fields = decision_fields(rejected_counts={"budget": 0})
                decision_id = payload_fields["decision_id"]
                events.record_decision(now=T0, **payload_fields)
                row = EventOutbox.objects.get()
                if label == "중첩 목록 안":
                    row.payload["extra"] = [1, {"k": 1}]
                    EventOutbox.objects.filter(pk=row.pk).update(payload=row.payload)
                    row.refresh_from_db()
                wrong = relay.to_document(row)
                mutate(wrong["payload"])
                store.collection().insert_one(wrong)  # 같은 ID 에 타입만 다른 문서가 이미 있다
                with self.assertRaises(EventConflict, msg=label) as raised:
                    relay_batch(now=T0)
                self.assertEqual(raised.exception.event_ids, [row.event_id])
                self.assertIsNone(EventOutbox.objects.get(pk=row.pk).sent_at)  # 확정하지 않는다
                self.assertEqual(decision_id, row.aggregate_id)

    def test_the_same_content_with_different_key_order_is_a_duplicate(self):
        (decision_id,) = enqueue_decisions(1)
        row = EventOutbox.objects.get()
        doc = relay.to_document(row)
        doc["payload"] = dict(reversed(list(doc["payload"].items())))  # 키 순서만 다르다
        store.collection().insert_one(doc)
        result = relay_batch(now=T0)
        self.assertEqual((result.sent, result.duplicate), (0, 1))

    def test_batches_are_oldest_first(self):
        ids = enqueue_decisions(5)
        relay_batch(limit=2, now=T0)
        self.assertEqual(set(EventOutbox.objects.filter(sent_at__isnull=False).values_list("aggregate_id", flat=True)), set(ids[:2]))
        relay_batch(limit=2, now=T0)
        relay_batch(limit=2, now=T0)
        self.assertEqual(EventOutbox.objects.filter(sent_at__isnull=True).count(), 0)
        self.assertEqual(len(stored()), 5)

    def test_non_duplicate_write_errors_are_not_hidden(self):
        """봉투 검증을 통과하지 못하는 문서는 중복이 아니다 — 숨기지 않고 실패한다."""
        events_row = enqueue_decisions(1)
        EventOutbox.objects.update(schema_version=1)
        with mock.patch("events.relay.to_document", lambda row: {"_id": row.event_id, "event_name": "x"}):  # 봉투 필드가 빠진 문서
            with self.assertRaises(Exception) as raised:
                relay_batch()
        self.assertNotIsInstance(raised.exception, EventConflict)
        self.assertEqual(EventOutbox.objects.filter(sent_at__isnull=True).count(), 1)
        self.assertEqual(len(events_row), 1)

    def test_when_mongodb_is_down_the_rows_stay_unsent(self):
        enqueue_decisions(2)
        with override_settings(EVENT_STORE={**mongo.config(), "HOSTS": ["127.0.0.1:1"], "REPLICA_SET": None}):
            mongo.close()
            with self.assertRaises(Exception):
                relay_batch()
            mongo.close()
        self.assertEqual(EventOutbox.objects.filter(sent_at__isnull=True).count(), 2)
        self.assertEqual(relay_batch().sent, 2)  # 복구되면 이어서 보낸다

    def test_status_reports_the_backlog(self):
        enqueue_decisions(3, start=T0)
        status = relay.outbox_status(now=T0 + timedelta(seconds=100))
        self.assertEqual((status["pending"], status["oldest_age_seconds"]), (3, 100.0))
        relay_batch()
        self.assertEqual(relay.outbox_status(), {"pending": 0, "oldest_age_seconds": None})

    def test_a_real_decision_event_arrives_as_the_same_json(self):
        w = World()
        view = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW)
        relay_batch()
        (doc,) = [d for d in stored().values() if d["event_name"] == "ad.decision"]
        self.assertEqual(doc["payload"], EventOutbox.objects.get(aggregate_id=view.decision_id).payload)
        self.assertEqual(doc["payload"]["decision_id"], str(view.decision_id))


@tag("security")
class RelayCommandTests(RelayBase):
    def run_command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        try:
            call_command("relay_events", *args, stdout=out, stderr=err)
            return True, out.getvalue() + err.getvalue()
        except CommandError as error:
            return False, out.getvalue() + str(error)

    def test_once_drains_the_backlog_and_reports(self):
        enqueue_decisions(5)
        ok, text = self.run_command("--once", "--batch", "2")
        self.assertTrue(ok, text)
        self.assertIn("'sent': 5", text)
        self.assertEqual(len(stored()), 5)

    def test_status_only_reads(self):
        enqueue_decisions(2)
        ok, text = self.run_command("--status")
        self.assertTrue(ok)
        self.assertIn("'pending': 2", text)
        self.assertEqual(len(stored()), 0)

    def test_a_conflict_fails_loudly(self):
        (decision_id,) = enqueue_decisions(1)
        row = EventOutbox.objects.get()
        store.collection().insert_one({"_id": row.event_id, "event_name": row.event_name, "schema_version": 1, "produced_at": row.created_at, "payload": {}})
        ok, text = self.run_command("--once")
        self.assertFalse(ok)
        self.assertIn("충돌", text)

    def test_once_fails_when_mongodb_is_unreachable(self):
        enqueue_decisions(1)
        with override_settings(EVENT_STORE={**mongo.config(), "HOSTS": ["127.0.0.1:1"], "REPLICA_SET": None}):
            mongo.close()
            ok, text = self.run_command("--once")
            mongo.close()
        self.assertFalse(ok)
        self.assertIn("중계 실패", text)
        self.assertEqual(EventOutbox.objects.filter(sent_at__isnull=True).count(), 1)

    def test_bad_options(self):
        self.assertFalse(self.run_command("--batch", "0")[0])
        self.assertFalse(self.run_command("--interval", "0")[0])
        self.assertFalse(self.run_command("--interval", "nan")[0])


class StandingRelayTests(RelayBase):
    """상시 중계(`--once` 없이)의 동작 중 다른 시험이 덮지 않는 것(계획 4-4e): 실패하면 점점 길게 쉬고(최대 30초) 성공하면 처음으로, 충돌이면 쉬지 않고 멈춤, 신호 처리기 복원."""

    def run_standing(self, relay, stop_after_sleeps, interval="1"):
        handlers, sleeps, err = {}, [], io.StringIO()

        def capture(signum, handler):
            handlers[signum] = handler
            return signal.SIG_DFL

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == stop_after_sleeps:
                handlers[signal.SIGTERM](signal.SIGTERM, None)

        with mock.patch("events.management.commands.relay_events.relay_batch", relay), \
                mock.patch("events.management.commands.relay_events.signal.signal", capture), \
                mock.patch("events.management.commands.relay_events.time.sleep", fake_sleep):
            call_command("relay_events", "--interval", interval, stdout=io.StringIO(), stderr=err)
        return sleeps, err.getvalue()

    def test_failures_back_off_up_to_30_seconds_and_a_success_starts_over(self):
        calls = []

        def flaky(**kwargs):
            calls.append(1)
            if len(calls) <= 6 or len(calls) == 8:  # 여섯 번 실패 → 성공 → 다시 실패
                raise ServerSelectionTimeoutError("down")
            return relay_batch(**kwargs)

        sleeps, err = self.run_standing(flaky, stop_after_sleeps=8)
        self.assertEqual(sleeps, [2, 4, 8, 16, 30, 30, 1.0, 2])  # interval × 2^min(실패 횟수, 5), 최대 30초 / 성공하면 주기대로 쉬고 실패 횟수는 처음부터
        self.assertEqual(err.count("이번 주기를 건너뛴다"), 7)
        self.assertIn("(6번째, 30초 뒤 다시)", err)
        self.assertIn("(1번째, 2초 뒤 다시)", err)

    def test_the_interval_scales_the_back_off(self):
        sleeps, _ = self.run_standing(mock.Mock(side_effect=ServerSelectionTimeoutError("down")), stop_after_sleeps=3, interval="0.25")
        self.assertEqual(sleeps, [0.5, 1.0, 2.0])

    def test_a_conflict_stops_the_standing_relay_without_retrying(self):
        relay = mock.Mock(side_effect=EventConflict([uuid.uuid4()]))
        with self.assertRaisesRegex(CommandError, "충돌로 중계를 멈춥니다"):
            self.run_standing(relay, stop_after_sleeps=99)
        self.assertEqual(relay.call_count, 1)  # 다시 시도하지 않는다

    def test_the_previous_signal_handler_is_restored(self):
        before = signal.getsignal(signal.SIGTERM)
        call_command("relay_events", "--once", stdout=io.StringIO())
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)
        with mock.patch("events.management.commands.relay_events.relay_batch", side_effect=EventConflict([uuid.uuid4()])), \
                mock.patch("events.management.commands.relay_events.time.sleep", side_effect=AssertionError("충돌이면 쉬지 않고 멈춰야 한다")), \
                self.assertRaises(CommandError):  # (충돌 처리가 깨지면 이 시험이 매달리지 않고 실패한다)
            call_command("relay_events", stdout=io.StringIO())
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)

@tag("security")
class PurgeTests(TestCase):
    def test_only_old_sent_rows_are_deleted(self):
        now = timezone.now()
        events.record_decision(now=now, **decision_fields(decision_id=uuid.uuid4()))  # 미전송(오래됐어도 지우지 않는다)
        old_unsent = EventOutbox.objects.get()
        EventOutbox.objects.filter(pk=old_unsent.pk).update(created_at=now - timedelta(days=30))
        for sent_days_ago in (30, 1):
            events.record_decision(now=now, **decision_fields(decision_id=uuid.uuid4()))
        a, b = EventOutbox.objects.exclude(pk=old_unsent.pk).order_by("event_id")
        EventOutbox.objects.filter(pk=a.pk).update(sent_at=now - timedelta(days=30))
        EventOutbox.objects.filter(pk=b.pk).update(sent_at=now - timedelta(days=1))
        out = io.StringIO()
        call_command("purge_sent_events", "--days", "7", stdout=out)
        self.assertIn("deleted: 1", out.getvalue())
        self.assertEqual(set(EventOutbox.objects.values_list("pk", flat=True)), {old_unsent.pk, b.pk})
        with self.assertRaises(CommandError):
            call_command("purge_sent_events", "--days", "-1")
        call_command("purge_sent_events", stdout=io.StringIO())  # 기본은 설정값(7일)


class RelayConcurrencyTests(MongoDatabaseMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        store.ensure()

    def test_two_relays_take_different_rows_and_never_send_the_same_event_twice(self):
        ids = enqueue_decisions(6)
        entered, release = threading.Event(), threading.Event()
        real_write = relay._write

        def slow_write(documents):
            if threading.current_thread().name == "slow-relay":  # 패치는 프로세스 전체에 걸리므로 첫 중계 스레드만 멈춘다
                entered.set()
                assert release.wait(WAIT)
            return real_write(documents)

        first = Worker(lambda: _with_slow_write(slow_write))
        first.name = "slow-relay"
        first.start()
        self.assertTrue(entered.wait(WAIT))  # 첫 중계가 가장 오래된 3건을 잡고 MongoDB 쓰기 직전에 멈춰 있다
        second = relay_batch(limit=10)  # 둘째는 잠긴 3건을 건너뛰고 나머지 3건을 옮긴다
        self.assertEqual((second.sent, second.duplicate), (3, 0))
        release.set()
        first.join(WAIT)
        self.assertEqual(first.errors, [])
        self.assertEqual((first.result.sent, first.result.duplicate), (3, 0))  # 같은 이벤트를 두 번 보내지 않았다
        self.assertEqual(len(stored()), 6)
        self.assertEqual(EventOutbox.objects.filter(sent_at__isnull=True).count(), 0)
        self.assertEqual(len(ids), 6)


def _with_slow_write(slow_write):
    with mock.patch("events.relay._write", slow_write):
        return relay_batch(limit=3)
