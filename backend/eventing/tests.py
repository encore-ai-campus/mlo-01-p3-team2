"""Behavioral checks for the DRD raw-event contracts and failure paths."""
import json
import queue
import threading
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import xxhash
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import DatabaseError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from accounts.session_cleanup import run_due_cleanup
from accounts.session_policy import check_session, start_login
from campus.positions import save_position
from community.models import Comment, Post
from . import events, publisher
from .catalog import CATALOG_IDS, class_group_uuid, floor_uuid
from .models import ChatMessage, ClassGroup, ContentCategory, ContentItem, EventOutbox, MapFloor, MapZone, PlatformSession


class RawEventTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="raw-user", password="Raw!River4820")
        Profile.objects.create(user=cls.user, nickname="원문에 넣지 않을 닉네임", cohort="mlo-1", avatar="male-1")

    def setUp(self):
        self.session_uuid = uuid.uuid4()
        self.now = timezone.now()

    def chat(self):
        return events.record_chat(self.user, self.session_uuid, "운영 DB에만 보관할 메시지", "campus")

    def test_chat_body_and_metadata_commit_together_without_body_in_raw(self):
        message_uuid = self.chat()
        message = ChatMessage.objects.get(pk=message_uuid)
        outbox = EventOutbox.objects.get(event_type="chat_sent")
        self.assertEqual(message.body, "운영 DB에만 보관할 메시지")
        self.assertEqual(message.floor_id, floor_uuid("campus"))
        self.assertEqual(message.expires_at - message.sent_at, timedelta(days=30))
        self.assertEqual(outbox.topic, "raw.chat")
        self.assertEqual(outbox.raw_data["message_uuid"], message_uuid)
        self.assertEqual(outbox.raw_data["floor_uuid"], str(message.floor_id))
        self.assertEqual(outbox.message_key, self.user.campus_profile.user_uuid)
        self.assertEqual(set(outbox.raw_data), {
            "user_uuid", "session_uuid", "class_group_uuid", "message_uuid", "channel_code", "floor_uuid"
        })
        self.assertNotIn(message.body, json.dumps(outbox.payload_json, ensure_ascii=False))
        self.assertNotIn(self.user.campus_profile.nickname, json.dumps(outbox.payload_json, ensure_ascii=False))

    def test_chat_storage_rolls_back_when_outbox_write_fails(self):
        with patch.object(EventOutbox.objects, "create", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                self.chat()
        self.assertFalse(ChatMessage.objects.exists())
        self.assertFalse(EventOutbox.objects.exists())

    def test_events_get_distinct_uuid4_ids_and_deterministic_raw_fingerprints(self):
        self.chat()
        self.chat()
        rows = list(EventOutbox.objects.all())
        self.assertNotEqual(rows[0].event_uuid, rows[1].event_uuid)
        for row in rows:
            self.assertEqual(row.event_uuid.version, 4)
            manifest = row.payload_json["raw_manifest"]
            expected = xxhash.xxh3_64(events.canonical_json(row.raw_data).encode("utf-8")).hexdigest()
            self.assertEqual(manifest["fingerprint"], expected)
            self.assertRegex(manifest["fingerprint"], r"^[0-9a-f]{16}$")
            reordered = dict(reversed(list(row.raw_data.items())))
            envelope = events.build_envelope(row.event_uuid, row.event_type, row.occurred_at, reordered)
            self.assertEqual(envelope["raw_manifest"], manifest)

    def test_raw_time_is_utc_with_millisecond_precision(self):
        raw = events.raw_identity(self.user, self.session_uuid)
        observed = datetime(2026, 10, 9, 15, 38, tzinfo=datetime_timezone(timedelta(hours=9)))
        envelope = events.build_envelope(uuid.uuid4(), "session_started", observed, raw)
        self.assertEqual(envelope["raw_manifest"]["occurred_at"], "2026-10-09T06:38:00.000Z")

    def test_unknown_extra_and_nested_values_are_rejected_without_logging_secrets(self):
        identity = events.raw_identity(self.user, self.session_uuid)
        cases = [
            ("chat_sent", {**identity, "message_uuid": str(uuid.uuid4()), "channel_code": "GLOBAL",
                           "floor_uuid": None, "body": "private-secret"}),
            ("movement_observed", {**identity, "floor_uuid": str(floor_uuid("campus")), "zone_uuid": None,
                                   "x": {"body": "private-secret"}, "y": 100, "input_kind": "KEYBOARD"}),
            ("session_started", {**identity, "session_uuid": None}),
            ("session_started", {**identity, "user_uuid": "private-secret"}),
        ]
        for event_type, raw in cases:
            with self.subTest(event_type=event_type, raw_keys=list(raw)):
                with self.assertLogs("eventing.events", level="ERROR") as captured:
                    with self.assertRaises(ValueError):
                        events.build_envelope(uuid.uuid4(), event_type, self.now, raw)
                self.assertNotIn("private-secret", " ".join(captured.output))
        self.assertFalse(EventOutbox.objects.exists())

    def test_direct_movement_publish_uses_same_privacy_validation(self):
        raw = {**events.raw_identity(self.user, self.session_uuid),
               "floor_uuid": str(floor_uuid("campus")), "zone_uuid": None,
               "x": 10, "y": 20, "input_kind": "KEYBOARD", "nickname": "private-secret"}
        with override_settings(KAFKA_BOOTSTRAP_SERVERS=""):
            with self.assertLogs("eventing.events", level="ERROR"):
                with self.assertRaises(ValueError):
                    events.enqueue_event("movement_observed", self.user, self.session_uuid, raw, occurred_at=self.now)
        self.assertFalse(EventOutbox.objects.exists())

    def test_movement_is_durable_even_without_a_broker(self):
        fields = {"floor_uuid": str(floor_uuid("campus")), "zone_uuid": None,
                  "x": 10.25, "y": 20.5, "input_kind": "KEYBOARD"}
        with override_settings(KAFKA_BOOTSTRAP_SERVERS=""):
            event_id = events.enqueue_event("movement_observed", self.user, self.session_uuid, fields, occurred_at=self.now)
        row = EventOutbox.objects.get(event_uuid=event_id.event_uuid)
        self.assertEqual(row.topic, "raw.movement")
        self.assertEqual(row.raw_data["x"], 10.25)
        self.assertIsNone(row.published_at)

    def test_session_started_once_and_reconnect_does_not_mint_another_session(self):
        session = SessionStore()
        session.save()
        first = events.ensure_platform_session(self.user, session, now=self.now)
        reloaded = SessionStore(session_key=session.session_key)
        self.assertEqual(events.ensure_platform_session(self.user, reloaded, now=self.now), first)
        self.assertEqual(PlatformSession.objects.count(), 1)
        self.assertEqual(EventOutbox.objects.filter(event_type="session_started").count(), 1)
        self.assertEqual(Session.objects.get(pk=session.session_key).get_decoded()[events.SESSION_KEY], first)

    def test_session_creation_rolls_back_if_django_session_cannot_be_saved(self):
        session = SessionStore()
        session.save()
        with patch.object(session, "save", side_effect=DatabaseError("session unavailable")):
            with self.assertRaises(DatabaseError):
                events.ensure_platform_session(self.user, session)
        self.assertFalse(PlatformSession.objects.exists())
        self.assertFalse(EventOutbox.objects.exists())

    def test_session_end_is_idempotent_and_failed_outbox_does_not_end_it(self):
        session = SessionStore()
        identity = events.start_platform_session(self.user, session)
        with patch.object(EventOutbox.objects, "create", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                events.end_platform_session(self.user, session, "LOGOUT")
        record = PlatformSession.objects.get(pk=identity)
        self.assertIsNone(record.ended_at)
        self.assertTrue(events.end_platform_session(self.user, session, "LOGOUT"))
        self.assertFalse(events.end_platform_session(self.user, session, "LOGOUT"))
        ended = EventOutbox.objects.get(event_type="session_ended")
        self.assertEqual(ended.raw_data["session_uuid"], identity)
        self.assertEqual(ended.raw_data["end_reason"], "LOGOUT")

    def test_offline_idle_session_gets_an_end_event_during_daily_cleanup(self):
        self.client.force_login(self.user)
        session = self.client.session
        old = self.now - timedelta(hours=1)
        with patch("accounts.session_policy.timezone.now", return_value=old):
            start_login(session, self.user)
        session.save()
        session_uuid = session[events.SESSION_KEY]
        key = session.session_key
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cleanup.json"
            self.assertTrue(run_due_cleanup(self.now, path))
            self.assertFalse(run_due_cleanup(self.now, path))
        self.assertFalse(Session.objects.filter(pk=key).exists())
        record = PlatformSession.objects.get(pk=session_uuid)
        self.assertEqual(record.end_reason, "SESSION_EXPIRED")
        self.assertEqual(record.ended_at, self.now)
        self.assertEqual(EventOutbox.objects.filter(event_type="session_ended").count(), 1)

    def test_expired_http_session_is_not_recreated_by_logging_middleware(self):
        self.client.force_login(self.user)
        session = self.client.session
        with patch("accounts.session_policy.timezone.now", return_value=self.now - timedelta(hours=1)):
            start_login(session, self.user)
        session.save()
        self.assertEqual(self.client.get("/accounts/session/status/").status_code, 401)
        self.assertEqual(PlatformSession.objects.count(), 1)
        self.assertEqual(EventOutbox.objects.filter(event_type="session_started").count(), 1)
        self.assertEqual(EventOutbox.objects.filter(event_type="session_ended").count(), 1)

    def test_chat_cleanup_only_deletes_expired_bodies_and_keeps_raw_metadata(self):
        message_uuid = self.chat()
        ChatMessage.objects.filter(pk=message_uuid).update(expires_at=self.now - timedelta(seconds=1))
        retained_uuid = self.chat()
        with TemporaryDirectory() as directory:
            run_due_cleanup(self.now, Path(directory) / "cleanup.json")
        self.assertFalse(ChatMessage.objects.filter(pk=message_uuid).exists())
        self.assertTrue(ChatMessage.objects.filter(pk=retained_uuid).exists())
        self.assertEqual(EventOutbox.objects.filter(event_type="chat_sent").count(), 2)

    def test_floor_event_is_created_only_when_snapshot_update_succeeds(self):
        initial = {"floor": "campus", "x": 1900, "y": 800, "dir": "up"}
        rooftop = {"floor": "rooftop", "x": 100, "y": 1200, "dir": "left"}
        save_position(self.user, initial, self.now)
        observed = self.now + timedelta(seconds=1)
        self.assertTrue(events.record_floor_transfer(self.user, self.session_uuid, "campus", "rooftop", rooftop, observed))
        self.assertFalse(events.record_floor_transfer(self.user, self.session_uuid, "campus", "rooftop", rooftop, observed))
        self.assertFalse(events.record_floor_transfer(self.user, self.session_uuid, "rooftop", "campus", initial, self.now))
        self.assertFalse(events.record_floor_transfer(self.user, self.session_uuid, "campus", "rooftop", {**rooftop, "x": -1}))
        row = EventOutbox.objects.get(event_type="floor_transferred")
        self.assertEqual(row.topic, "raw.movement")
        self.assertEqual(row.raw_data["from_floor_uuid"], str(floor_uuid("campus")))
        self.assertEqual(row.raw_data["to_floor_uuid"], str(floor_uuid("rooftop")))
        self.assertEqual(Profile.objects.get(user=self.user).last_position["floor"], "rooftop")

    def test_floor_snapshot_rolls_back_when_event_storage_fails(self):
        initial = {"floor": "campus", "x": 1900, "y": 800, "dir": "up"}
        save_position(self.user, initial, self.now)
        with patch.object(EventOutbox.objects, "create", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                events.record_floor_transfer(self.user, self.session_uuid, "campus", "rooftop",
                                             {"floor": "rooftop", "x": 100, "y": 1200, "dir": "left"},
                                             self.now + timedelta(seconds=1))
        self.assertEqual(Profile.objects.get(user=self.user).last_position["floor"], "campus")
        self.assertFalse(EventOutbox.objects.exists())

    def test_event_uses_class_group_at_the_time_of_acceptance(self):
        first = events.raw_identity(self.user, self.session_uuid)
        Profile.objects.filter(user=self.user).update(cohort="skn-34", nickname="바뀐 이름")
        self.chat()
        row = EventOutbox.objects.get()
        self.assertEqual(row.raw_data["user_uuid"], first["user_uuid"])
        self.assertEqual(row.raw_data["class_group_uuid"], str(class_group_uuid("skn-34")))
        self.assertNotEqual(row.raw_data["class_group_uuid"], first["class_group_uuid"])


class HttpEventTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="event-http", password="Event!River4820")
        Profile.objects.create(user=cls.user, nickname="HTTP 작성자", cohort="mlo-1", avatar="male-1")

    def setUp(self):
        self.client.force_login(self.user)
        self.client.get(reverse("community:metadata"))

    def send(self, method, url, data=None):
        return getattr(self.client, method)(url, data=json.dumps(data) if data is not None else "", content_type="application/json")

    def test_accepted_content_request_logs_before_redirect_for_each_catalog_link(self):
        for code in ("gomoku", "war", "dad-and-me", "minesweeper", "fruit-box", "bubble-shooter", "suika", "flashman", "psych-test",
                     "tetris", "worlds-hardest-game", "bamboo-master", "sword-upgrade", "walk-the-stork", "isaac", "paladog", "solitaire"):
            content = ContentItem.objects.get(code=code)
            response = self.client.get(f"/content/{code}/open/")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], content.external_url)
            row = EventOutbox.objects.filter(event_type="content_open_requested", raw_data__content_uuid=str(content.pk)).get()
            self.assertEqual(row.topic, "raw.content_usage")
            self.assertEqual(row.raw_data["category_uuid"], str(content.category_id))
            self.assertEqual(row.raw_data["domain"], "REST")
            self.assertEqual(row.raw_data["domain"], content.category.domain)
            self.assertEqual(row.raw_data["zone_uuid"], str(content.zone_id))
            self.assertEqual(row.raw_data["action"], "OPEN_REQUESTED")
        self.assertEqual(EventOutbox.objects.filter(event_type="content_open_requested").count(), 17)

    def test_unauthenticated_hidden_and_unknown_links_do_not_make_usage_events(self):
        self.assertEqual(Client().get("/content/gomoku/open/").status_code, 401)
        ContentItem.objects.filter(code="gomoku").update(status="HIDDEN")
        self.assertEqual(self.client.get("/content/gomoku/open/").status_code, 404)
        self.assertEqual(self.client.get("/content/missing/open/").status_code, 404)
        self.assertFalse(EventOutbox.objects.filter(event_type="content_open_requested").exists())

    def test_content_request_cannot_redirect_if_event_cannot_be_committed(self):
        with patch("eventing.views.record_content_open", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                self.client.get("/content/gomoku/open/")
        self.assertFalse(EventOutbox.objects.filter(event_type="content_open_requested").exists())

    def test_post_and_comment_revisions_and_soft_delete_events_match_api_results(self):
        response = self.send("post", reverse("community:posts"),
                             {"category": "free", "title": "원문 제목", "body": "게시글 원문"})
        self.assertEqual(response.status_code, 201)
        post = response.json()["post"]
        detail = reverse("community:post-detail", args=[post["id"]])
        self.assertEqual(self.client.get(detail).json()["post"]["revision"], 1)
        changed = self.send("patch", detail, {"title": "수정 제목", "version": post["updatedAt"]})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["post"]["revision"], 2)
        comment_response = self.send("post", reverse("community:comments", args=[post["id"]]), {"body": "댓글 원문"})
        comment = comment_response.json()["comment"]
        comment_url = reverse("community:comment-detail", args=[comment["id"]])
        self.assertEqual(self.send("patch", comment_url, {"body": "댓글 수정", "version": comment["updatedAt"]}).status_code, 200)
        self.assertEqual(self.send("delete", comment_url).status_code, 200)
        self.assertEqual(self.send("delete", detail).status_code, 200)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertIsNotNone(Post.objects.get(pk=post["id"]).deleted_at)
        self.assertIsNotNone(Comment.objects.get(pk=comment["id"]).deleted_at)
        for prefix, topic in (("post", "raw.board"), ("comment", "raw.comment")):
            for action, revision in (("created", 1), ("updated", 2), ("deleted", 3)):
                row = EventOutbox.objects.get(event_type=f"{prefix}_{action}")
                self.assertEqual((row.topic, row.raw_data["revision"]), (topic, revision))
                self.assertNotIn("body", row.raw_data)
                self.assertNotIn("title", row.raw_data)
        self.assertEqual(EventOutbox.objects.get(event_type="post_read").raw_data["revision"], 1)

    def test_rejected_stale_changes_do_not_make_update_events(self):
        post = Post.objects.create(author=self.user, category="free", title="글", body="원문")
        url = reverse("community:post-detail", args=[post.pk])
        original = post.updated_at.isoformat()
        self.assertEqual(self.send("patch", url, {"title": "첫 변경", "version": original}).status_code, 200)
        self.assertEqual(self.send("patch", url, {"title": "오래된 변경", "version": original}).status_code, 409)
        self.assertEqual(EventOutbox.objects.filter(event_type="post_updated").count(), 1)
        post.refresh_from_db()
        self.assertEqual((post.title, post.revision), ("첫 변경", 2))

    def test_reply_events_use_raw_comment_and_keep_the_same_parent_uuid(self):
        post = Post.objects.create(author=self.user, category="free", title="답글", body="본문")
        parent = Comment.objects.create(post=post, author=self.user, body="부모 댓글")
        created = self.send("post", reverse("community:comments", args=[post.pk]), {
            "body": "대댓글 원문", "parentCommentUuid": str(parent.comment_uuid),
        })
        self.assertEqual(created.status_code, 201)
        reply = created.json()["comment"]
        url = reverse("community:comment-detail", args=[reply["id"]])
        self.assertEqual(self.send("patch", url, {"body": "대댓글 수정", "version": reply["updatedAt"]}).status_code, 200)
        self.assertEqual(self.send("delete", url).status_code, 200)
        for event_type, revision in (("comment_created", 1), ("comment_updated", 2), ("comment_deleted", 3)):
            row = EventOutbox.objects.get(event_type=event_type)
            self.assertEqual(row.topic, "raw.comment")
            self.assertEqual(row.raw_data["parent_comment_uuid"], str(parent.comment_uuid))
            self.assertEqual(row.raw_data["comment_uuid"], reply["commentUuid"])
            self.assertEqual(row.raw_data["post_uuid"], str(post.post_uuid))
            self.assertEqual(row.raw_data["revision"], revision)
            self.assertNotIn("body", row.raw_data)
        self.assertEqual(EventOutbox.objects.filter(event_type__startswith="comment_").count(), 3)

    def test_invalid_replies_do_not_emit_comment_events(self):
        post = Post.objects.create(author=self.user, category="free", title="답글", body="본문")
        parent = Comment.objects.create(post=post, author=self.user, body="부모 댓글")
        reply = Comment.objects.create(post=post, parent=parent, author=self.user, body="답글")
        for parent_uuid in (str(uuid.uuid4()), str(reply.comment_uuid), "invalid"):
            response = self.send("post", reverse("community:comments", args=[post.pk]), {
                "body": "잘못된 답글", "parentCommentUuid": parent_uuid,
            })
            self.assertIn(response.status_code, (400, 404))
        self.assertFalse(EventOutbox.objects.filter(event_type__startswith="comment_").exists())

    def test_reply_mutations_roll_back_if_outbox_cannot_commit(self):
        post = Post.objects.create(author=self.user, category="free", title="답글", body="본문")
        parent = Comment.objects.create(post=post, author=self.user, body="부모 댓글")
        with patch("community.views.record_comment_event", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                self.send("post", reverse("community:comments", args=[post.pk]), {
                    "body": "실패 답글", "parentCommentUuid": str(parent.comment_uuid),
                })
        self.assertEqual(Comment.objects.count(), 1)
        reply = Comment.objects.create(post=post, parent=parent, author=self.user, body="수정 전 답글")
        url = reverse("community:comment-detail", args=[reply.pk])
        for method, data in (("patch", {"body": "실패 수정", "version": reply.updated_at.isoformat()}), ("delete", None)):
            with patch("community.views.record_comment_event", side_effect=DatabaseError("outbox unavailable")):
                with self.assertRaises(DatabaseError):
                    self.send(method, url, data)
            reply.refresh_from_db()
            self.assertEqual((reply.body, reply.revision, reply.deleted_at), ("수정 전 답글", 1, None))
        self.assertFalse(EventOutbox.objects.filter(event_type__startswith="comment_").exists())

    def test_post_mutation_and_read_fail_if_outbox_cannot_commit(self):
        with patch("community.views.record_post_event", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                self.send("post", reverse("community:posts"), {"category": "free", "title": "실패", "body": "원문"})
        self.assertFalse(Post.objects.exists())
        post = Post.objects.create(author=self.user, category="free", title="원래 제목", body="원문")
        url = reverse("community:post-detail", args=[post.pk])
        with patch("community.views.record_post_event", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                self.send("patch", url, {"title": "실패 변경", "version": post.updated_at.isoformat()})
            with self.assertRaises(DatabaseError):
                self.client.get(url)
        post.refresh_from_db()
        self.assertEqual((post.title, post.revision), ("원래 제목", 1))

    def test_comment_mutation_rolls_back_if_outbox_cannot_commit(self):
        post = Post.objects.create(author=self.user, category="free", title="글", body="원문")
        with patch("community.views.record_comment_event", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                self.send("post", reverse("community:comments", args=[post.pk]), {"body": "실패 댓글"})
        self.assertFalse(Comment.objects.exists())

    def test_http_logout_ends_the_original_login_session_once(self):
        session_uuid = self.client.session[events.SESSION_KEY]
        self.assertEqual(self.client.post("/accounts/logout/").status_code, 302)
        record = PlatformSession.objects.get(pk=session_uuid)
        self.assertEqual(record.end_reason, "LOGOUT")
        row = EventOutbox.objects.get(event_type="session_ended")
        self.assertEqual(row.raw_data["session_uuid"], session_uuid)
        self.client.post("/accounts/logout/")
        self.assertEqual(EventOutbox.objects.filter(event_type="session_ended").count(), 1)


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


class CatalogMigrationTests(TestCase):
    def setUp(self):
        ContentItem.objects.all().delete()
        ContentCategory.objects.all().delete()
        MapZone.objects.all().delete()
        MapFloor.objects.all().delete()
        ClassGroup.objects.all().delete()
        import_module("eventing.migrations.0002_seed_raw_catalog").seed_catalog(apps, None)
        self.user = get_user_model().objects.create_user(username="catalog-user")
        Profile.objects.create(user=self.user, nickname="참조 검사")
        self.old_floor = MapFloor.objects.get(code="campus").pk
        self.old_content = ContentItem.objects.get(code="gomoku")
        self.old_content.title = "운영자가 수정한 제목"
        self.old_content.save()
        self.message = ChatMessage.objects.create(user=self.user, body="기존 메시지", floor_id=self.old_floor,
                                                 sent_at=timezone.now(), expires_at=timezone.now() + timedelta(days=30))

    def old_event(self, published=False):
        raw = {"user_uuid": str(self.user.campus_profile.user_uuid), "session_uuid": str(uuid.uuid4()),
               "class_group_uuid": str(ClassGroup.objects.get(code="mlo-1").pk),
               "content_uuid": str(self.old_content.pk), "category_uuid": str(self.old_content.category_id),
               "domain": self.old_content.category.domain, "content_kind": "EXTERNAL_LINK",
               "zone_uuid": str(self.old_content.zone_id), "action": "OPEN_REQUESTED"}
        event_uuid = uuid.uuid4()
        payload = {"event_uuid": str(event_uuid), "raw_data": raw, "raw_manifest": {
            "schema_version": "1.0", "event_type": "content_open_requested",
            "occurred_at": "2026-10-10T00:00:00.000Z", "source": "platform_server_1",
            "fingerprint_algorithm": "xxh3_64",
            "fingerprint": xxhash.xxh3_64(events.canonical_json(raw).encode("utf-8")).hexdigest()}}
        return EventOutbox.objects.create(event_uuid=event_uuid, event_type="content_open_requested", topic="raw.content_usage",
                                          message_key=self.user.campus_profile.user_uuid, raw_data=raw, payload_json=payload,
                                          occurred_at=timezone.now(), published_at=timezone.now() if published else None)

    def migrate_catalog(self):
        with transaction.atomic():
            import_module("eventing.migrations.0003_catalog_uuid4").rekey_catalog(apps, None)

    def test_uuid4_conversion_preserves_foreign_keys_custom_fields_and_pending_event_id(self):
        row = self.old_event()
        event_id = row.pk
        self.migrate_catalog()
        self.message.refresh_from_db()
        self.assertEqual(self.message.floor_id, floor_uuid("campus"))
        content = ContentItem.objects.get(code="gomoku")
        self.assertEqual(content.title, "운영자가 수정한 제목")
        self.assertEqual(content.created_at, self.old_content.created_at)
        for Model in (ClassGroup, MapFloor, MapZone, ContentCategory, ContentItem):
            self.assertTrue(all(item.pk.version == 4 for item in Model.objects.all()))
        row.refresh_from_db()
        self.assertEqual(row.pk, event_id)
        self.assertEqual(row.raw_data["content_uuid"], str(content.pk))
        self.assertEqual(row.payload_json["raw_data"], row.raw_data)
        self.assertEqual(row.payload_json["raw_manifest"]["fingerprint"],
                         xxhash.xxh3_64(events.canonical_json(row.raw_data).encode("utf-8")).hexdigest())
        self.migrate_catalog()
        self.assertEqual([Model.objects.count() for Model in (ClassGroup, MapFloor, MapZone, ContentCategory, ContentItem)],
                         [6, 2, 3, 2, 3])

    def test_already_published_event_and_its_referenced_catalog_ids_are_preserved(self):
        row = self.old_event(published=True)
        original = row.payload_json
        self.migrate_catalog()
        row.refresh_from_db()
        self.assertEqual(row.payload_json, original)
        self.assertTrue(ContentItem.objects.filter(pk=self.old_content.pk, status="HIDDEN").exists())
        self.assertEqual(ContentItem.objects.get(code="gomoku").pk, CATALOG_IDS[("content", "gomoku")])
        self.assertTrue(ClassGroup.objects.filter(pk=row.raw_data["class_group_uuid"], status="INACTIVE").exists())

    def test_failed_conversion_rolls_back_all_previous_reference_updates(self):
        with patch.object(ContentItem.objects, "create", side_effect=DatabaseError("catalog unavailable")):
            with self.assertRaises(DatabaseError):
                self.migrate_catalog()
        self.message.refresh_from_db()
        self.assertEqual(self.message.floor_id, self.old_floor)
        self.assertEqual(ContentItem.objects.get(code="gomoku").pk, self.old_content.pk)
        self.assertEqual(ClassGroup.objects.count(), 6)


class CategoryDomainMigrationTests(TestCase):
    def test_reclassification_keeps_catalog_ids_and_historical_events(self):
        category = ContentCategory.objects.get(code="game")
        category.domain = "LEARNING"
        category.save(update_fields=["domain"])
        content_ids = dict(ContentItem.objects.values_list("code", "content_uuid"))
        category_ids = dict(ContentCategory.objects.values_list("code", "category_uuid"))
        user = get_user_model().objects.create_user(username="domain-migration")
        Profile.objects.create(user=user, nickname="분류 검사", cohort="mlo-1")
        session_uuid = uuid.uuid4()
        content = ContentItem.objects.select_related("category", "zone").get(code="gomoku")
        old_event = events.record_content_open(user, session_uuid, content)
        original_payload = old_event.payload_json
        original_raw = old_event.raw_data

        migration = import_module("eventing.migrations.0004_game_category_rest")
        with transaction.atomic():
            migration.move_games_to_rest(apps, None)

        self.assertEqual(dict(ContentItem.objects.values_list("code", "content_uuid")), content_ids)
        self.assertEqual(dict(ContentCategory.objects.values_list("code", "category_uuid")), category_ids)
        old_event.refresh_from_db()
        self.assertEqual(old_event.raw_data, original_raw)
        self.assertEqual(old_event.payload_json, original_payload)
        self.assertEqual(old_event.raw_data["domain"], "LEARNING")
        content = ContentItem.objects.select_related("category", "zone").get(code="gomoku")
        new_event = events.record_content_open(user, session_uuid, content)
        self.assertEqual(new_event.raw_data["domain"], "REST")
        self.assertEqual(new_event.raw_data["category_uuid"], str(category_ids["game"]))
        self.assertNotEqual(category_ids["game"], category_ids["psychology"])

    def test_reverse_only_restores_game_domain_and_keeps_future_learning_category(self):
        learning = ContentCategory.objects.create(code="learning-material", name="학습 자료", domain="LEARNING")
        identities = dict(ContentCategory.objects.values_list("code", "category_uuid"))
        migration = import_module("eventing.migrations.0004_game_category_rest")
        migration.restore_previous_domain(apps, None)
        self.assertEqual(ContentCategory.objects.get(code="game").domain, "LEARNING")
        self.assertEqual(ContentCategory.objects.get(code="psychology").domain, "REST")
        migration.move_games_to_rest(apps, None)
        self.assertEqual(ContentCategory.objects.get(code="game").domain, "REST")
        learning.refresh_from_db()
        self.assertEqual(learning.domain, "LEARNING")
        self.assertEqual(dict(ContentCategory.objects.values_list("code", "category_uuid")), identities)
