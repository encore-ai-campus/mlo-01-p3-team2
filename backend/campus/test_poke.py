"""Pokes obey authoritative geometry, session checks, and transient room scope."""
import asyncio
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings

from accounts.models import Profile
from eventing.models import EventOutbox
from . import consumers, poke
from .motion import ControlError, MotionController, World, world


class PokeGeometryTests(SimpleTestCase):
    def setUp(self):
        self.data = {"id": "test", "width": 300, "height": 300, "privateRoom": False, "angle": 0, "tilt": 1,
                     "radius": 8, "objects": [], "colliders": [],
                     "rooms": [{"x": 0, "y": 0, "w": 300, "h": 300}]}
        self.world = World(self.data)
        self.pose = {"x": 150, "y": 150, "dir": "right"}

    def target(self, x, y, identity="target"):
        return {"id": identity, "x": x, "y": y}

    def test_eight_directions_only_hit_in_front(self):
        for direction, (x, y) in poke.VECTORS.items():
            with self.subTest(direction=direction):
                pose = {**self.pose, "dir": direction}
                targets = [self.target(150 - x * 32, 150 - y * 32, "behind"),
                           self.target(150 + x * 32, 150 + y * 32)]
                self.assertEqual(poke.find_target(pose, targets, self.world, {}), "target")

    def test_distance_sideways_and_coincident_targets_miss(self):
        for x, y in [(223, 150), (182, 187), (222, 160), (150, 150)]:
            with self.subTest(x=x, y=y):
                self.assertIsNone(poke.find_target(self.pose, [self.target(x, y)], self.world, {}))

    def test_extended_distance_and_width_hit(self):
        for x, y in [(214, 150), (210, 182)]:
            with self.subTest(x=x, y=y):
                self.assertEqual(poke.find_target(self.pose, [self.target(x, y)], self.world, {}), "target")

    def test_rotated_world_matches_screen_facing_for_all_eight_directions(self):
        angled = World({**self.data, "angle": math.pi / 4, "tilt": .58})
        for direction in poke.VECTORS:
            with self.subTest(direction=direction):
                dx, dy = poke.direction_vector(angled, direction)
                self.assertAlmostEqual(math.hypot(dx, dy), 1)
                target = self.target(150 + dx * 64, 150 + dy * 64)
                self.assertEqual(poke.find_target(self.pose, [target], angled, {}, direction), "target")
                beyond = self.target(150 + dx * 73, 150 + dy * 73)
                self.assertIsNone(poke.find_target(self.pose, [beyond], angled, {}, direction))

    def test_one_nearest_target_reacts(self):
        targets = [self.target(192, 150, "far"), self.target(179, 150, "near")]
        self.assertEqual(poke.find_target(self.pose, targets, self.world, {}), "near")

    def test_wall_blocks_a_poke(self):
        blocked = World({**self.data, "colliders": [{"x": 165, "y": 125, "w": 3, "h": 50, "pad": 0}]})
        self.assertIsNone(poke.find_target(self.pose, [self.target(190, 150)], blocked, {}))

    def test_seated_resident_can_react_in_each_subject(self):
        for subject in ["python", "sql"]:
            with self.subTest(subject=subject):
                pose = {"x": 154, "y": 239, "dir": "left"}
                self.assertTrue(world(subject).walkable(pose["x"], pose["y"]))
                self.assertEqual(poke.find_target(pose, poke.classroom_targets(subject), world(subject), {}),
                                 "resident-student-0-0-chair")


