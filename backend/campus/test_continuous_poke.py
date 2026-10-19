"""Held pokes repeat locally, with bounded server hits and nearby-only state changes."""
import asyncio
import json
import math
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.contrib.sessions.models import Session
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from eventing.models import EventOutbox

from . import consumers, poke
from .motion import MotionController
from .test_poke import PokeSocketTests


class ContinuousPokeTests(SimpleTestCase):
    def setUp(self):
        self.clock = [0.0]
        self.room = consumers.CampusRoom()
        self.consumer = c = consumers.CampusConsumer()
        c.player_id = "self"
        c.controller = MotionController({"floor": "campus", "x": 130, "y": 100, "dir": "right"})
        c.state = {"id": "self", **c.controller.pose}
        c.server_control = True
        c.control_lock = asyncio.Lock()
        c.policy_status = {"expiresAt": int((time.time() + 3600) * 1000)}
        c.last_seen = 0
        c.last_poke = -math.inf
        c.poke_requested = True
        c.poke_input_scope = None
        c.poke_started = None
        c.poke_scope = None
        c.poke_stream_id = None
        c.poke_direction = None
        c.poke_watchers = set()
        c.send_packet = AsyncMock()
        c.current_identity = AsyncMock(return_value={})
        c.touch_activity = AsyncMock()
        c.checkpoint = AsyncMock()
        self.room.players = {"self": c.state.copy(),
                             "near": {"id": "near", "floor": "campus", "x": 130 + 32 / math.sqrt(2), "y": 100 - 32 / math.sqrt(2)},
                             "far": {"id": "far", "floor": "campus", "x": 900, "y": 100},
                             "roof": {"id": "roof", "floor": "rooftop", "x": 130, "y": 100}}
        self.room.channels = {key: "channel." + key for key in self.room.players}
        self.room.sockets = {key: SimpleNamespace(send=AsyncMock()) for key in self.room.players}
        self.room_patch = patch.object(consumers, "room", self.room)
        self.room_patch.start()
        self.addCleanup(self.room_patch.stop)
        self.time_patch = patch.object(consumers, "time", SimpleNamespace(monotonic=lambda: self.clock[0], time=time.time))
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)

    def packets(self, recipient="self"):
        # 찌르기는 받는 사람의 다음 0.1초 묶음에 실린다(계획 §8)
        return [json.loads(text) for text in self.room.pending_effects.get(recipient, [])]

    async def tick(self, seconds, *, refresh=True):
        self.clock[0] = seconds
        if refresh:
            self.consumer.controller.last_input = seconds
        await self.consumer.tick_poke()

    async def test_holding_sends_one_start_and_four_hits_per_second_without_database_reads(self):
        for step in range(100):
            await self.tick(step / 100)
        packets = self.packets()
        self.assertEqual(sum(row["type"] == "poke_state" for row in packets), 1)
        self.assertEqual(sum(row["type"] == "poke_hit" for row in packets), 4)
        self.assertEqual(self.packets("far"), [])
        self.assertEqual(self.packets("roof"), [])
        self.consumer.current_identity.assert_not_awaited()
        self.consumer.touch_activity.assert_not_awaited()
        self.consumer.checkpoint.assert_not_awaited()

    async def test_misses_have_no_repeated_network_packets(self):
        self.consumer.controller.input(["a"], now=0)
        for step in range(100):
            await self.tick(step / 100)
        self.assertEqual([row["type"] for row in self.packets()], ["poke_state"])
        self.consumer.poke_requested = False
        await self.tick(1)
        self.assertEqual([row["active"] for row in self.packets()], [True, False])

    async def test_input_lease_stops_a_missing_keyup(self):
        await self.tick(0)
        await self.tick(poke.INPUT_LEASE + .01, refresh=False)
        self.assertIsNone(self.consumer.poke_started)
        self.assertFalse(self.packets()[-1]["active"])
        before = len(self.packets())
        await self.tick(2, refresh=False)
        self.assertEqual(len(self.packets()), before)

    async def test_audience_join_and_leave_only_update_affected_sockets(self):
        await self.tick(0)
        stream = self.packets()[0]["id"]
        self.room.players["near"]["x"] = 1000
        self.room.players["far"].update(x=330, y=100)
        await self.tick(.25)
        self.assertFalse(self.packets("near")[-1]["active"])
        self.assertEqual(self.packets("far")[0]["id"], stream)
        self.assertTrue(self.packets("far")[0]["active"])
        self.assertEqual(sum(row["type"] == "poke_state" for row in self.packets()), 1)

    async def test_direction_changes_are_throttled_and_keep_the_same_stream(self):
        await self.tick(0)
        identity = self.packets()[0]["id"]
        self.consumer.controller.input(["w", "d"], now=.1)
        await self.tick(.1)
        self.assertEqual(sum(row["type"] == "poke_state" for row in self.packets()), 1)
        await self.tick(.25)
        state = [row for row in self.packets() if row['type'] == 'poke_state'][-1]
        self.assertEqual((state["type"], state["dir"], state["id"]), ("poke_state", "up-right", identity))

    async def test_private_npc_hits_only_reach_the_owner(self):
        self.consumer.controller.interior = {"subject": "python", "actor": {"x": 154, "y": 239, "dir": "left", "moving": False}}
        await self.tick(0)
        self.assertEqual(self.packets("near"), [])
        hit = self.packets()[-1]
        self.assertEqual((hit["type"], hit["targetId"]), ("poke_hit", "resident-student-0-0-chair"))

    async def test_scope_change_stops_the_old_hold(self):
        await self.tick(0)
        self.consumer.controller.interior = {"subject": "python", "actor": {"x": 154, "y": 239, "dir": "left", "moving": False}}
        await self.tick(.1)
        self.assertFalse(self.consumer.poke_requested)
        self.assertIsNone(self.consumer.poke_started)
        self.assertFalse(self.packets("near")[-1]["active"])

    async def test_bad_context_and_malformed_hold_do_not_start_a_stream(self):
        self.consumer.poke_requested = False
        await self.consumer.receive(text_data=json.dumps({"type": "input", "keys": [], "poking": True,
            "pokeContext": {"context": "world", "floor": "rooftop"}}))
        self.assertEqual(self.packets(), [])
        await self.consumer.receive(text_data=json.dumps({"type": "input", "keys": [], "poking": "true"}))
        self.assertEqual(self.consumer.send_packet.await_args.args[0]["type"], "control_error")

    async def test_session_checks_remain_in_the_periodic_guard(self):
        await self.tick(0)
        self.consumer.current_identity.assert_not_awaited()
        await self.consumer.presence_check({})
        self.consumer.current_identity.assert_awaited_once()
        self.consumer.touch_activity.assert_awaited_once()

    async def test_heartbeats_reuse_scope_but_cannot_carry_it_into_a_classroom(self):
        self.consumer.poke_requested = False
        await self.consumer.receive(text_data=json.dumps({'type': 'input', 'keys': [], 'poking': True,
            'pokeContext': {'context': 'world', 'floor': 'campus'}}))
        await self.consumer.receive(text_data=json.dumps({'type': 'input', 'keys': [], 'poking': True}))
        self.assertTrue(self.consumer.poke_requested)
        self.consumer.controller.interior = {'subject': 'python', 'actor': {'x': 154, 'y': 239, 'dir': 'left', 'moving': False}}
        await self.consumer.receive(text_data=json.dumps({'type': 'input', 'keys': [], 'poking': True}))
        self.assertFalse(self.consumer.poke_requested)
        self.assertIsNone(self.consumer.poke_started)

    async def test_effects_ride_each_recipients_batch_and_a_broken_socket_does_not_stop_the_others(self):
        await self.tick(0)
        self.room.sockets['near'].send.side_effect = RuntimeError('closing')
        self.room.flusher = None
        with patch.object(consumers.asyncio, 'sleep', AsyncMock(side_effect=[None, asyncio.CancelledError])):
            with self.assertRaises(asyncio.CancelledError):
                await consumers.flush_moves(self.room)
        sent = json.loads(self.room.sockets['self'].send.await_args.kwargs['text_data'])
        self.assertEqual((sent['type'], sent['players']), ('moves', []))
        self.assertEqual([row['type'] for row in sent['effects']], ['poke_state', 'poke_hit'])
        self.room.sockets['far'].send.assert_not_awaited()  # 실을 것이 없는 사람에게는 보내지 않는다
        self.assertEqual(self.room.pending_effects, {})


