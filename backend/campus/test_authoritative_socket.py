import asyncio
from unittest.mock import patch

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings

from accounts.models import Profile
from eventing.models import EventOutbox
from . import consumers
from .positions import DEFAULT_POSITION


@override_settings(CAMPUS_TEST_LEGACY_MOVEMENT=False, KAFKA_BOOTSTRAP_SERVERS='')
class AuthoritativeSocketTests(TransactionTestCase):
    def setUp(self):
        from raffle.models import Control
        Control.objects.get_or_create(pk=1)
        self.user = get_user_model().objects.create_user(username='server-input')
        Profile.objects.create(user=self.user, nickname='입력 검증', cohort='mlo-1', setup_complete=True)
        client = Client()
        client.force_login(self.user)
        self.cookie = f'{settings.SESSION_COOKIE_NAME}={client.cookies[settings.SESSION_COOKIE_NAME].value}'
        self.room = consumers.CampusRoom()
        replacement = patch.object(consumers, 'room', self.room)
        replacement.start()
        self.addCleanup(replacement.stop)

    def socket(self):
        from config.asgi import application
        return WebsocketCommunicator(application, '/ws/campus/', headers=[
            (b'origin', b'http://127.0.0.1'), (b'host', b'127.0.0.1'), (b'cookie', self.cookie.encode())])

    async def packet(self, socket, kind):
        for _ in range(30):
            packet = await socket.receive_json_from(timeout=2)
            if packet['type'] == kind:
                return packet
        self.fail(f'{kind} was not received')

    @database_sync_to_async
    def stored(self):
        return (Profile.objects.get(user_id=self.user.pk).last_position,
                list(EventOutbox.objects.filter(event_type='movement_observed').values_list('raw_data', flat=True)))

    async def test_production_socket_rejects_coordinates_and_uses_server_default_spawn(self):
        socket = self.socket()
        try:
            self.assertTrue((await socket.connect())[0])
            welcome = await self.packet(socket, 'welcome')
            self.assertTrue(welcome['serverControl'])
            await self.packet(socket, 'control_state')
            await socket.send_json_to({'type': 'move', 'floor': 'rooftop', 'x': 100, 'y': 100, 'dir': 'left', 'moving': True})
            await self.packet(socket, 'control_error')
            self.assertEqual(self.room.players[welcome['selfId']]['floor'], 'campus')
            self.assertEqual(self.room.players[welcome['selfId']]['x'], DEFAULT_POSITION['x'])
        finally:
            await socket.disconnect()
        self.assertEqual((await self.stored())[1], [])

    async def test_keyboard_moves_on_the_server_and_disconnect_flushes_one_latest_outbox(self):
        socket = self.socket()
        try:
            self.assertTrue((await socket.connect())[0])
            await self.packet(socket, 'welcome')
            await self.packet(socket, 'control_state')
            await socket.send_json_to({'type': 'input', 'keys': ['w']})
            await asyncio.sleep(.15)
            await socket.send_json_to({'type': 'input', 'keys': []})
            await socket.send_json_to({'type': 'ping'})
            await self.packet(socket, 'pong')
        finally:
            await socket.disconnect()
        position, events = await self.stored()
        self.assertNotEqual((position['x'], position['y']), (DEFAULT_POSITION['x'], DEFAULT_POSITION['y']))
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]['x'], events[0]['y']), (position['x'], position['y']))

    async def test_invalid_keys_are_rejected_without_disconnect_or_movement(self):
        socket = self.socket()
        try:
            self.assertTrue((await socket.connect())[0])
            await self.packet(socket, 'welcome')
            await socket.send_json_to({'type': 'input', 'keys': ['teleport']})
            await self.packet(socket, 'control_error')
            await socket.send_json_to({'type': 'ping'})
            await self.packet(socket, 'pong')
        finally:
            await socket.disconnect()
        self.assertEqual((await self.stored())[1], [])

    async def test_transfer_approval_returns_a_user_bound_ad_token_before_moving(self):
        from ad_bridge.placements import transfer_identity

        await database_sync_to_async(Profile.objects.filter(user_id=self.user.pk).update)(
            last_position={"floor": "campus", "x": 2280, "y": 912, "dir": "down"})
        socket = self.socket()
        try:
            self.assertTrue((await socket.connect(timeout=5))[0])
            await self.packet(socket, "welcome")
            await socket.send_json_to({"type": "control", "requestId": "offer", "action": "prepare_transfer",
                                       "data": {"objectId": "campus-roof-stairs"}})
            await self.packet(socket, "control_result")
            await socket.send_json_to({"type": "control", "requestId": "approve", "action": "begin_transfer",
                                       "data": {"floor": "rooftop"}})
            result = (await self.packet(socket, "control_result"))["result"]
            self.assertEqual(transfer_identity(result["ads_token"], self.user.pk), result["transfer_id"])
            self.assertEqual(next(iter(self.room.players.values()))["floor"], "campus")
        finally:
            await socket.disconnect()
