from config.testing import PresentationTestCase
import asyncio
from datetime import timedelta
import json
import re
from unittest.mock import patch

from channels.db import database_sync_to_async
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Profile
from accounts.forms import NicknameForm
from . import consumers
from .positions import DEFAULT_POSITION, get_position, save_position, validate_position
from . import tests as socket_tests


class PositionStorageTests(PresentationTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="position-user", password="Location!4820")
        self.profile = Profile.objects.create(user=self.user, nickname="복원", avatar="female-1")
        self.position = {"floor": "rooftop", "x": 2310.25, "y": 1510.875, "dir": "left"}

    def test_missing_or_invalid_saved_position_defaults_to_entrance(self):
        self.assertEqual(get_position(self.user), DEFAULT_POSITION)
        for changes in [{"x": True}, {"y": float("nan")}, {"x": 10 ** 350},
                        {"y": 1801}, {"floor": "basement"}, {"floor": []}, {"dir": {}}]:
            self.assertIsNone(validate_position({**self.position, **changes}))
        self.profile.last_position = {**self.position, "floor": "old-roof"}
        self.profile.save()
        self.assertEqual(get_position(get_user_model().objects.get(pk=self.user.pk)), DEFAULT_POSITION)

    def test_latest_movement_wins_even_when_an_old_tab_saves_later(self):
        old = timezone.now() - timedelta(seconds=1)
        self.assertTrue(save_position(self.user, self.position))
        self.assertFalse(save_position(self.user, DEFAULT_POSITION, old))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.position)
        self.assertEqual(self.profile.avatar, "female-1")
        self.assertEqual(self.profile.nickname, "복원")

    def test_exit_position_resumes_inside_entrance(self):
        save_position(self.user, {"floor": "campus", "x": 1998.75, "y": 980, "dir": "down"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, DEFAULT_POSITION)

    @override_settings(CAMPUS_TEST_LEGACY_MOVEMENT=False)
    def test_logout_uses_server_snapshot_and_ignores_posted_coordinates(self):
        self.client.post("/accounts/login/", {"username": self.user.username, "password": "Location!4820"})
        save_position(self.user, self.position)
        response = self.client.post("/accounts/logout/", {"last_position": json.dumps(DEFAULT_POSITION)})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.position)
        self.assertEqual(self.client.post("/accounts/login/", {"username": self.user.username, "password": "Location!4820"}).status_code, 302)
        html = self.client.get("/").content.decode()
        config = json.loads(re.search(r'<script id="campusPresenceConfig" type="application/json">(.*?)</script>', html).group(1))
        self.assertEqual(config["position"], self.position)
        self.assertNotIn('name="last_position"', html)

    def test_invalid_logout_payload_preserves_saved_position_but_still_logs_out(self):
        save_position(self.user, self.position)
        for raw in ["not-json", "[]", json.dumps({**self.position, "x": True})]:
            self.client.post("/accounts/login/", {"username": self.user.username, "password": "Location!4820"})
            self.assertEqual(self.client.post("/accounts/logout/", {"last_position": raw}).status_code, 302)
            self.assertNotIn(SESSION_KEY, self.client.session)
            self.profile.refresh_from_db()
            self.assertEqual(self.profile.last_position, self.position)

    def test_logout_save_still_requires_csrf_and_cannot_change_another_account(self):
        other = get_user_model().objects.create_user(username="other-position")
        other_profile = Profile.objects.create(user=other, nickname="다른 조원")
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/accounts/logout/", {"last_position": json.dumps(self.position)}).status_code, 403)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.last_position)
        self.client.force_login(self.user)
        self.client.post("/accounts/logout/", {"last_position": json.dumps({**self.position, "user_id": other.pk})})
        other_profile.refresh_from_db()
        self.assertIsNone(other_profile.last_position)

    def test_nickname_change_preserves_saved_position_and_fixed_avatar(self):
        save_position(self.user, self.position)
        self.client.force_login(self.user)
        self.client.post("/accounts/nickname/", {"nickname": "새 닉네임"})
        self.assertEqual(self.client.post("/accounts/avatar/", {"avatar": "male-2"}).status_code, 404)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.position)
        self.assertEqual(self.profile.avatar, "female-1")

    def test_nickname_form_does_not_overwrite_a_concurrent_checkpoint(self):
        original = NicknameForm.is_valid

        def checkpoint_during_validation(form):
            valid = original(form)
            save_position(self.user, self.position)
            return valid

        self.client.force_login(self.user)
        with patch.object(NicknameForm, "is_valid", checkpoint_during_validation):
            response = self.client.post("/accounts/nickname/", {"nickname": "새 닉네임"})
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.nickname, "새 닉네임")
        self.assertEqual(self.profile.last_position, self.position)


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"], DEBUG=False)
class PositionSocketTests(TransactionTestCase):
    setUp = socket_tests.CampusSocketTests.setUp
    socket = socket_tests.CampusSocketTests.socket
    connections = socket_tests.CampusSocketTests.connections
    welcome_pair = socket_tests.CampusSocketTests.welcome_pair
    movement = socket_tests.CampusSocketTests.movement

    async def snapshot(self):
        return await database_sync_to_async(lambda: Profile.objects.get(user=self.alice).last_position)()

    async def test_last_frame_bypasses_throttle_and_survives_a_fresh_room(self):
        async with self.connections(self.a) as (a,):
            await a.receive_json_from()
            await a.send_json_to(self.movement())
            await a.send_json_to(self.movement(type="leave", x=1250.875, y=443.625, moving=False))
            self.assertEqual(await a.receive_output(), {"type": "websocket.close", "code": 1000})
        self.assertEqual(await self.snapshot(), {"floor": "campus", "x": 1250.875, "y": 443.625, "dir": "left"})
        consumers.room = consumers.CampusRoom()
        async with self.connections(self.a, self.b) as (a, b):
            first, second = await self.welcome_pair(a, b)
            self.assertEqual(first["players"][0]["x"], 1250.875)
            bob = next(p for p in second["players"] if p["id"] == second["selfId"])
            self.assertEqual((bob["x"], bob["y"]), (DEFAULT_POSITION["x"], DEFAULT_POSITION["y"]))

    async def test_rooftop_switch_saves_immediately_and_restores_floor(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            await a.send_json_to(self.movement(floor="rooftop", x=2300.75, y=1700.5))
            await b.receive_json_from()
            await a.send_json_to({"type": "ping"})
            await a.receive_json_from()
            self.assertEqual((await self.snapshot())["floor"], "rooftop")
        async with self.connections(self.a) as (a,):
            own = (await a.receive_json_from())["players"][0]
            self.assertEqual((own["floor"], own["x"], own["y"]), ("rooftop", 2300.75, 1700.5))

    async def test_disconnect_saves_latest_accepted_movement(self):
        async with self.connections(self.a) as (a,):
            await a.receive_json_from()
            await a.send_json_to(self.movement(x=1800.875))
            await a.send_json_to({"type": "ping"})
            await a.receive_json_from()
        self.assertEqual((await self.snapshot())["x"], 1800.875)

    async def test_idle_checkpoint_saves_without_closing_the_socket(self):
        with patch.object(consumers.CampusConsumer, "position_interval", 0.05):
            async with self.connections(self.a) as (a,):
                await a.receive_json_from()
                await a.send_json_to(self.movement(x=1850.125))
                for _ in range(20):
                    if await self.snapshot():
                        break
                    await asyncio.sleep(0.02)
                self.assertEqual((await self.snapshot())["x"], 1850.125)
                await a.send_json_to({"type": "ping"})
                self.assertEqual((await a.receive_json_from())["type"], "pong")

    async def test_stale_tab_disconnect_cannot_overwrite_newer_rooftop_position(self):
        async with self.connections(self.a, self.a) as (old, new):
            await self.welcome_pair(old, new)
            await old.send_json_to(self.movement(x=1800.125))
            await new.receive_json_from()
            await new.send_json_to(self.movement(floor="rooftop", x=2200.5, y=1500.75))
            await old.receive_json_from()
            await old.disconnect()
            self.assertEqual((await new.receive_json_from())["type"], "leave")
            self.assertEqual((await self.snapshot())["floor"], "rooftop")

    async def test_revoked_socket_cannot_overwrite_the_logout_snapshot(self):
        async with self.connections(self.a) as (a,):
            await a.receive_json_from()
            await a.send_json_to(self.movement(x=1850.5))
            await a.send_json_to({"type": "ping"})
            await a.receive_json_from()
            position = {"floor": "rooftop", "x": 2300.75, "y": 1700.5, "dir": "up"}
            await database_sync_to_async(self.a.post)("/accounts/logout/", {"last_position": json.dumps(position)})
            await a.send_json_to(self.movement(type="leave", x=1900.25))
            self.assertEqual((await a.receive_output())["code"], 1000)
        self.assertEqual(await self.snapshot(), position)