@override_settings(ALLOWED_HOSTS=['127.0.0.1', 'testserver'], KAFKA_BOOTSTRAP_SERVERS='')
class ContinuousPokeSocketTests(TransactionTestCase):
    setUp = PokeSocketTests.setUp
    socket = PokeSocketTests.socket
    packets = PokeSocketTests.packets
    @database_sync_to_async
    def movement_count(self):
        return EventOutbox.objects.filter(event_type='movement_observed').count()

    async def hold(self, socket, active=True):
        await socket.send_json_to({"type": "input", "keys": [], "poking": active,
                                  "pokeContext": {"context": "world", "floor": "campus"}})

    async def test_held_key_repeats_and_keyup_stops_both_clients(self):
        left, right = [self.socket(client) for client in self.clients]
        try:
            for socket in [left, right]:
                self.assertTrue((await socket.connect())[0])
                await self.packets(socket, {"welcome"})
            await self.hold(left)
            own = await self.packets(left, {"poke_state", "poke_hit"})
            peer = await self.packets(right, {"poke_state", "poke_hit"})
            self.assertEqual(own["poke_state"], peer["poke_state"])
            self.assertEqual(own["poke_hit"], peer["poke_hit"])
            await asyncio.sleep(.26)
            await self.hold(left)
            second = (await self.packets(right, {"poke_hit"}))["poke_hit"]
            self.assertNotEqual(second["id"], peer["poke_hit"]["id"])
            await self.hold(left, False)
            stopped = (await self.packets(right, {"poke_state"}))["poke_state"]
            self.assertFalse(stopped["active"])
        finally:
            await left.disconnect()
            await right.disconnect()
        self.assertEqual(await self.movement_count(), 0)

    async def test_disconnect_stops_the_peer_animation_and_removes_channel_registration(self):
        left, right = [self.socket(client) for client in self.clients]
        try:
            for socket in [left, right]:
                self.assertTrue((await socket.connect())[0])
                await self.packets(socket, {"welcome"})
            await self.hold(left)
            started = (await self.packets(right, {"poke_state"}))["poke_state"]
            await left.disconnect()
            stopped = (await self.packets(right, {"poke_state"}))["poke_state"]
            self.assertFalse(stopped["active"])
            self.assertNotIn(started["actorId"], consumers.room.channels)
        finally:
            if not left.future.done():
                await left.disconnect()
            await right.disconnect()

    async def test_expired_authentication_guard_stops_a_held_stream(self):
        left, right = [self.socket(client) for client in self.clients]
        try:
            for socket in [left, right]:
                self.assertTrue((await socket.connect())[0])
                await self.packets(socket, {"welcome"})
            await self.hold(left)
            started = (await self.packets(right, {"poke_state"}))["poke_state"]
            key = self.clients[0].session.session_key
            await database_sync_to_async(lambda: Session.objects.filter(session_key=key).delete())()
            await get_channel_layer().send(consumers.room.channels[started["actorId"]], {"type": "presence.check"})
            stopped = (await self.packets(right, {"poke_state"}))["poke_state"]
            self.assertFalse(stopped["active"])
        finally:
            await left.disconnect()
            await right.disconnect()
