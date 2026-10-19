from datetime import timedelta
from unittest.mock import patch

from channels.db import database_sync_to_async
from django.contrib.sessions.models import Session
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Profile
from accounts.session_policy import ACTIVITY, check_session
from . import consumers
from . import tests as socket_tests


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"], DEBUG=False,
                   CAMPUS_LOGIN_MAX_AGE_SECONDS=60, CAMPUS_LOGIN_IDLE_TIMEOUT_SECONDS=30,
                   CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS=0)
class SessionSocketTests(TransactionTestCase):
    setUp = socket_tests.CampusSocketTests.setUp
    socket = socket_tests.CampusSocketTests.socket
    connections = socket_tests.CampusSocketTests.connections
    welcome_pair = socket_tests.CampusSocketTests.welcome_pair
    movement = socket_tests.CampusSocketTests.movement

    async def test_socket_pings_do_not_extend_idle_and_expiry_closes_the_socket(self):
        now = timezone.now()
        key = self.a.cookies["campus_sessionid"].value
        with patch("accounts.session_policy.timezone.now", return_value=now) as clock:
            async with self.connections(self.a) as (ws,):
                welcome = await ws.receive_json_from()
                self.assertTrue(welcome["session"]["authenticated"])
                clock.return_value = now + timedelta(seconds=20)
                await ws.send_json_to({"type": "ping"})
                self.assertEqual((await ws.receive_json_from())["type"], "pong")
                data = await database_sync_to_async(lambda: Session.objects.get(pk=key).get_decoded())()
                self.assertEqual(data[ACTIVITY], now.timestamp())
                clock.return_value = now + timedelta(seconds=30)
                await ws.send_json_to({"type": "ping"})
                self.assertEqual(await ws.receive_json_from(), {"type": "session_expired", "reason": "idle"})
                self.assertEqual(await ws.receive_output(), {"type": "websocket.close", "code": 4401})
                self.assertFalse(await database_sync_to_async(Session.objects.filter(pk=key).exists)())

    async def test_expiry_in_http_saves_latest_position_and_closes_all_session_tabs(self):
        now = timezone.now()
        key = self.a.cookies["campus_sessionid"].value
        with patch("accounts.session_policy.timezone.now", return_value=now) as clock:
            async with self.connections(self.a, self.a, self.b) as (old, new, observer):
                await old.receive_json_from()  # welcome
                await new.receive_json_from()
                await observer.receive_json_from()
                self.assertEqual((await old.receive_output())["code"],4409)
                await new.receive_json_from()
                clock.return_value = now + timedelta(seconds=1)
                await new.send_json_to(self.movement(x=1700.25))
                await observer.receive_json_from()
                await new.send_json_to({"type": "ping"})
                await new.receive_json_from()
                clock.return_value = now + timedelta(seconds=2)
                await new.send_json_to(self.movement(floor="rooftop", x=2200.5, y=1510.75))
                await observer.receive_json_from()
                await new.send_json_to({"type": "ping"})
                await new.receive_json_from()
                clock.return_value = now + timedelta(seconds=32)
                state = await database_sync_to_async(check_session)(key)
                self.assertEqual(state["reason"], "idle")
                for ws in (new,):
                    self.assertEqual((await ws.receive_json_from())["type"], "session_expired")
                    self.assertEqual((await ws.receive_output())["code"], 4401)
                for _ in range(1):
                    self.assertEqual((await observer.receive_json_from())["type"], "leave")
                position = await database_sync_to_async(lambda: Profile.objects.get(user=self.alice).last_position)()
                self.assertEqual(position, {"floor": "rooftop", "x": 2200.5, "y": 1510.75, "dir": "left"})
                self.assertFalse(await database_sync_to_async(Session.objects.filter(pk=key).exists)())

    async def test_continuous_movement_cannot_extend_maximum_login_lifetime(self):
        now = timezone.now()
        key = self.a.cookies["campus_sessionid"].value
        with patch("accounts.session_policy.timezone.now", return_value=now) as clock:
            async with self.connections(self.a) as (ws,):
                await ws.receive_json_from()
                for elapsed, floor in ((20, "rooftop"), (40, "campus")):
                    clock.return_value = now + timedelta(seconds=elapsed)
                    await ws.send_json_to(self.movement(floor=floor, x=1700 + elapsed, y=500))
                    await ws.send_json_to({"type": "ping"})
                    self.assertEqual((await ws.receive_json_from())["type"], "pong")
                    data = await database_sync_to_async(lambda: Session.objects.get(pk=key).get_decoded())()
                    self.assertEqual(data[ACTIVITY], clock.return_value.timestamp())
                clock.return_value = now + timedelta(seconds=60)
                await ws.send_json_to(self.movement(floor="rooftop", x=1900, y=500))
                self.assertEqual(await ws.receive_json_from(), {"type": "session_expired", "reason": "maximum"})
                self.assertEqual((await ws.receive_output())["code"], 4401)
                position = await database_sync_to_async(lambda: Profile.objects.get(user=self.alice).last_position)()
                self.assertEqual(position["x"], 1740)

    async def test_a_server_close_leaves_its_code_and_policy_reason(self):
        """재로그인의 원인을 운영 로그로 가린다(계획 0c): 서버가 4401 로 끊으면 세션 정책의 사유가 한 줄 남는다."""
        now = timezone.now()
        with patch("accounts.session_policy.timezone.now", return_value=now) as clock, \
                self.assertLogs("campus.consumers", "WARNING") as logs:
            async with self.connections(self.a) as (ws,):
                await ws.receive_json_from()
                clock.return_value = now + timedelta(seconds=30)
                await ws.send_json_to({"type": "ping"})
                self.assertEqual((await ws.receive_json_from())["type"], "session_expired")
                self.assertEqual((await ws.receive_output())["code"], 4401)
        self.assertTrue(any("closed by server code=4401 policy=idle" in line for line in logs.output), logs.output)

    async def test_server_guard_expires_without_client_logout_or_activity_requests(self):
        now = timezone.now()
        with patch("accounts.session_policy.timezone.now", return_value=now) as clock, \
                patch.object(consumers.CampusConsumer, "session_check_interval", 0.02):
            async with self.connections(self.a) as (ws,):
                await ws.receive_json_from()
                clock.return_value = now + timedelta(seconds=30)
                self.assertEqual(await ws.receive_json_from(timeout=2), {"type": "session_expired", "reason": "idle"})
                self.assertEqual((await ws.receive_output())["code"], 4401)
