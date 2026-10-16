import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from unittest.mock import patch

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Profile
from campus import tests as socket_tests
from . import service
from .models import Control, Entry, Event


def buzzer_position():
    return {"floor": "rooftop", "x": service.BUZZER_POINT[0], "y": service.BUZZER_POINT[1]}


def setup_users(case):
    Control.objects.get_or_create(pk=1)
    case.admin = get_user_model().objects.create_user(username="raffle_admin", password="Test!River4820", is_staff=True)
    case.member = get_user_model().objects.create_user(username="raffle_member", password="Test!River4820")
    Profile.objects.create(user=case.admin, nickname="관리자")
    Profile.objects.create(user=case.member, nickname="참가 조원")
    case.client.force_login(case.admin)


class RaffleAPITests(TestCase):
    def setUp(self):
        setup_users(self)

    def post(self, action, **changes):
        event_id = Control.objects.get(pk=1).current_event_id
        data = {"action": action, "eventId": str(event_id) if event_id else None, **changes}
        return self.client.post("/api/raffle/control/", data=json.dumps(data), content_type="application/json")

    def test_empty_event_has_no_automatic_schedule(self):
        data = self.client.get("/api/raffle/").json()
        self.assertIsNone(data["event"])
        self.assertEqual(data["participants"], [])
        opened = self.post("open").json()["event"]
        self.assertEqual(opened["status"], "open")
        self.assertIsNone(opened["opensAt"])
        self.assertIsNone(opened["drawAt"])

    def test_authentication_staff_and_csrf_are_enforced(self):
        self.assertEqual(Client().get("/api/raffle/").status_code, 401)
        self.client.force_login(self.member)
        self.assertEqual(self.post("open").status_code, 403)
        self.assertFalse(self.client.get("/api/raffle/").json()["canManage"])
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.admin)
        self.assertEqual(secure.post("/api/raffle/control/", {"action": "open"}).status_code, 403)
        self.assertEqual(Event.objects.count(), 0)

    def test_setup_required_and_get_does_not_mutate_event(self):
        Profile.objects.filter(user=self.member).update(cohort="mlo-1", setup_complete=False)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get("/api/raffle/").status_code, 403)
        self.client.force_login(self.admin)
        self.post("prepare")
        revision = Control.objects.get(pk=1).revision
        self.client.get("/api/raffle/")
        self.assertEqual(Control.objects.get(pk=1).revision, revision)

    def test_invalid_schedule_and_stale_event_are_rejected(self):
        self.post("prepare")
        later = timezone.now() + timedelta(hours=1)
        self.assertEqual(self.post("schedule", opensAt=later.isoformat(), drawAt=(later-timedelta(minutes=1)).isoformat()).status_code, 400)
        self.assertEqual(self.post("schedule", drawAt=timezone.now().replace(tzinfo=None).isoformat()).status_code, 400)
        self.assertEqual(self.post("schedule", drawAt="bad").status_code, 400)
        self.assertEqual(self.post("schedule", title="").status_code, 400)
        self.assertEqual(self.post("open", eventId="old-event").status_code, 409)
        self.assertEqual(self.post("schedule", opensAt=later.isoformat(), drawAt=(later+timedelta(hours=1)).isoformat()).status_code, 200)

    def test_state_exposes_nickname_snapshot_and_my_entry_without_account_ids(self):
        self.post("open")
        event = Control.objects.get(pk=1).current_event
        entry_id, created = service.join(self.member, buzzer_position(), str(event.pk))
        self.assertTrue(created)
        Profile.objects.filter(user=self.member).update(nickname="바꾼 닉네임")
        self.client.force_login(self.member)
        data = self.client.get("/api/raffle/").json()
        self.assertEqual(data["myEntryId"], entry_id)
        self.assertEqual(data["participants"], [{"id":entry_id, "nickname":"참가 조원"}])
        self.assertNotIn("userId", data["participants"][0])

    def test_repeat_draw_keeps_original_result_and_new_event_preserves_history(self):
        self.post("open")
        event = Control.objects.get(pk=1).current_event
        service.join(self.member, buzzer_position(), str(event.pk))
        first = self.post("draw").json()["event"]
        again = self.post("draw").json()["event"]
        self.assertEqual(first["winner"], again["winner"])
        self.assertEqual(first["drawnAt"], again["drawnAt"])
        fresh = self.post("prepare").json()
        self.assertNotEqual(fresh["event"]["id"], str(event.pk))
        self.assertEqual(fresh["participants"], [])
        self.assertEqual(Entry.objects.filter(event=event).count(), 1)
        self.assertEqual(Event.objects.count(), 2)


