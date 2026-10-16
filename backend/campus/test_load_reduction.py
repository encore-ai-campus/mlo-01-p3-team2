"""부하 줄이기(계획 docs/metaverse-optimization-plan.md).

- 1a·1b: 가만히 있는 사람은 메시지를 만들지 않는다. 움직임은 지금처럼 전달한다: 이동 중 위치는 0.1초 간격,
  정지·방향 전환도 다음 묶음에, **마지막 정지 위치(`moving=false`)는 반드시**.
- 1d: 여러 사람의 위치는 0.1초마다 한 메시지(`moves`)로 묶어 보낸다.
- 1e: 가만히 있는 사람은 30Hz 이동 틱을 돌리지 않는다(0.5초에 한 번만 살핀다). 입력이 오면 바로 깨어난다.
- 2a·2b: 메시지마다 DB 스레드를 왕복하지 않고, 큐가 가득 차도 세션 감시 작업이 끝나지 않는다.
- 4f: 소켓의 DB 호출은 연결 하나를 이어 쓴다(호출마다 새 연결·TLS 핸드셰이크를 하지 않는다).
"""
import asyncio
from unittest.mock import AsyncMock, patch

from channels.exceptions import ChannelFull
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings

from accounts.models import Profile
from . import consumers


@override_settings(CAMPUS_TEST_LEGACY_MOVEMENT=False, KAFKA_BOOTSTRAP_SERVERS='')
class IdleTrafficTests(TransactionTestCase):
    def setUp(self):
        from raffle.models import Control
        Control.objects.get_or_create(pk=1)
        self.cookies = [self.login(name) for name in ('idle-a', 'idle-b', 'idle-c')]
        self.sockets = []
        self.room = consumers.CampusRoom()
        replacement = patch.object(consumers, 'room', self.room)
        replacement.start()
        self.addCleanup(replacement.stop)

    def login(self, name):
        user = get_user_model().objects.create_user(username=name)
        Profile.objects.create(user=user, nickname=name, cohort='mlo-1', setup_complete=True)
        client = Client()
        client.force_login(user)
        return f'{settings.SESSION_COOKIE_NAME}={client.cookies[settings.SESSION_COOKIE_NAME].value}'.encode()

    async def connect(self, cookie):
        from config.asgi import application
        socket = WebsocketCommunicator(application, '/ws/campus/', headers=[
            (b'origin', b'http://127.0.0.1'), (b'host', b'127.0.0.1'), (b'cookie', cookie)])
        self.assertTrue((await socket.connect(timeout=5))[0])
        self.sockets.append(socket)
        while (packet := await socket.receive_json_from(timeout=2))['type'] != 'welcome':
            pass
        socket.player_id = packet['selfId']
        return socket

    async def drain(self, socket, seconds=0.0):
        """`seconds` 동안 쌓인 메시지(시간 초과로 앱을 끊지 않게 비어 있는지 먼저 본다)."""
        await asyncio.sleep(seconds)
        packets = []
        while not await socket.receive_nothing(timeout=0):
            packets.append(await socket.receive_json_from())
        return packets

    async def two_settled(self):
        a, b = await self.connect(self.cookies[0]), await self.connect(self.cookies[1])
        await self.drain(a, .3)
        await self.drain(b)
        return a, b

    @staticmethod
    def kinds(packets, kind):
        return [p for p in packets if p['type'] == kind]

    @staticmethod
    def positions_of(packets, socket):
        """묶음(`moves`)에 실려 온 그 사람의 상태들."""
        return [player for p in packets if p['type'] == 'moves' for player in p['players'] if player['id'] == socket.player_id]

    async def disconnect_all(self):
        for socket in self.sockets:
            await socket.disconnect()

    async def test_people_standing_still_send_no_state_and_no_position(self):
        try:
            await self.check_standing_still()
        finally:
            await self.disconnect_all()

    async def test_walking_is_relayed_and_the_final_stop_always_arrives(self):
        try:
            await self.check_walking()
        finally:
            await self.disconnect_all()

    async def check_standing_still(self):
        a, b = await self.two_settled()
        idle_a, idle_b = await self.drain(a, .6), await self.drain(b)
        self.assertEqual(self.kinds(idle_a, 'control_state'), [])
        self.assertEqual(self.kinds(idle_b, 'moves') + self.kinds(idle_b, 'move'), [])
        self.assertEqual(self.kinds(idle_b, 'control_state'), [])

    async def check_walking(self):
        a, b = await self.two_settled()
        await a.send_json_to({'type': 'input', 'keys': ['w']})
        await asyncio.sleep(.35)
        await a.send_json_to({'type': 'input', 'keys': []})
        walk_a, walk_b = await self.drain(a, .5), await self.drain(b)
        moves = self.positions_of(walk_b, a)
        self.assertGreaterEqual(len([m for m in moves if m['moving']]), 2)  # 이동 중 0.1초 간격
        self.assertFalse(moves[-1]['moving'])  # 마지막은 정지
        states = self.kinds(walk_a, 'control_state')
        self.assertGreaterEqual(len(states), 5)
        self.assertFalse(states[-1]['state']['main']['moving'])
        # 정지한 뒤에는 다시 조용하다
        quiet_a, quiet_b = await self.drain(a, .4), await self.drain(b)
        self.assertEqual(self.kinds(quiet_a, 'control_state'), [])
        self.assertEqual(self.kinds(quiet_b, 'moves'), [])

    async def test_relayed_messages_do_not_hop_to_the_database_thread(self):
        try:
            with patch('channels.consumer.aclose_old_connections', new=AsyncMock()) as hop:
                a, b = await self.two_settled()
                await a.send_json_to({'type': 'input', 'keys': ['w']})
                await asyncio.sleep(.3)
                await a.send_json_to({'type': 'input', 'keys': []})
                self.assertTrue(self.positions_of(await self.drain(b, .3), a))
            self.assertEqual(hop.await_count, 0)  # DB 는 database_sync_to_async 가 앞뒤로 정리한다
        finally:
            await self.disconnect_all()

    async def test_a_full_queue_does_not_end_the_session_guard(self):
        consumer, sent = consumers.CampusConsumer(), []
        consumer.channel_name = 'campus.test!guard'

        async def send(channel, message):
            sent.append(message)
            if len(sent) == 1:
                raise ChannelFull(channel)
            if len(sent) == 3:
                raise asyncio.CancelledError

        consumer.channel_layer = type('Layer', (), {'send': staticmethod(send)})()
        with patch.object(consumers.CampusConsumer, 'session_check_interval', .01), \
                patch.object(consumers.CampusConsumer, 'position_interval', .01):
            with self.assertRaises(asyncio.CancelledError):
                await consumer.check_session_loop()
        self.assertEqual(len(sent), 3)  # 가득 찬 한 번은 건너뛰고 다음 주기에 다시 보낸다

    async def test_several_walkers_arrive_together_once_per_tenth_of_a_second(self):
        try:
            a, b = await self.two_settled()
            c = await self.connect(self.cookies[2])
            await self.drain(c, .3)
            await self.drain(a)
            await self.drain(b)
            await a.send_json_to({'type': 'input', 'keys': ['w']})
            await b.send_json_to({'type': 'input', 'keys': ['s']})
            await asyncio.sleep(.5)
            seen = await self.drain(c)
            batches = self.kinds(seen, 'moves')
            self.assertLessEqual(len(batches), 7)  # 0.1초에 하나(걷는 사람 수와 무관)
            self.assertTrue(any({a.player_id, b.player_id} <= {p['id'] for p in batch['players']} for batch in batches))
            self.assertEqual(self.kinds(seen, 'move'), [])
        finally:
            await self.disconnect_all()

    async def test_socket_database_calls_reuse_one_connection(self):
        from django.db import connections
        from django.db.backends.signals import connection_created
        from . import socket_db

        def probe():
            connections['default'].ensure_connection()
            return connections['default'].vendor

        created = []

        def count(sender, connection, **kwargs):
            created.append(connection.alias)

        connection_created.connect(count)
        try:
            for _ in range(10):
                await socket_db.run(probe)
        finally:
            connection_created.disconnect(count)
        self.assertLessEqual(len(created), 1)

    async def test_a_resting_player_barely_ticks_and_wakes_on_input(self):
        try:
            a, b = await self.two_settled()
            controller, ticks = self.room.controllers[a.player_id], []
            original = controller.tick

            def counting(*args, **kwargs):
                ticks.append(1)
                return original(*args, **kwargs)

            controller.tick = counting
            await asyncio.sleep(1.0)
            self.assertLessEqual(len(ticks), 4)  # 30Hz 면 30번
            await self.drain(a)
            await a.send_json_to({'type': 'input', 'keys': ['w']})
            states = self.kinds(await self.drain(a, .15), 'control_state')
            self.assertTrue(any(s['state']['main']['moving'] for s in states))  # 깨어나 바로 움직인다
        finally:
            await self.disconnect_all()