class PokeControlTests(SimpleTestCase):
    def setUp(self):
        self.room = consumers.CampusRoom()
        self.consumer = consumers.CampusConsumer()
        self.consumer.player_id = "self"
        self.consumer.controller = MotionController({"floor": "campus", "x": 130, "y": 100, "dir": "right"}, {})
        self.consumer.state = {"id": "self", **self.consumer.controller.pose}
        self.consumer.control_lock = asyncio.Lock()
        self.consumer.last_poke = -math.inf
        self.consumer.send_packet = AsyncMock()
        self.consumer.broadcast = AsyncMock()
        self.consumer.send_poke_to = AsyncMock()
        self.consumer.touch_activity = AsyncMock()
        self.consumer.receive_movement = AsyncMock()
        self.consumer.current_identity = AsyncMock(return_value={})
        self.consumer.session_expired = AsyncMock()
        self.consumer.policy_status = {}
        self.room.players = {"self": self.consumer.state.copy(),
                             "near": {"id": "near", "floor": "campus", "x": 130 + 32 / math.sqrt(2), "y": 100 - 32 / math.sqrt(2)}}
        self.room_patch = patch.object(consumers, "room", self.room)
        self.room_patch.start()
        self.addCleanup(self.room_patch.stop)
        self.arguments = {"context": "world", "floor": "campus"}

    async def test_control_broadcasts_without_a_position_write(self):
        original = self.consumer.controller.pose.copy()
        await self.consumer.receive_control({"requestId": "1", "action": "poke", "data": self.arguments})
        payload = self.consumer.send_poke_to.await_args.args[1]
        self.assertEqual((payload["actorId"], payload["targetId"], payload["dir"]), ("self", "near", "right"))
        self.assertEqual(self.consumer.controller.pose, original)
        self.consumer.receive_movement.assert_not_awaited()
        self.assertTrue(self.consumer.send_packet.await_args.args[0]["result"]["hit"])

    async def test_cooldown_rejects_a_second_request(self):
        await self.consumer.receive_poke(self.arguments)
        with self.assertRaises(ControlError):
            await self.consumer.receive_poke(self.arguments)
        self.assertEqual(self.consumer.send_poke_to.await_count, 1)

    async def test_last_diagonal_survives_releasing_keys(self):
        self.consumer.controller.input(['w', 'd'])
        self.consumer.controller.input([])
        await self.consumer.receive_poke(self.arguments)
        self.assertEqual(self.consumer.send_poke_to.await_args.args[1]['dir'], 'up-right')
        self.assertIn(self.consumer.controller.pose['dir'], {'up', 'down', 'left', 'right'})

    async def test_client_cannot_supply_coordinates_or_a_target(self):
        with self.assertRaises(ControlError):
            await self.consumer.receive_poke({**self.arguments, "x": 9999, "targetId": "near"})
        self.consumer.broadcast.assert_not_awaited()

    async def test_other_floor_and_private_occupants_are_excluded(self):
        self.room.players["near"]["floor"] = "rooftop"
        result = await self.consumer.receive_poke(self.arguments)
        self.assertFalse(result["hit"])
        self.consumer.last_poke = -math.inf
        self.room.players["near"]["floor"] = "campus"
        self.room.interiors.add("near")
        self.assertFalse((await self.consumer.receive_poke(self.arguments))["hit"])

    async def test_private_classroom_effect_is_only_sent_to_its_owner(self):
        self.consumer.controller.interior = {"subject": "python", "actor": {"x": 154, "y": 239, "dir": "left", "moving": False}}
        result = await self.consumer.receive_poke({"context": "classroom", "subject": "python"})
        self.assertTrue(result["hit"])
        self.consumer.broadcast.assert_not_awaited()
        payload = self.consumer.send_poke_to.await_args.args[1]
        self.assertEqual((payload["context"], payload["targetId"]), ("classroom", "resident-student-0-0-chair"))

    async def test_expired_session_is_rejected_before_broadcast(self):
        self.consumer.current_identity.return_value = None
        await self.consumer.receive_control({"requestId": "1", "action": "poke", "data": self.arguments})
        self.consumer.session_expired.assert_awaited_once()
        self.consumer.broadcast.assert_not_awaited()

    async def test_recipients_do_not_receive_other_floor_or_private_effects(self):
        packet = {"type": "poke", "floor": "rooftop"}
        await self.consumer.presence_packet({"sender": "near", "payload": packet})
        self.consumer.send_packet.assert_not_awaited()
        self.consumer.controller.interior = {"subject": "python"}
        await self.consumer.presence_packet({"sender": "near", "payload": {**packet, "floor": "campus"}})
        self.consumer.send_packet.assert_not_awaited()


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "testserver"], KAFKA_BOOTSTRAP_SERVERS="",
                   CAMPUS_RAFFLE_SCHEDULER_ENABLED=False)