class RaffleServiceTests(TransactionTestCase):
    def setUp(self):
        setup_users(self)
        service.control_event("prepare", None)
        self.event = Control.objects.get(pk=1).current_event
        self.point = buzzer_position()

    def test_only_open_event_and_rooftop_buzzer_can_accept_entry(self):
        with self.assertRaises(service.RaffleError):
            service.join(self.member, self.point, str(self.event.pk))
        service.control_event("open", str(self.event.pk))
        for point in ({**self.point,"floor":"campus"}, {**self.point,"x":2000}, {**self.point,"y":float("nan")}, {**self.point,"x":True}):
            with self.assertRaises(service.RaffleError):
                service.join(self.member, point, str(self.event.pk))
        first, _ = service.join(self.member, self.point, str(self.event.pk))
        second, created = service.join(self.member, self.point, str(self.event.pk))
        self.assertEqual(first, second)
        self.assertFalse(created)
        self.assertEqual(Entry.objects.count(), 1)

    def test_deadline_closes_entry_even_before_scheduler_tick(self):
        service.control_event("open", str(self.event.pk))
        Event.objects.filter(pk=self.event.pk).update(draw_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(service.RaffleError):
            service.join(self.member, self.point, str(self.event.pk))
        self.assertEqual(Entry.objects.count(), 0)

    def test_reserved_open_draw_and_restart_catchup(self):
        now = timezone.now()
        self.event.opens_at, self.event.draw_at = now+timedelta(seconds=10), now+timedelta(seconds=20)
        self.event.save()
        self.assertFalse(service.advance_due(now))
        self.assertTrue(service.advance_due(now+timedelta(seconds=11)))
        service.join(self.member, self.point, str(self.event.pk))
        self.assertTrue(service.advance_due(now+timedelta(seconds=30)))
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "drawn")
        self.assertEqual(self.event.winner_nickname, "참가 조원")
        self.assertFalse(service.advance_due(now+timedelta(seconds=50)))

    def test_empty_draw_completes_once_without_fake_winner(self):
        service.control_event("open", str(self.event.pk))
        service.control_event("draw", str(self.event.pk))
        data = service.snapshot(self.admin)
        self.assertEqual(data["event"]["status"], "drawn")
        self.assertIsNone(data["event"]["winner"])

    def test_concurrent_entries_and_draws_are_idempotent(self):
        service.control_event("open", str(self.event.pk))
        def enter(_):
            close_old_connections()
            try:
                return service.join(self.member, self.point, str(self.event.pk))
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=3) as pool:
            entries = list(pool.map(enter, range(3)))
        self.assertEqual(len({result[0] for result in entries}), 1)
        self.assertEqual(sum(result[1] for result in entries), 1)
        def draw(_):
            close_old_connections()
            try:
                service.control_event("draw", str(self.event.pk))
            finally:
                close_old_connections()
        with patch("raffle.service.secrets.choice", wraps=service.secrets.choice) as picker:
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(draw, range(3)))
            self.assertEqual(picker.call_count, 1)
        self.event.refresh_from_db()
        self.assertEqual(str(self.event.winner_entry_id), entries[0][0])


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"], DEBUG=False)
class RaffleSocketTests(TransactionTestCase):
    setUp = socket_tests.CampusSocketTests.setUp
    socket = socket_tests.CampusSocketTests.socket
    connections = socket_tests.CampusSocketTests.connections
    welcome_pair = socket_tests.CampusSocketTests.welcome_pair
    movement = socket_tests.CampusSocketTests.movement

    async def next_type(self, ws, kind):
        for _ in range(20):
            packet = await ws.receive_json_from(timeout=2)
            if packet["type"] == kind:
                return packet
        self.fail(f"Missing {kind}")

    async def test_entries_are_shared_across_floors_and_reconnect_restores_own_entry(self):
        from . import survey
        from .models import SurveyAttempt
        from .test_survey import configure_bridge, google_result
        await database_sync_to_async(configure_bridge)()
        await database_sync_to_async(service.control_event)("open", None)
        event_id = (await database_sync_to_async(service.snapshot)(self.alice))["event"]["id"]
        async with self.connections(self.a, self.b) as (a,b):
            first, second = await self.welcome_pair(a,b)
            self.assertEqual(first["raffle"]["event"]["id"], event_id)
            await a.send_json_to({"type":"raffle_enter", "eventId":event_id, "nickname":"사칭"})
            self.assertEqual((await self.next_type(a,"raffle_error"))["message"], "옥상 이벤트 부저 가까이에서 참여해 주세요.")
            await asyncio.sleep(.81)
            await a.send_json_to(self.movement(**buzzer_position()))
            await self.next_type(b,"move")
            await a.send_json_to({"type":"raffle_enter", "eventId":event_id, "nickname":"사칭"})
            issued = await self.next_type(a,"raffle_survey")
            self.assertIn('entry.123456789=', issued['url'])
            self.assertNotIn('사칭', issued['url'])
            self.assertEqual(await database_sync_to_async(Entry.objects.count)(), 0)
            waiting = await self.next_type(b,"raffle_state")
            self.assertEqual(waiting['state']['participants'], [])
            attempt = await database_sync_to_async(SurveyAttempt.objects.get)(user=self.alice)
            result = google_result([{'token':attempt.token, 'responseId':'qa-socket-response', 'submittedAt':timezone.now().isoformat()}])
            with patch('raffle.survey.google_request', return_value=result):
                self.assertEqual(await database_sync_to_async(survey.synchronize)(), 1)
            entry_id = str((await database_sync_to_async(Entry.objects.get)(user=self.alice)).pk)
            shared = await self.next_type(b,"raffle_state")
            self.assertEqual(shared["state"]["participants"][0]["nickname"], "조원 하나")
            self.assertIsNone(shared["state"]["myEntryId"])
        async with self.connections(self.a) as (a,):
            restored = await a.receive_json_from()
            self.assertEqual(restored["raffle"]["myEntryId"], entry_id)

    async def test_draw_broadcast_has_identical_result_for_rooftop_and_18f(self):
        await database_sync_to_async(service.control_event)("open", None)
        event_id = (await database_sync_to_async(service.snapshot)())["event"]["id"]
        await database_sync_to_async(service.join)(self.alice,buzzer_position(),event_id)
        async with self.connections(self.a, self.b) as (a,b):
            await self.welcome_pair(a,b)
            await a.send_json_to(self.movement(**buzzer_position()))
            await self.next_type(b,"move")
            await database_sync_to_async(service.control_event)("draw", event_id)
            aa,bb = await asyncio.gather(self.next_type(a,"raffle_state"),self.next_type(b,"raffle_state"))
            self.assertEqual(aa["state"]["event"]["winner"],bb["state"]["event"]["winner"])
            self.assertEqual(aa["state"]["event"]["drawnAt"],bb["state"]["event"]["drawnAt"])
            self.assertEqual(bb["state"]["event"]["winner"]["nickname"],"조원 하나")
