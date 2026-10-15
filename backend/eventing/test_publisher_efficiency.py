"""Idle efficiency without changing commit/acknowledgement guarantees."""
from types import SimpleNamespace
import threading
import uuid
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import Profile
from . import events, publisher
from .models import EventOutbox


class CommitWakeupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="wakeup-test")
        Profile.objects.create(user=self.user, nickname="검증", cohort="mlo-1")

    def enqueue(self):
        session_uuid = uuid.uuid4()
        return events.enqueue_event("session_started", self.user, session_uuid,
                                    {"session_uuid": str(session_uuid)})

    def test_wakeup_runs_after_commit_and_not_during_the_transaction(self):
        with patch.object(publisher, "notify_outbox_ready") as notify:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                row = self.enqueue()
                notify.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            notify.assert_called_once_with()
        self.assertTrue(EventOutbox.objects.filter(pk=row.pk).exists())

    def test_rolled_back_outbox_neither_persists_nor_wakes_the_worker(self):
        with patch.object(publisher, "notify_outbox_ready") as notify:
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(RuntimeError):
                    with transaction.atomic():
                        self.enqueue()
                        raise RuntimeError("business operation rolled back")
            notify.assert_not_called()
        self.assertEqual(EventOutbox.objects.count(), 0)


@override_settings(CAMPUS_OUTBOX_IDLE_POLL_SECONDS=5)
class IdleWorkerTests(SimpleTestCase):
    def test_empty_polling_backs_off_and_never_closes_the_connection_per_poll(self):
        stop = threading.Event()
        waits = []

        def wait(unused_stop, seconds):
            waits.append(seconds)
            if len(waits) == 7:
                stop.set()

        queryset = Mock()
        queryset.order_by.return_value.first.return_value = None
        producer = Mock()
        with patch.object(publisher.EventOutbox.objects, "filter", return_value=queryset) as query, \
                patch.object(publisher, "close_old_connections"), \
                patch.object(publisher.connections, "close_all") as close, \
                patch.object(publisher, "_wait_for_work", side_effect=wait), \
                patch.object(publisher, "_wakeup", threading.Event()):
            publisher._publish_pending(producer, stop)
        self.assertEqual(waits, [.25, .5, 1, 2, 4, 5, 5])
        self.assertEqual(query.call_count, 7)
        close.assert_not_called()

    def test_commit_during_empty_read_is_not_lost_before_waiting(self):
        stop = threading.Event()
        wake = threading.Event()
        queryset = Mock()
        calls = []

        def read():
            calls.append(True)
            publisher.notify_outbox_ready()
            if len(calls) == 2:
                stop.set()
            return None

        queryset.order_by.return_value.first.side_effect = read
        with patch.object(publisher.EventOutbox.objects, "filter", return_value=queryset), \
                patch.object(publisher, "close_old_connections"), \
                patch.object(publisher, "_wakeup", wake), \
                patch.object(publisher, "_wait_for_work", wraps=publisher._wait_for_work) as wait:
            publisher._publish_pending(Mock(), stop)
        self.assertEqual(len(calls), 2)
        self.assertEqual(wait.call_count, 2)

    @override_settings(CAMPUS_OUTBOX_IDLE_POLL_SECONDS=.1)
    def test_configured_fallback_poll_ceiling_is_respected(self):
        stop = threading.Event()
        queryset = Mock()
        queryset.order_by.return_value.first.return_value = None
        with patch.object(publisher.EventOutbox.objects, "filter", return_value=queryset), \
                patch.object(publisher, "close_old_connections"), \
                patch.object(publisher, "_wait_for_work", side_effect=lambda *_: stop.set()) as wait:
            publisher._publish_pending(Mock(), stop)
        self.assertEqual(wait.call_args.args[1], .1)


@override_settings(CAMPUS_OUTBOX_CONNECTION_MAX_AGE_SECONDS=60)
class WorkerConnectionTests(SimpleTestCase):
    def test_mysql_worker_options_do_not_change_global_or_request_connection_options(self):
        original = {"CONN_MAX_AGE":0, "CONN_HEALTH_CHECKS":False}
        database = SimpleNamespace(vendor="mysql", settings_dict=original)
        connections = Mock()
        connections.__getitem__ = Mock(return_value=database)
        producer = Mock()
        global_options = settings.DATABASES['default'].copy()

        def inspect(*unused):
            self.assertIsNot(database.settings_dict, original)
            self.assertEqual(database.settings_dict['CONN_MAX_AGE'], 60)
            self.assertTrue(database.settings_dict['CONN_HEALTH_CHECKS'])
            self.assertEqual(original['CONN_MAX_AGE'], 0)
            self.assertEqual(settings.DATABASES['default'], global_options)

        with patch.object(publisher, "connections", connections), \
                patch("confluent_kafka.Producer", return_value=producer), \
                patch.object(publisher, "_publish_pending", side_effect=inspect):
            publisher._publisher_loop(threading.Event())
        self.assertIs(database.settings_dict, original)
        connections.close_all.assert_called_once_with()
        producer.flush.assert_called_once_with(5)

    def test_sqlite_keeps_its_existing_connection_policy(self):
        original = {"CONN_MAX_AGE":0, "CONN_HEALTH_CHECKS":False}
        database = SimpleNamespace(vendor="sqlite", settings_dict=original)
        connections = Mock()
        connections.__getitem__ = Mock(return_value=database)
        with patch.object(publisher, "connections", connections), \
                patch("confluent_kafka.Producer"), \
                patch.object(publisher, "_publish_pending", side_effect=lambda *_: self.assertIs(database.settings_dict, original)):
            publisher._publisher_loop(threading.Event())
        self.assertIs(database.settings_dict, original)

    def test_worker_exit_closes_connection_and_restores_options_even_on_failure(self):
        original = {"CONN_MAX_AGE":0}
        database = SimpleNamespace(vendor="mysql", settings_dict=original)
        connections = Mock()
        connections.__getitem__ = Mock(return_value=database)
        with patch.object(publisher, "connections", connections), \
                patch("confluent_kafka.Producer"), \
                patch.object(publisher, "_publish_pending", side_effect=RuntimeError("stopped")):
            with self.assertRaises(RuntimeError):
                publisher._publisher_loop(threading.Event())
        self.assertIs(database.settings_dict, original)
        connections.close_all.assert_called_once_with()
