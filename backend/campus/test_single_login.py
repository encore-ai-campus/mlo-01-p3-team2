from channels.db import database_sync_to_async
from django.contrib.sessions.models import Session
from django.test import Client, TransactionTestCase, override_settings

from . import tests as socket_tests


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"], DEBUG=False)
class SingleLoginSocketTests(TransactionTestCase):
    setUp = socket_tests.CampusSocketTests.setUp
    socket = socket_tests.CampusSocketTests.socket
    connections = socket_tests.CampusSocketTests.connections
    movement = socket_tests.CampusSocketTests.movement

    async def test_new_browser_closes_all_old_tabs_and_restores_latest_position(self):
        async with self.connections(self.a, self.a, self.b) as (old, old_tab, observer):
            await old.receive_json_from()
            await old_tab.receive_json_from()
            await observer.receive_json_from()
            await old.receive_json_from()  # tab join
            await old.receive_json_from()  # observer join
            await old_tab.receive_json_from()
            position = self.movement(x=1720.25, y=455.5)
            await old.send_json_to(position)
            await old_tab.receive_json_from()
            await observer.receive_json_from()
            await old.send_json_to({"type": "ping"})
            await old.receive_json_from()

            new = Client()
            response = await database_sync_to_async(new.post)("/accounts/login/", {
                "username": "alice", "password": "Test!River4820",
            })
            self.assertEqual(response.status_code, 302)
            for ws in (old, old_tab):
                self.assertEqual(await ws.receive_json_from(), {"type": "session_expired", "reason": "replaced"})
                self.assertEqual((await ws.receive_output())["code"], 4401)
            for _ in range(2):
                self.assertEqual((await observer.receive_json_from())["type"], "leave")
            stale_key = self.a.cookies["campus_sessionid"].value
            self.assertFalse(await database_sync_to_async(Session.objects.filter(pk=stale_key).exists)())
            rejected = self.socket(self.a)
            connected, code = await rejected.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4401)
            await rejected.disconnect()
            current = self.socket(new)
            self.assertTrue((await current.connect())[0])
            try:
                welcome = await current.receive_json_from()
                player = next(p for p in welcome["players"] if p["id"] == welcome["selfId"])
                self.assertEqual(player["x"], 1720.25)
                self.assertEqual(player["y"], 455.5)
                await observer.receive_json_from()  # new browser join
                await current.send_json_to({"type": "ping"})
                self.assertEqual((await current.receive_json_from())["type"], "pong")
            finally:
                await current.disconnect()
            await observer.receive_json_from()  # leave
