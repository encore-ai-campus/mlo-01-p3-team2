import json
import threading
import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from accounts.models import Profile
from . import events, publisher
from .models import EventOutbox


class PublisherTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="publisher-user")
        Profile.objects.create(user=self.user, nickname="발행 검사", cohort="mlo-1")
        session_uuid = uuid.uuid4()
        self.row = events.enqueue_event("session_started", self.user, session_uuid,
                                       {"session_uuid": str(session_uuid)})

    def deliver_once(self, error=None, acknowledge=True):
        stop = threading.Event()
        sent = []
        callback = [None]

        class FakeProducer:
            def produce(self, topic, **kwargs):
                sent.append((topic, kwargs["key"], kwargs["value"]))
                callback[0] = kwargs["on_delivery"]

            def poll(self, timeout):
                if acknowledge:
                    callback[0](error, None)
                stop.set()

            def flush(self, timeout):
                return 0

        with override_settings(KAFKA_BOOTSTRAP_SERVERS="fake-broker:9092"), \
                patch("confluent_kafka.Producer", return_value=FakeProducer()), \
                patch.object(publisher, "close_old_connections"), \
                patch.object(publisher.connections, "close_all"), \
                patch.object(publisher, "_stop", stop):
            publisher._publisher_loop(stop)
        return sent

    def test_only_broker_ack_marks_event_published(self):
        sent = self.deliver_once()
        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.published_at)
        self.assertEqual(sent[0][0], "raw.account")
        self.assertEqual(sent[0][1].decode(), str(self.row.message_key))
        self.assertEqual(json.loads(sent[0][2]), self.row.payload_json)

    def test_failure_is_pending_and_retry_reuses_identical_event_and_payload(self):
        with self.assertLogs("eventing.publisher", level="WARNING"):
            first = self.deliver_once(RuntimeError("unavailable"))
        self.row.refresh_from_db()
        self.assertIsNone(self.row.published_at)
        self.assertEqual(self.row.retry_count, 1)
        second = self.deliver_once()
        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.published_at)
        self.assertEqual(first, second)
        self.assertEqual(EventOutbox.objects.count(), 1)

    def test_produce_return_without_delivery_callback_does_not_count_as_ack(self):
        with self.assertLogs("eventing.publisher", level="WARNING"):
            self.deliver_once(acknowledge=False)
        self.row.refresh_from_db()
        self.assertIsNone(self.row.published_at)
        self.assertEqual(self.row.retry_count, 1)


class MovementPublisherTests(TestCase):
    deliver_once = PublisherTests.deliver_once

    def setUp(self):
        from campus.positions import save_position

        self.user = get_user_model().objects.create_user(username="movement-publisher")
        save_position(self.user, {"floor": "campus", "x": 100, "y": 200, "dir": "up"},
                      session_uuid=uuid.uuid4())
        self.row = EventOutbox.objects.get(event_type="movement_observed")

    def test_movement_failure_is_retried_from_outbox_with_the_same_payload(self):
        with self.assertLogs("eventing.publisher", level="WARNING"):
            first = self.deliver_once(RuntimeError("broker unavailable"))
        self.row.refresh_from_db()
        self.assertIsNone(self.row.published_at)
        self.assertEqual(self.row.retry_count, 1)
        second = self.deliver_once()
        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.published_at)
        self.assertEqual(first, second)
        self.assertEqual(first[0][0], "raw.movement")
        self.assertEqual(json.loads(first[0][2]), self.row.payload_json)
        self.assertEqual(EventOutbox.objects.count(), 1)
