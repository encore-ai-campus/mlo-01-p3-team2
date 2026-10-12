from datetime import timedelta
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.models import Session
from django.db.models.query import QuerySet
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from campus import session_registry
from campus.positions import save_position
from .models import Profile
from .session_cleanup import run_due_cleanup
from .session_policy import ACTIVITY, STARTED, check_session, expire_record, start_login


class CleanupStartupTests(SimpleTestCase):
    def test_launcher_can_import_cleanup_before_django_apps_are_loaded(self):
        result = subprocess.run(
            [sys.executable, "-c", "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); import accounts.session_cleanup"],
            cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


@override_settings(CAMPUS_LOGIN_MAX_AGE_SECONDS=480, CAMPUS_LOGIN_IDLE_TIMEOUT_SECONDS=30,
                   CAMPUS_LOGIN_WARNING_SECONDS=10, CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS=5)
class SessionPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="session-user", password="Session!River4820")
        Profile.objects.create(user=cls.user, nickname="세션 테스트", avatar="male-1")

    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)
        self.client.force_login(self.user)
        session = self.client.session
        with patch("accounts.session_policy.timezone.now", return_value=self.now):
            start_login(session)
        session.save()
        self.key = session.session_key

    def test_login_and_signup_fix_an_absolute_deadline(self):
        for route, data in [
            ("login", {"username": self.user.username, "password": "Session!River4820"}),
            ("signup", {"username": "new-session-user", "cohort": "mlo-1",
                        "password1": "Session!River4820", "password2": "Session!River4820"}),
        ]:
            client = Client()
            with patch("accounts.session_policy.timezone.now", return_value=self.now):
                response = client.post(f"/accounts/{route}/", data)
            self.assertEqual(response.status_code, 302)
            session = client.session
            self.assertEqual(session[STARTED], self.now.timestamp())
            self.assertEqual(session[ACTIVITY], self.now.timestamp())
            self.assertEqual(Session.objects.get(pk=session.session_key).expire_date, self.now + timedelta(seconds=480))

    def test_activity_moves_idle_deadline_but_never_absolute_deadline(self):
        for elapsed in range(20, 480, 20):
            state = check_session(self.key, touch=True, force=True, now=self.now.timestamp() + elapsed)
            self.assertTrue(state["authenticated"])
            self.assertEqual(state["absoluteExpiresAt"], (self.now.timestamp() + 480) * 1000)
            self.assertEqual(state["idleExpiresAt"], (self.now.timestamp() + elapsed + 30) * 1000)
        state = check_session(self.key, touch=True, force=True, now=self.now.timestamp() + 480)
        self.assertEqual(state["reason"], "maximum")
        self.assertFalse(Session.objects.filter(pk=self.key).exists())

    def test_status_poll_does_not_count_as_activity(self):
        for elapsed in (10, 20, 29):
            with patch("accounts.session_policy.timezone.now", return_value=self.now + timedelta(seconds=elapsed)):
                response = self.client.get("/accounts/session/status/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(Session.objects.get(pk=self.key).get_decoded()[ACTIVITY], self.now.timestamp())
            self.assertIn("no-store", response.headers["Cache-Control"])
        with patch("accounts.session_policy.timezone.now", return_value=self.now + timedelta(seconds=30)):
            response = self.client.post("/accounts/session/activity/", {})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["reason"], "idle")
        self.assertFalse(Session.objects.filter(pk=self.key).exists())
        self.assertEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value, "")

    def test_real_activity_is_csrf_protected_and_cannot_revive_deleted_sessions(self):
        client = Client(enforce_csrf_checks=True)
        client.cookies = self.client.cookies.copy()
        with patch("accounts.session_policy.timezone.now", return_value=self.now + timedelta(seconds=10)):
            self.assertEqual(client.post("/accounts/session/activity/").status_code, 403)
            self.assertEqual(client.get("/accounts/session/activity/").status_code, 405)
            self.assertEqual(self.client.post("/accounts/session/status/").status_code, 405)
        self.assertEqual(Session.objects.get(pk=self.key).get_decoded()[ACTIVITY], self.now.timestamp())
        client.get("/accounts/nickname/")
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        with patch("accounts.session_policy.timezone.now", return_value=self.now + timedelta(seconds=20)):
            accepted = client.post("/accounts/session/activity/", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(Session.objects.get(pk=self.key).get_decoded()[ACTIVITY], (self.now + timedelta(seconds=20)).timestamp())
        Session.objects.filter(pk=self.key).delete()
        self.assertEqual(client.post("/accounts/session/activity/", HTTP_X_CSRFTOKEN=token).status_code, 401)
        self.assertFalse(Session.objects.filter(pk=self.key).exists())

    def test_automatic_api_reads_do_not_extend_idle_but_accepted_user_writes_do(self):
        with patch("accounts.session_policy.timezone.now", return_value=self.now + timedelta(seconds=10)):
            self.assertEqual(self.client.get("/api/board/menu/").status_code, 200)
        self.assertEqual(Session.objects.get(pk=self.key).get_decoded()[ACTIVITY], self.now.timestamp())
        with patch("accounts.session_policy.timezone.now", return_value=self.now + timedelta(seconds=20)):
            self.assertEqual(self.client.post("/accounts/nickname/", {"nickname": "변경한 닉네임"}).status_code, 302)
        self.assertEqual(Session.objects.get(pk=self.key).get_decoded()[ACTIVITY], (self.now + timedelta(seconds=20)).timestamp())

    def test_expiry_saves_latest_tab_position_then_deletes_session_then_notifies(self):
        old = {"floor": "campus", "x": 1500.5, "y": 442.25, "dir": "left"}
        newest = {"floor": "rooftop", "x": 2100.25, "y": 1700.75, "dir": "up"}
        for player, position, offset in (("policy-old", old, 1), ("policy-new", newest, 2)):
            session_registry.register(player, self.key, self.user.pk)
            session_registry.update(player, position, self.now + timedelta(seconds=offset))
            self.addCleanup(session_registry.unregister, player)
        trace = []
        original_delete = QuerySet.delete

        def record_save(user, position, observed_at):
            self.assertTrue(Session.objects.filter(pk=self.key).exists())
            trace.append("save")
            return save_position(user, position, observed_at)

        def record_delete(queryset):
            if queryset.model is Session:
                trace.append("delete")
            return original_delete(queryset)

        async def notify(group, packet):
            trace.append("notify")
            self.assertEqual(group, session_registry.session_group(self.key))
            self.assertEqual(packet["reason"], "idle")

        layer = SimpleNamespace(group_send=AsyncMock(side_effect=notify))
        with patch("accounts.session_policy.save_position", side_effect=record_save), \
                patch.object(QuerySet, "delete", record_delete), \
                patch("accounts.session_policy.get_channel_layer", return_value=layer):
            check_session(self.key, now=self.now.timestamp() + 30)
        self.assertEqual(trace, ["save", "delete", "notify"])
        self.assertEqual(Profile.objects.get(user=self.user).last_position, newest)
        self.assertFalse(Session.objects.filter(pk=self.key).exists())

    def test_stale_expiry_revision_cannot_delete_activity_from_another_tab(self):
        stale = Session.objects.get(pk=self.key)
        check_session(self.key, touch=True, force=True, now=self.now.timestamp() + 20)
        with patch("accounts.session_policy.get_channel_layer") as layer:
            self.assertFalse(expire_record(stale, stale.get_decoded(), "idle"))
            layer.assert_not_called()
        self.assertTrue(check_session(self.key, now=self.now.timestamp() + 35)["authenticated"])

    def test_existing_session_adopts_policy_without_changing_identity(self):
        legacy = Client()
        legacy.force_login(self.user)
        key = legacy.session.session_key
        before = Session.objects.get(pk=key).get_decoded()
        self.assertNotIn(STARTED, before)
        state = check_session(key, now=self.now.timestamp())
        after = Session.objects.get(pk=key).get_decoded()
        self.assertTrue(state["authenticated"])
        self.assertEqual(after[SESSION_KEY], before[SESSION_KEY])
        self.assertEqual(after[STARTED], self.now.timestamp())
        self.assertEqual(Session.objects.get(pk=key).expire_date, self.now + timedelta(seconds=480))

    def test_invalid_policy_fields_expire_and_larger_config_cannot_extend_old_deadline(self):
        with override_settings(CAMPUS_LOGIN_MAX_AGE_SECONDS=960):
            state = check_session(self.key, now=self.now.timestamp())
        self.assertEqual(state["absoluteExpiresAt"], (self.now.timestamp() + 480) * 1000)
        session = self.client.session
        session[ACTIVITY] = "not-a-timestamp"
        session.save()
        self.assertEqual(check_session(self.key)["reason"], "invalid")
        self.assertFalse(Session.objects.filter(pk=self.key).exists())


@override_settings(CAMPUS_SESSION_CLEANUP_TIME="04:00")
class SessionCleanupTests(TestCase):
    def test_cleanup_runs_once_per_day_and_removes_only_expired_sessions(self):
        now = timezone.now()
        user = get_user_model().objects.create_user(username="cleanup-user")
        profile = Profile.objects.create(user=user, nickname="유지되는 계정")
        Session.objects.create(pk="expired-session", session_data="", expire_date=now - timedelta(seconds=1))
        Session.objects.create(pk="valid-session", session_data="", expire_date=now + timedelta(days=1))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session-cleanup.json"
            self.assertTrue(run_due_cleanup(now, path))
            self.assertFalse(Session.objects.filter(pk="expired-session").exists())
            self.assertTrue(Session.objects.filter(pk="valid-session").exists())
            self.assertTrue(Profile.objects.filter(pk=profile.pk).exists())
            self.assertFalse(run_due_cleanup(now + timedelta(seconds=1), path))
            local = timezone.localtime(now)
            tomorrow = (local + timedelta(days=1)).replace(hour=4, minute=0, second=0, microsecond=0)
            self.assertFalse(run_due_cleanup(tomorrow - timedelta(seconds=1), path))
            self.assertTrue(run_due_cleanup(tomorrow, path))
            self.assertEqual(json.loads(path.read_text())["completed_day"], tomorrow.date().isoformat())

    def test_failed_cleanup_does_not_mark_completed_and_can_retry(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session-cleanup.json"
            with patch("accounts.session_cleanup.call_command", side_effect=RuntimeError("DB unavailable")):
                with self.assertRaises(RuntimeError):
                    run_due_cleanup(path=path)
            self.assertFalse(path.exists())
            self.assertTrue(run_due_cleanup(path=path))
