"""Movement is sampled at dirty checkpoints and committed with durable events."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Profile
from accounts.session_policy import expire_record
from eventing.events import SESSION_KEY, enqueue_event, record_floor_transfer
from eventing.models import EventOutbox, PlatformSession
from . import consumers, session_registry
from .positions import DEFAULT_POSITION, save_position


@override_settings(KAFKA_BOOTSTRAP_SERVERS="", CAMPUS_TEST_LEGACY_MOVEMENT=False)
class MovementSnapshotTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="snapshot-user")
        self.original = {"floor": "campus", "x": 100.0, "y": 200.0, "dir": "up"}
        self.position = {**self.original, "x": 1250.125, "y": 442.875, "dir": "left"}
        self.now = timezone.now()
        self.profile = Profile.objects.create(user=self.user, nickname="스냅샷", cohort="mlo-1",
            setup_complete=True, last_position=self.original, last_position_at=self.now)
        self.login = PlatformSession.objects.create(user=self.user, started_at=self.now, last_seen_at=self.now)

    def save(self, position=None, observed_at=None):
        return save_position(self.user, position or self.position,
            observed_at or self.now + timedelta(seconds=1), session_uuid=self.login.pk)

    def test_offline_checkpoint_saves_matching_position_and_durable_event(self):
        self.assertTrue(self.save())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.position)
        row = EventOutbox.objects.get(event_type="movement_observed")
        self.assertEqual(row.topic, "raw.movement")
        self.assertEqual(str(row.message_key), str(self.profile.user_uuid))
        self.assertEqual(row.occurred_at, self.profile.last_position_at)
        self.assertEqual(row.raw_data["x"], self.position["x"])
        self.assertEqual(row.raw_data["y"], self.position["y"])
        self.assertEqual(row.raw_data["session_uuid"], str(self.login.pk))
        self.assertNotIn("dir", row.raw_data)
        self.assertIsNone(row.published_at)

    def test_stale_and_repeated_snapshots_do_not_emit_events(self):
        self.assertFalse(self.save(observed_at=self.now))
        self.assertFalse(self.save(observed_at=self.now - timedelta(seconds=1)))
        self.assertFalse(EventOutbox.objects.exists())
        self.assertTrue(self.save())
        self.assertFalse(self.save())
        self.assertEqual(EventOutbox.objects.count(), 1)

    def test_outbox_failure_rolls_back_position_and_timestamp_and_can_retry(self):
        with patch("eventing.events.enqueue_event", side_effect=DatabaseError("outbox unavailable")):
            with self.assertRaises(DatabaseError):
                self.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.original)
        self.assertEqual(self.profile.last_position_at, self.now)
        self.assertFalse(EventOutbox.objects.exists())
        self.assertTrue(self.save())
        self.assertEqual(EventOutbox.objects.count(), 1)

    def test_direction_only_change_is_restored_without_a_movement_event(self):
        facing = {**self.original, "dir": "left"}
        self.assertTrue(self.save(facing))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, facing)
        self.assertFalse(EventOutbox.objects.exists())

    def test_new_timestamp_at_the_same_location_does_not_emit_another_event(self):
        self.assertTrue(self.save())
        self.assertTrue(self.save(observed_at=self.now + timedelta(seconds=6)))
        self.assertEqual(EventOutbox.objects.filter(event_type="movement_observed").count(), 1)

    def test_floor_change_with_the_same_xy_still_emits_movement(self):
        self.assertTrue(self.save({**self.original, "floor": "rooftop"}))
        self.assertEqual(EventOutbox.objects.filter(event_type="movement_observed").count(), 1)

    def test_event_uses_the_normalized_position_actually_saved(self):
        self.assertTrue(self.save({"floor": "campus", "x": 1999, "y": 1000, "dir": "down"}))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, DEFAULT_POSITION)
        row = EventOutbox.objects.get()
        self.assertEqual((row.raw_data["x"], row.raw_data["y"]),
                         (DEFAULT_POSITION["x"], DEFAULT_POSITION["y"]))

    def test_invalid_or_inactive_positions_are_not_saved_or_logged(self):
        for invalid in [{**self.position, "x": -1}, {**self.position, "x": float("nan")},
                        {**self.position, "floor": "unknown"}]:
            self.assertFalse(self.save(invalid))
        self.user.is_active = False
        self.assertFalse(self.save())
        self.assertFalse(EventOutbox.objects.exists())

    def test_floor_transfer_records_snapshot_and_transfer_once(self):
        position = {**self.position, "floor": "rooftop"}
        observed_at = self.now + timedelta(seconds=1)
        self.assertTrue(record_floor_transfer(self.user, self.login.pk, "campus", "rooftop", position, observed_at))
        self.assertEqual(set(EventOutbox.objects.values_list("event_type", flat=True)),
                         {"movement_observed", "floor_transferred"})
        self.assertFalse(record_floor_transfer(self.user, self.login.pk, "campus", "rooftop", position, observed_at))
        self.assertEqual(EventOutbox.objects.count(), 2)

    def test_transfer_event_failure_rolls_back_snapshot_and_movement_event(self):
        def enqueue(event_type, *args, **kwargs):
            if event_type == "floor_transferred":
                raise DatabaseError("transfer outbox unavailable")
            return enqueue_event(event_type, *args, **kwargs)

        with patch("eventing.events.enqueue_event", side_effect=enqueue):
            with self.assertRaises(DatabaseError):
                record_floor_transfer(self.user, self.login.pk, "campus", "rooftop",
                    {**self.position, "floor": "rooftop"}, self.now + timedelta(seconds=1))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.original)
        self.assertFalse(EventOutbox.objects.exists())

    def register_final_position(self):
        self.client.force_login(self.user)
        self.client.get("/api/learning/csrf/")
        key = self.client.session.session_key
        session_registry.register("final-position", key, self.user.pk)
        session_registry.update("final-position", self.position, timezone.now())
        self.addCleanup(session_registry.unregister, "final-position")
        return key, self.client.session.get(SESSION_KEY)

    def test_http_logout_commits_final_movement_before_ending_session(self):
        key, identity = self.register_final_position()
        self.assertEqual(self.client.post("/accounts/logout/").status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.position)
        row = EventOutbox.objects.get(event_type="movement_observed")
        self.assertEqual(row.raw_data["session_uuid"], identity)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(EventOutbox.objects.filter(event_type="session_ended").count(), 1)

    def test_session_expiry_commits_final_movement_before_invalidating_session(self):
        key, identity = self.register_final_position()
        record = Session.objects.get(session_key=key)
        self.assertTrue(expire_record(record, record.get_decoded(), "idle", notify=False))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.position)
        self.assertEqual(EventOutbox.objects.get(event_type="movement_observed").raw_data["session_uuid"], identity)
        self.assertFalse(Session.objects.filter(session_key=key).exists())


class CheckpointTimingTests(SimpleTestCase):
    def setUp(self):
        self.consumer = consumers.CampusConsumer()
        self.consumer.player_id = "checkpoint-player"
        self.consumer.state = {"floor": "campus", "x": 100.0, "y": 200.0, "dir": "up",
                               "color": "#dfa34d", "moving": False}
        self.consumer.position_dirty = False
        self.consumer.position_changed_at = None
        self.consumer.pending_floor_transfer = None
        self.consumer.last_checkpoint = 0
        self.consumer.last_move = 0
        self.consumer.store_position = AsyncMock(return_value=True)
        self.consumer.broadcast = AsyncMock()
        self.consumer.touch_activity = AsyncMock()
        self.consumer.session_group = None
        self.consumer.channel_name = "test.checkpoint"
        self.consumer.channel_layer = SimpleNamespace(group_discard=AsyncMock())
        self.room = consumers.CampusRoom()
        self.room.players[self.consumer.player_id] = self.consumer.state.copy()
        self.room_patch = patch.object(consumers, "room", self.room)
        self.room_patch.start()
        self.addCleanup(self.room_patch.stop)
        self.clock = [0.0]
        self.time_patch = patch.object(consumers, "time", SimpleNamespace(monotonic=lambda: self.clock[0]))
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)

    async def move(self, x):
        await self.consumer.receive_movement({**self.consumer.state, "x": x, "moving": True}, authoritative=True)

    async def test_stationary_user_never_calls_position_storage_even_when_forced(self):
        for tick in [5, 10, 15]:
            self.clock[0] = tick
            await self.consumer.checkpoint(force=True)
        self.consumer.store_position.assert_not_awaited()

    async def test_many_frames_are_coalesced_into_latest_position_once_per_five_seconds(self):
        for tick in [0.2, 1, 2, 3, 4.9]:
            self.clock[0] = tick
            await self.move(100 + tick)
        self.consumer.store_position.assert_not_awaited()
        self.clock[0] = 5
        await self.move(150)
        self.assertEqual(self.consumer.store_position.await_count, 1)
        self.assertEqual(self.consumer.store_position.await_args.args[0]["x"], 150)
        self.clock[0] = 6
        await self.move(160)
        self.assertEqual(self.consumer.store_position.await_count, 1)
        self.clock[0] = 10
        await self.consumer.checkpoint()
        self.assertEqual(self.consumer.store_position.await_count, 2)
        self.assertEqual(self.consumer.store_position.await_args.args[0]["x"], 160)
        self.assertGreater(self.consumer.broadcast.await_count, 2)

    async def test_stopped_user_saves_final_changed_position_once(self):
        self.clock[0] = 1
        await self.move(125)
        self.clock[0] = 5
        await self.consumer.checkpoint()
        for tick in [10, 15, 20]:
            self.clock[0] = tick
            await self.consumer.checkpoint()
        self.assertEqual(self.consumer.store_position.await_count, 1)

    async def test_failed_outbox_write_keeps_dirty_flag_for_next_checkpoint(self):
        self.consumer.store_position.side_effect = [DatabaseError("outbox unavailable"), True]
        self.clock[0] = 1
        await self.move(125)
        self.clock[0] = 5
        with self.assertLogs("campus.consumers", level="ERROR"):
            await self.consumer.checkpoint()
        self.assertTrue(self.consumer.position_dirty)
        self.clock[0] = 10
        await self.consumer.checkpoint()
        self.assertFalse(self.consumer.position_dirty)
        self.assertEqual(self.consumer.store_position.await_count, 2)

    async def test_newer_frame_during_write_remains_dirty(self):
        self.clock[0] = 1
        await self.move(125)
        observed_at = self.consumer.position_changed_at

        async def write(*args):
            self.consumer.state["x"] = 200
            self.consumer.position_changed_at = observed_at + timedelta(seconds=1)
            self.consumer.position_dirty = True
            return True

        self.consumer.store_position.side_effect = write
        self.clock[0] = 5
        await self.consumer.checkpoint()
        self.assertTrue(self.consumer.position_dirty)
        self.consumer.store_position.side_effect = None
        self.clock[0] = 10
        await self.consumer.checkpoint()
        self.assertEqual(self.consumer.store_position.await_args.args[0]["x"], 200)
        self.assertFalse(self.consumer.position_dirty)

    async def test_floor_transition_and_leave_flush_before_five_seconds(self):
        self.clock[0] = 1
        await self.consumer.receive_movement({**self.consumer.state, "floor": "rooftop", "moving": True}, authoritative=True)
        self.assertEqual(self.consumer.store_position.await_args.args[2], "campus")
        self.clock[0] = 2
        await self.move(150)
        self.assertEqual(self.consumer.store_position.await_count, 1)
        await self.consumer.leave()
        self.assertEqual(self.consumer.store_position.await_count, 2)

    async def test_periodic_presence_check_does_not_bypass_checkpoint_interval(self):
        self.clock[0] = 5
        await self.move(125)
        self.clock[0] = 6
        await self.move(150)
        self.consumer.last_seen = 6
        self.consumer.current_identity = AsyncMock(return_value={})
        await self.consumer.presence_check({})
        self.assertEqual(self.consumer.store_position.await_count, 1)
        self.assertTrue(self.consumer.position_dirty)


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "testserver"], KAFKA_BOOTSTRAP_SERVERS="",
                   CAMPUS_TEST_LEGACY_MOVEMENT=True, CAMPUS_RAFFLE_SCHEDULER_ENABLED=False)
class MovementSocketTests(TransactionTestCase):
    def setUp(self):
        consumers.room = consumers.CampusRoom()
        from raffle.models import Control

        Control.objects.get_or_create(pk=1)
        self.user = get_user_model().objects.create_user(username="movement-socket")
        Profile.objects.create(user=self.user, nickname="이동 확인", cohort="mlo-1", setup_complete=True)
        self.client = Client()
        self.client.force_login(self.user)

    def socket(self):
        from config.asgi import application

        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        return WebsocketCommunicator(application, "/ws/campus/", headers=[
            (b"origin", b"http://127.0.0.1"), (b"host", b"127.0.0.1"),
            (b"cookie", f"{settings.SESSION_COOKIE_NAME}={key}".encode()),
        ])

    @database_sync_to_async
    def movement_rows(self):
        return list(EventOutbox.objects.filter(event_type="movement_observed").values("raw_data", "published_at"))

    async def test_socket_frames_do_not_emit_until_final_checkpoint(self):
        socket = self.socket()
        try:
            connected, _ = await socket.connect()
            self.assertTrue(connected)
            welcome = await socket.receive_json_from()
            position = next(player for player in welcome["players"] if player["id"] == welcome["selfId"])
            for x in [1250.125, 1300.5, 1400.75]:
                await socket.send_json_to({**position, "type": "move", "x": x, "y": 442.875, "moving": True})
                await socket.send_json_to({"type": "ping"})
                self.assertEqual((await socket.receive_json_from())["type"], "pong")
                self.assertEqual(await self.movement_rows(), [])
                await asyncio.sleep(0.05)
            await socket.send_json_to({**position, "type": "leave", "x": 1500.25, "y": 443.625, "moving": False})
            self.assertEqual((await socket.receive_output())["type"], "websocket.close")
            rows = await self.movement_rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["raw_data"]["x"], rows[0]["raw_data"]["y"]), (1500.25, 443.625))
            self.assertIsNone(rows[0]["published_at"])
        finally:
            await socket.disconnect()

    async def test_idle_socket_disconnect_creates_no_movement_event(self):
        socket = self.socket()
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        await socket.receive_json_from()
        await socket.disconnect()
        self.assertEqual(await self.movement_rows(), [])