class PokeSocketTests(TransactionTestCase):
    def setUp(self):
        consumers.room = consumers.CampusRoom()
        from raffle.models import Control
        Control.objects.get_or_create(pk=1)
        self.clients = []
        for index, (x, y) in enumerate([(130, 100), (130 + 32 / math.sqrt(2), 100 - 32 / math.sqrt(2))]):
            user = get_user_model().objects.create_user(username=f"poke-{index}")
            Profile.objects.create(user=user, nickname=f"찌르기 {index}", cohort="mlo-1", setup_complete=True,
                                   last_position={"floor": "campus", "x": x, "y": y, "dir": "right"})
            client = Client()
            client.force_login(user)
            self.clients.append(client)

    def socket(self, client=None):
        from config.asgi import application
        headers = [(b"origin", b"http://127.0.0.1"), (b"host", b"127.0.0.1")]
        if client:
            key = client.cookies[settings.SESSION_COOKIE_NAME].value
            headers.append((b"cookie", f"{settings.SESSION_COOKIE_NAME}={key}".encode()))
        return WebsocketCommunicator(application, "/ws/campus/?control=server", headers=headers)

    async def packets(self, socket, wanted):
        result = {}
        async def collect():
            while not wanted <= result.keys():
                packet = await socket.receive_json_from(timeout=2)
                result[packet["type"]] = packet
        await asyncio.wait_for(collect(), timeout=3)
        return result

    @database_sync_to_async
    def movement_count(self):
        return EventOutbox.objects.filter(event_type="movement_observed").count()

    async def test_two_authenticated_clients_share_the_same_effect_and_cooldown(self):
        left, right = [self.socket(client) for client in self.clients]
        try:
            self.assertTrue((await left.connect())[0])
            own = (await self.packets(left, {"welcome"}))["welcome"]
            self.assertTrue((await right.connect())[0])
            peer = (await self.packets(right, {"welcome"}))["welcome"]
            await left.send_json_to({"type": "control", "requestId": "poke-1", "action": "poke",
                                     "data": {"context": "world", "floor": "campus"}})
            accepted = await self.packets(left, {"poke", "control_result"})
            observed = (await self.packets(right, {"poke"}))["poke"]
            self.assertEqual(accepted["poke"], observed)
            self.assertEqual((observed["actorId"], observed["targetId"]), (own["selfId"], peer["selfId"]))
            self.assertTrue(accepted["control_result"]["result"]["hit"])
            await left.send_json_to({"type": "control", "requestId": "poke-2", "action": "poke",
                                     "data": {"context": "world", "floor": "campus"}})
            rejected = (await self.packets(left, {"control_result"}))["control_result"]
            self.assertIn("error", rejected)
        finally:
            await left.disconnect()
            await right.disconnect()
        self.assertEqual(await self.movement_count(), 0)

    async def test_anonymous_socket_cannot_connect(self):
        socket = self.socket()
        try:
            self.assertEqual(await socket.connect(), (False, 4401))
        finally:
            await socket.disconnect()

    async def test_diagonal_input_is_accepted_before_poke_and_kept_after_stop(self):
        socket = self.socket(self.clients[0])
        try:
            self.assertTrue((await socket.connect())[0])
            await self.packets(socket, {"welcome"})
            await socket.send_json_to({"type": "input", "keys": ["w", "d"]})
            await socket.send_json_to({"type": "input", "keys": []})
            await socket.send_json_to({"type": "control", "requestId": "diagonal", "action": "poke",
                                       "data": {"context": "world", "floor": "campus"}})
            accepted = await self.packets(socket, {"poke", "control_result"})
            self.assertEqual(accepted["poke"]["dir"], "up-right")
            self.assertNotIn("error", accepted["control_result"])
        finally:
            await socket.disconnect()


class PokeFacingTests(SimpleTestCase):
    def setUp(self):
        self.controller = MotionController({"floor": "campus", "x": 130, "y": 100, "dir": "right"}, {})

    def test_all_keyboard_pairs_and_aliases_keep_a_separate_eight_direction_facing(self):
        for keys, direction in [(['w', 'a'], 'up-left'), (['w', 'd'], 'up-right'),
                                (['s', 'a'], 'down-left'), (['s', 'd'], 'down-right'),
                                (['arrowup', 'arrowright'], 'up-right'),
                                (['w', 'arrowup', 'd', 'arrowright'], 'up-right')]:
            with self.subTest(keys=keys):
                self.controller.input(keys)
                self.controller.input([])
                self.assertEqual(self.controller.poke_direction, direction)
                self.assertIn(self.controller.pose['dir'], {'up', 'down', 'left', 'right'})

    def test_private_facing_is_separate_from_main_map_and_snapshot_coordinates(self):
        self.controller.interior = {'subject': 'python', 'actor': {'x': 154, 'y': 239, 'dir': 'left', 'moving': False}}
        self.controller.input(['w', 'a'])
        self.controller.input([])
        self.assertEqual(self.controller.interior['poke_direction'], 'up-left')
        self.assertEqual(self.controller.poke_direction, 'right')
        state = self.controller.snapshot({})
        self.assertEqual(state['interior']['actor']['dir'], 'left')
        self.assertNotIn('poke_direction', state['main'])
        self.assertNotIn('poke_direction', state['interior']['actor'])

    def test_releasing_a_diagonal_in_two_frames_keeps_its_direction(self):
        self.controller.input(['s', 'd'], now=10)
        self.controller.input(['d'], now=10.025)
        self.controller.input([], now=10.045)
        self.assertEqual(self.controller.poke_direction, 'down-right')

    def test_holding_a_single_direction_after_diagonal_turns_normally(self):
        self.controller.input(['w', 'd'], now=10)
        self.controller.input(['d'], now=10.025)
        self.controller.input(['d'], now=10.1)
        self.assertEqual(self.controller.poke_direction, 'right')
