import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Profile
from accounts.session_policy import ACTIVITY, STARTED
from eventing.models import ChatMessage, EventOutbox, PlatformSession
from config.asgi import application
from . import consumers


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"], DEBUG=False)
class CampusSocketTests(TransactionTestCase):
    def setUp(self):
        consumers.room = consumers.CampusRoom()
        from eventing.catalog import FLOORS, floor_uuid
        from eventing.models import MapFloor
        # TransactionTestCase flushes migration data between socket tests.
        for code, name in FLOORS:
            MapFloor.objects.get_or_create(floor_uuid=floor_uuid(code), defaults={"code": code, "name": name})
        from raffle.models import Control
        Control.objects.get_or_create(pk=1)
        self.alice = get_user_model().objects.create_user(username="alice", password="Test!River4820")
        self.bob = get_user_model().objects.create_user(username="bob", password="Test!River4820")
        Profile.objects.create(user=self.alice, nickname="조원 하나", avatar="female-2")
        Profile.objects.create(user=self.bob, nickname="조원 둘", avatar="male-2")
        self.a, self.b = Client(), Client()
        self.a.force_login(self.alice)
        self.b.force_login(self.bob)

    def socket(self, client=None, origin="http://127.0.0.1"):
        headers = [(b"origin", origin.encode()), (b"host", b"127.0.0.1")]
        if client:
            cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
            headers.append((b"cookie", f"{settings.SESSION_COOKIE_NAME}={cookie}".encode()))
        return WebsocketCommunicator(application, "/ws/campus/", headers=headers)

    @asynccontextmanager
    async def connections(self, *clients):
        sockets = []
        try:
            for client in clients:
                ws = self.socket(client)
                sockets.append(ws)
                connected, _ = await ws.connect()
                self.assertTrue(connected)
            yield sockets
        finally:
            for ws in reversed(sockets):
                await ws.disconnect()
        self.assertFalse(consumers.room.players)

    async def welcome_pair(self, a, b):
        first = await a.receive_json_from()
        second = await b.receive_json_from()
        join = await a.receive_json_from()
        self.assertEqual(join["type"], "join")
        return first, second

    def movement(self, **changes):
        return {"type": "move", "x": 1250.125, "y": 442.875,
                "dir": "left", "color": "#4e9b91", "moving": True, **changes}

    async def test_anonymous_and_foreign_origin_connections_are_rejected(self):
        for client, origin in [(None, "http://127.0.0.1"), (self.a, "https://untrusted.example")]:
            ws = self.socket(client, origin)
            try:
                connected, _ = await ws.connect()
                self.assertFalse(connected)
                self.assertFalse(consumers.room.players)
            finally:
                await ws.disconnect()

    async def test_incomplete_profile_cannot_join_presence_until_setup_is_finished(self):
        await database_sync_to_async(Profile.objects.filter(user=self.alice).update)(cohort="mlo-1", setup_complete=False)
        ws = self.socket(self.a)
        try:
            connected, code = await ws.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4403)
            self.assertFalse(consumers.room.players)
        finally:
            await ws.disconnect()

    async def test_join_snapshot_and_fractional_movement_use_server_identity(self):
        async with self.connections(self.a, self.b) as (a, b):
            first, second = await self.welcome_pair(a, b)
            self.assertEqual(len(first["players"]), 1)
            self.assertEqual(len(second["players"]), 2)
            self.assertEqual({p["nickname"] for p in second["players"]}, {"조원 하나", "조원 둘"})
            self.assertEqual(first["players"][0]["avatar"], "female-2")
            self.assertEqual({p["avatar"] for p in second["players"]}, {"female-2", "male-2"})
            await a.send_json_to(self.movement(id=second["selfId"], nickname="사칭한 이름", avatar="male-1"))
            message = await b.receive_json_from()
            self.assertEqual(message["type"], "move")
            self.assertEqual(message["player"]["id"], first["selfId"])
            self.assertEqual(message["player"]["nickname"], "조원 하나")
            self.assertEqual(message["player"]["avatar"], "female-2")
            self.assertEqual(message["player"]["x"], 1250.125)
            self.assertEqual(message["player"]["y"], 442.875)
            self.assertEqual(message["player"]["color"], "#4e9b91")
            self.assertTrue(await a.receive_nothing())

    async def test_invalid_positions_and_fields_do_not_broadcast_or_crash(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            for changes in [{"x": -1}, {"y": 10000}, {"x": float("nan")}, {"x": 10 ** 350},
                            {"x": True}, {"dir": []}, {"color": {}}, {"moving": "yes"}]:
                await a.send_json_to(self.movement(**changes))
            self.assertTrue(await b.receive_nothing())
            await a.send_json_to(self.movement())
            self.assertEqual((await b.receive_json_from())["type"], "move")

    async def test_stopping_and_room_teleport_are_broadcast(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            await a.send_json_to(self.movement())
            await b.receive_json_from()
            await asyncio.sleep(0.05)
            await a.send_json_to(self.movement(x=365.25, y=380.5, moving=False))
            peer = (await b.receive_json_from())["player"]
            self.assertFalse(peer["moving"])
            self.assertEqual((peer["x"], peer["y"]), (365.25, 380.5))

    async def test_expanded_world_positions_and_boundary_validation(self):
        async with self.connections(self.a, self.b) as (a, b):
            first, _ = await self.welcome_pair(a, b)
            own = next(p for p in first["players"] if p["id"] == first["selfId"])
            self.assertEqual((own["x"], own["y"]), (1998.75, 910.5))
            await a.send_json_to(self.movement(x=2300.25, y=1100.5))
            peer = (await b.receive_json_from())["player"]
            self.assertEqual((peer["x"], peer["y"]), (2300.25, 1100.5))
            await asyncio.sleep(0.05)
            await a.send_json_to(self.movement(x=2449))
            await a.send_json_to(self.movement(y=1231))
            self.assertTrue(await b.receive_nothing())

    async def test_rooftop_floor_and_return_to_campus_are_shared(self):
        async with self.connections(self.a, self.b) as (a, b):
            first, _ = await self.welcome_pair(a, b)
            self.assertEqual(first["players"][0]["floor"], "campus")
            await a.send_json_to(self.movement(floor="rooftop", x=2310.25, y=1700.5))
            peer = (await b.receive_json_from())["player"]
            self.assertEqual((peer["floor"], peer["x"], peer["y"]), ("rooftop", 2310.25, 1700.5))
            self.assertEqual(peer["id"], first["selfId"])
            await asyncio.sleep(0.05)
            await a.send_json_to(self.movement(floor="campus", x=2233.5, y=912))
            peer = (await b.receive_json_from())["player"]
            self.assertEqual((peer["floor"], peer["x"], peer["y"]), ("campus", 2233.5, 912.0))

    async def test_unknown_floors_and_rooftop_out_of_bounds_positions_are_rejected(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            for changes in [{"floor": []}, {"floor": "basement"}, {"floor": ""},
                            {"floor": "rooftop", "x": 2449}, {"floor": "rooftop", "y": 1801},
                            {"floor": "campus", "y": 1700}]:
                await a.send_json_to(self.movement(**changes))
            self.assertTrue(await b.receive_nothing())
            await a.send_json_to(self.movement(floor="rooftop", y=1700))
            self.assertEqual((await b.receive_json_from())["player"]["floor"], "rooftop")

    async def test_disconnect_removes_avatar_and_later_connection_has_no_ghost(self):
        async with self.connections(self.a, self.b) as (a, b):
            first, _ = await self.welcome_pair(a, b)
            await a.disconnect()
            self.assertEqual(await b.receive_json_from(), {"type": "leave", "id": first["selfId"]})
            reconnect = self.socket(self.a)
            try:
                self.assertTrue((await reconnect.connect())[0])
                new = await reconnect.receive_json_from()
                self.assertEqual(len(new["players"]), 2)
                self.assertNotIn(first["selfId"], {p["id"] for p in new["players"]})
            finally:
                await reconnect.disconnect()

    async def test_two_tabs_of_same_account_have_independent_presence(self):
        async with self.connections(self.a, self.a) as (a, b):
            first, second = await self.welcome_pair(a, b)
            self.assertNotEqual(first["selfId"], second["selfId"])
            self.assertEqual({p["nickname"] for p in second["players"]}, {"조원 하나"})

    async def test_logout_in_another_tab_revokes_socket_and_announces_leave(self):
        with patch.object(consumers.CampusConsumer, "session_check_interval", 0.05):
            async with self.connections(self.a, self.b) as (a, b):
                first, _ = await self.welcome_pair(a, b)
                await database_sync_to_async(self.a.logout)()
                close = await a.receive_output(timeout=2)
                self.assertEqual(close, {"type": "websocket.close", "code": 4401})
                self.assertEqual(await b.receive_json_from(), {"type": "leave", "id": first["selfId"]})

    async def test_nickname_change_is_published_to_existing_connections(self):
        with patch.object(consumers.CampusConsumer, "session_check_interval", 0.05):
            async with self.connections(self.a, self.b) as (a, b):
                await self.welcome_pair(a, b)
                await database_sync_to_async(Profile.objects.filter(user=self.alice).update)(nickname="새 이름")
                self.assertEqual((await b.receive_json_from(timeout=2))["player"]["nickname"], "새 이름")

    async def test_outfit_change_is_shared_with_peers_and_the_open_map(self):
        with patch.object(consumers.CampusConsumer, "session_check_interval", 0.05):
            async with self.connections(self.a, self.b) as (a, b):
                await self.welcome_pair(a, b)
                await database_sync_to_async(Profile.objects.filter(user=self.alice).update)(avatar="female-1")
                self.assertEqual((await b.receive_json_from(timeout=2))["player"]["avatar"], "female-1")
                own = await a.receive_json_from(timeout=2)
                self.assertEqual((own["type"], own["player"]["avatar"]), ("identity", "female-1"))

    async def test_oversized_and_malformed_payloads_close_without_ghosts(self):
        for payload, code in [("{" + "x" * 4097, 1009), ("not-json", 1007)]:
            async with self.connections(self.a) as (a,):
                await a.receive_json_from()
                await a.send_to(text_data=payload)
                self.assertEqual((await a.receive_output())["code"], code)
                self.assertFalse(consumers.room.players)

    async def test_heartbeat_keeps_idle_clients_connected_and_rate_limits_movement(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            await a.send_json_to({"type": "ping"})
            self.assertEqual(await a.receive_json_from(), {"type": "pong"})
            # Control the consumer clock: a slow PC must not stretch this burst
            # beyond the throttle interval and make the assertion intermittent.
            clock = {"now": 1000.0}
            with patch.object(consumers, "time", SimpleNamespace(monotonic=lambda: clock["now"])):
                for i in range(30):
                    await a.send_json_to(self.movement(x=1250 + i))
                self.assertEqual((await b.receive_json_from())["type"], "move")
                self.assertTrue(await b.receive_nothing())
                clock["now"] += 0.05
                await a.send_json_to(self.movement(x=1300))
                self.assertEqual((await b.receive_json_from())["player"]["x"], 1300)

    async def test_chat_reaches_sender_and_other_floor_with_server_identity(self):
        async with self.connections(self.a, self.b) as (a, b):
            first, second = await self.welcome_pair(a, b)
            await b.send_json_to(self.movement(floor="rooftop", y=1610))
            await a.receive_json_from()
            await b.send_json_to({"type": "chat", "text": "  안녕하세요!  ",
                                  "nickname": "사칭", "playerId": first["selfId"], "floor": "campus"})
            own, other = await b.receive_json_from(), await a.receive_json_from()
            self.assertEqual(own, other)
            self.assertEqual(own["type"], "chat")
            message = own["message"]
            self.assertEqual(message["playerId"], second["selfId"])
            self.assertEqual(message["nickname"], "조원 둘")
            self.assertEqual(message["floor"], "rooftop")
            self.assertEqual(message["text"], "안녕하세요!")
            self.assertIsNotNone(datetime.fromisoformat(message["sentAt"]).tzinfo)
            self.assertTrue(message["id"])
            @database_sync_to_async
            def stored_message():
                saved = ChatMessage.objects.get(pk=message["id"])
                event = EventOutbox.objects.get(event_type="chat_sent")
                return saved.body, str(saved.floor.floor_uuid), event.raw_data

            body, floor_uuid, raw = await stored_message()
            self.assertEqual(body, message["text"])
            self.assertEqual(raw["message_uuid"], message["id"])
            self.assertEqual(raw["floor_uuid"], floor_uuid)
            self.assertNotIn("text", raw)
            self.assertNotIn("nickname", raw)
            self.assertTrue(await a.receive_nothing())
            self.assertTrue(await b.receive_nothing())

    async def test_invalid_chat_is_rejected_without_broadcast_or_losing_presence(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            for text in [None, [], True, "", "   ", "가" * 201, "bad\x00text", "\ud800"]:
                await a.send_json_to({"type": "chat", "text": text})
                self.assertEqual((await a.receive_json_from())["type"], "chat_error")
            self.assertTrue(await b.receive_nothing())
            await a.send_json_to(self.movement(x=1300))
            self.assertEqual((await b.receive_json_from())["type"], "move")

    async def test_chat_accepts_200_unicode_characters_and_keeps_html_as_text(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            text = "🎮" * 200
            await a.send_json_to({"type": "chat", "text": text})
            self.assertEqual((await a.receive_json_from())["message"]["text"], text)
            self.assertEqual((await b.receive_json_from())["message"]["text"], text)
            await asyncio.sleep(0.81)
            text = '<img src=x onerror="alert(1)">'
            await a.send_json_to({"type": "chat", "text": text})
            self.assertEqual((await a.receive_json_from())["message"]["text"], text)
            self.assertEqual((await b.receive_json_from())["message"]["text"], text)

    async def test_chat_rate_limit_does_not_throttle_the_next_movement(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            clock = {"now": 1000.0}
            with patch.object(consumers, "time", SimpleNamespace(monotonic=lambda: clock["now"])):
                await a.send_json_to({"type": "chat", "text": "첫 메시지"})
                await a.receive_json_from()
                await b.receive_json_from()
                await a.send_json_to({"type": "chat", "text": "너무 빠른 메시지"})
                self.assertEqual((await a.receive_json_from())["type"], "chat_error")
                self.assertTrue(await b.receive_nothing())
                await a.send_json_to(self.movement(x=1300))
                self.assertEqual((await b.receive_json_from())["player"]["x"], 1300)
                clock["now"] += 0.81
                await a.send_json_to({"type": "chat", "text": "다음 메시지"})
                self.assertEqual((await a.receive_json_from())["message"]["text"], "다음 메시지")
                self.assertEqual((await b.receive_json_from())["message"]["text"], "다음 메시지")

    async def test_chat_uses_new_nickname_and_rejects_a_logged_out_session(self):
        async with self.connections(self.a, self.b) as (a, b):
            first, _ = await self.welcome_pair(a, b)
            await database_sync_to_async(Profile.objects.filter(user=self.alice).update)(nickname="새 닉네임")
            await a.send_json_to({"type": "chat", "text": "이름 변경 후"})
            self.assertEqual((await a.receive_json_from())["message"]["nickname"], "새 닉네임")
            self.assertEqual((await b.receive_json_from())["message"]["nickname"], "새 닉네임")
            await database_sync_to_async(self.a.logout)()
            await asyncio.sleep(0.81)
            await a.send_json_to({"type": "chat", "text": "로그아웃 후 전송"})
            self.assertEqual(await a.receive_output(timeout=2), {"type": "websocket.close", "code": 4401})
            self.assertEqual(await b.receive_json_from(), {"type": "leave", "id": first["selfId"]})

    async def test_glass_door_state_reaches_both_players_and_later_connections(self):
        async with self.connections(self.a, self.b) as (a, b):
            first, second = await self.welcome_pair(a, b)
            self.assertEqual(len(first["doors"]), 8)
            self.assertTrue(all(value is False for value in first["doors"].values()))
            await a.send_json_to(self.movement(x=1649.25, y=533.5))
            await b.receive_json_from()
            await a.send_json_to({"type": "door", "doorId": "door-class1", "open": True})
            expected = {"type": "door_state", "doorId": "door-class1", "open": True}
            self.assertEqual(await a.receive_json_from(), expected)
            self.assertEqual(await b.receive_json_from(), expected)
            self.assertFalse(await database_sync_to_async(ChatMessage.objects.exists)())
            later = self.socket(self.a)
            try:
                self.assertTrue((await later.connect())[0])
                self.assertTrue((await later.receive_json_from())["doors"]["door-class1"])
            finally:
                await later.disconnect()

    async def test_glass_door_cannot_close_over_another_player(self):
        consumers.room.doors["door-class1"] = True
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            await a.send_json_to(self.movement(x=1649.25, y=533.5))
            await b.receive_json_from()
            await b.send_json_to(self.movement(x=1649.25, y=553.5))
            await a.receive_json_from()
            await a.send_json_to({"type": "door", "doorId": "door-class1", "open": False})
            self.assertEqual((await a.receive_json_from())["type"], "door_error")
            self.assertTrue(consumers.room.doors["door-class1"])
            self.assertTrue(await b.receive_nothing())
            await b.send_json_to(self.movement(x=1649.25, y=510))
            await a.receive_json_from()
            await asyncio.sleep(0.16)
            await a.send_json_to({"type": "door", "doorId": "door-class1", "open": False})
            self.assertFalse((await a.receive_json_from())["open"])
            self.assertFalse((await b.receive_json_from())["open"])

    async def test_invalid_or_distant_door_requests_do_not_change_shared_state(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            for payload in [{"doorId": []}, {"doorId": "invalid", "open": True},
                            {"doorId": "door-class1", "open": "yes"}]:
                await a.send_json_to({"type": "door", **payload})
            self.assertTrue(await a.receive_nothing())
            await a.send_json_to({"type": "door", "doorId": "door-class1", "open": True})
            self.assertEqual((await a.receive_json_from())["type"], "door_error")
            self.assertTrue(await b.receive_nothing())
            self.assertFalse(consumers.room.doors["door-class1"])

    async def test_door_rejects_a_logged_out_session_immediately(self):
        async with self.connections(self.a, self.b) as (a, b):
            first, _ = await self.welcome_pair(a, b)
            await database_sync_to_async(self.a.logout)()
            await a.send_json_to({"type": "door", "doorId": "door-class1", "open": True})
            self.assertEqual(await a.receive_output(timeout=2), {"type": "websocket.close", "code": 4401})
            self.assertEqual(await b.receive_json_from(), {"type": "leave", "id": first["selfId"]})
            self.assertFalse(consumers.room.doors["door-class1"])

    async def test_expired_legacy_socket_does_not_create_a_new_platform_session(self):
        @database_sync_to_async
        def make_idle():
            session = self.a.session
            old = timezone.now().timestamp() - 3600
            session[STARTED] = session[ACTIVITY] = old
            session.save()

        await make_idle()
        ws = self.socket(self.a)
        try:
            connected, code = await ws.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4401)
            self.assertFalse(await database_sync_to_async(PlatformSession.objects.exists)())
            self.assertFalse(await database_sync_to_async(EventOutbox.objects.exists)())
        finally:
            await ws.disconnect()

    async def test_legacy_socket_preserves_policy_and_reconnects_to_same_log_session(self):
        @database_sync_to_async
        def saved_session():
            data = self.a.session.load()
            return data[STARTED], data[ACTIVITY], data["platform_session_uuid"]

        async with self.connections(self.a) as (first,):
            await first.receive_json_from()
            initial = await saved_session()
        async with self.connections(self.a) as (second,):
            await second.receive_json_from()
            self.assertEqual(await saved_session(), initial)
        self.assertEqual(await database_sync_to_async(PlatformSession.objects.count)(), 1)
        self.assertFalse(await database_sync_to_async(EventOutbox.objects.filter(event_type="session_ended").exists)())


    async def test_storage_sliding_door_is_shared_with_current_and_later_players(self):
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            await a.send_json_to(self.movement(x=2112.75, y=146))
            await b.receive_json_from()
            await a.send_json_to({"type": "door", "doorId": "door-storage", "open": True})
            expected = {"type": "door_state", "doorId": "door-storage", "open": True}
            self.assertEqual(await a.receive_json_from(), expected)
            self.assertEqual(await b.receive_json_from(), expected)
            later = self.socket(self.a)
            try:
                self.assertTrue((await later.connect())[0])
                self.assertTrue((await later.receive_json_from())["doors"]["door-storage"])
            finally:
                await later.disconnect()

    async def test_storage_sliding_door_cannot_close_over_another_player(self):
        consumers.room.doors["door-storage"] = True
        async with self.connections(self.a, self.b) as (a, b):
            await self.welcome_pair(a, b)
            await a.send_json_to(self.movement(x=2112.75, y=146))
            await b.receive_json_from()
            await b.send_json_to(self.movement(x=2112.75, y=126))
            await a.receive_json_from()
            await a.send_json_to({"type": "door", "doorId": "door-storage", "open": False})
            self.assertEqual((await a.receive_json_from())["type"], "door_error")
            self.assertTrue(consumers.room.doors["door-storage"])
            await asyncio.sleep(0.06)
            await b.send_json_to(self.movement(x=2112.75, y=100))
            await a.receive_json_from()
            await asyncio.sleep(0.16)
            await a.send_json_to({"type": "door", "doorId": "door-storage", "open": False})
            self.assertFalse((await a.receive_json_from())["open"])
            self.assertFalse((await b.receive_json_from())["open"])
