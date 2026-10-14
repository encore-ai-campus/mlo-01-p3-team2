"""MongoDB 오류 문구(계획 4-4h, R4): 오류를 알리는 아홉 곳이 같은 형식 `<오류 종류>: <메시지 앞 200자>` 를 쓴다. 명령은 여전히 비정상 종료하고 오류 종류 이름을 남긴다."""
import io
import os
import signal
import tempfile
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from events import api as events
from events import store

from tests.support.mongo_support import EventStoreTestCase, MongoDatabaseMixin

LONG = "x" * 500
EXPECTED = f"ServerSelectionTimeoutError: {'x' * 200}"


def down():
    return ServerSelectionTimeoutError(LONG)


class HelperTests(SimpleTestCase):
    def test_type_name_then_the_first_200_characters(self):
        self.assertEqual(events.mongo_error_text(down()), EXPECTED)
        self.assertEqual(events.mongo_error_text(OperationFailure("짧다")), "OperationFailure: 짧다")
        self.assertEqual(events.mongo_error_text(events.NotConfigured("설정 없음")), "NotConfigured: 설정 없음")


class CommandTests(MongoDatabaseMixin, TransactionTestCase):
    def run_command(self, name, *args):
        out, err = io.StringIO(), io.StringIO()
        with self.assertRaises(CommandError) as failed:
            call_command(name, *args, stdout=out, stderr=err)
        return str(failed.exception)

    def assertFormatted(self, text):
        self.assertIn(EXPECTED, text)
        self.assertNotIn("x" * 201, text)

    def out_dir(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name

    def test_backfill_events(self):
        with mock.patch("records.management.commands.backfill_events.backfill_events", side_effect=down()):
            self.assertFormatted(self.run_command("backfill_events", "--input", "unused", "--out", self.out_dir()))

    def test_export_integrity(self):
        with mock.patch.object(events, "sent_but_not_in_mongo", side_effect=down()):
            self.assertFormatted(self.run_command("export_integrity", "--out", self.out_dir()))

    def test_export_hop_manifests(self):
        with mock.patch.object(events, "mongo_streams", side_effect=down()):
            self.assertFormatted(self.run_command("export_hop_manifests", "--out", self.out_dir()))

    def test_relay_events_once(self):
        with mock.patch("events.management.commands.relay_events.relay_batch", side_effect=down()):
            self.assertFormatted(self.run_command("relay_events", "--once"))

    def test_relay_events_standing_loop_reports_and_keeps_going(self):
        err = io.StringIO()
        with mock.patch("events.management.commands.relay_events.relay_batch", side_effect=down()), \
                mock.patch("events.management.commands.relay_events.time.sleep", lambda _: os.kill(os.getpid(), signal.SIGTERM)):  # 쉬는 동안 종료 신호
            call_command("relay_events", "--interval", "0.01", stdout=io.StringIO(), stderr=err)
        self.assertIn("이번 주기를 건너뛴다", err.getvalue())
        self.assertFormatted(err.getvalue())

    def test_ensure_event_store(self):
        with mock.patch("events.management.commands.ensure_event_store.store.ensure", side_effect=down()):
            self.assertFormatted(self.run_command("ensure_event_store"))


class StoreCheckTests(EventStoreTestCase):
    def detail(self, results, name):
        (found,) = [r for r in results if r.name == name]
        self.assertFalse(found.ok)
        return found.detail

    def test_connection(self):
        with mock.patch("events.store.mongo.client", side_effect=down()):
            self.assertEqual(self.detail(store.check(), "연결"), EXPECTED)

    def test_write_permission(self):
        real = store.collection

        def probe_fails(name=store.COLLECTION):
            if name == store.PROBE_COLLECTION:
                raise down()
            return real(name)

        with mock.patch("events.store.collection", probe_fails):
            self.assertEqual(self.detail(store.check(), "쓰기 권한"), EXPECTED)

    def test_collection(self):
        store.ensure()
        with mock.patch("events.store._validator", side_effect=down()):
            self.assertEqual(self.detail(store.check(), "컬렉션"), EXPECTED)

    def test_check_event_store_command_shows_it(self):
        out = io.StringIO()
        with mock.patch("events.store.mongo.client", side_effect=down()), self.assertRaises(CommandError):
            call_command("check_event_store", stdout=out)
        self.assertIn(EXPECTED, out.getvalue())
        self.assertNotIn("x" * 201, out.getvalue())

