from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import close_old_connections, connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone

from campus import session_registry
from eventing.models import EventOutbox, PlatformSession
from .models import ActiveLogin, Profile
from .session_policy import check_session


class SingleLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "Login!River4820"
        cls.user = get_user_model().objects.create_user(username="single-login", password=cls.password)
        Profile.objects.create(user=cls.user, nickname="단일 접속")

    def log_in(self, client=None):
        client = client or Client()
        with self.captureOnCommitCallbacks(execute=True):
            response = client.post("/accounts/login/", {"username": self.user.username, "password": self.password})
        self.assertEqual(response.status_code, 302)
        return client, client.session.session_key

    def test_new_browser_revokes_old_session_and_keeps_new_http_access(self):
        old, old_key = self.log_in()
        new, new_key = self.log_in()
        self.assertNotEqual(old_key, new_key)
        self.assertEqual(ActiveLogin.objects.get(user=self.user).session_key, new_key)
        self.assertFalse(Session.objects.filter(pk=old_key).exists())
        self.assertTrue(check_session(new_key)["authenticated"])
        self.assertEqual(old.get("/accounts/session/status/").status_code, 401)
        self.assertEqual(old.get("/").status_code, 302)
        self.assertEqual(new.get("/").status_code, 200)
        self.assertEqual(PlatformSession.objects.filter(user=self.user, ended_at__isnull=True).count(), 1)
        self.assertEqual(PlatformSession.objects.filter(user=self.user, end_reason="SESSION_EXPIRED").count(), 1)
        endings = EventOutbox.objects.filter(event_type="session_ended")
        self.assertEqual(endings.count(), 1)
        self.assertEqual(endings.get().payload_json["raw_data"]["end_reason"], "SESSION_EXPIRED")

    def test_shared_cookie_tabs_and_different_accounts_are_unaffected(self):
        first, key = self.log_in()
        tab = Client()
        tab.cookies = first.cookies.copy()
        other = get_user_model().objects.create_user(username="another-login", password=self.password)
        second = Client()
        second.post("/accounts/login/", {"username": other.username, "password": self.password})
        for client in (first, tab, second):
            self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(tab.session.session_key, key)

    def test_failed_login_does_not_kick_out_current_browser(self):
        _, key = self.log_in()
        failed = Client()
        self.assertEqual(failed.post("/accounts/login/", {"username": self.user.username, "password": "wrong"}).status_code, 200)
        self.assertEqual(ActiveLogin.objects.get(user=self.user).session_key, key)
        self.assertTrue(check_session(key)["authenticated"])

    def test_old_logout_cannot_clear_current_login_or_overwrite_position(self):
        old, _ = self.log_in()
        new, key = self.log_in()
        profile = Profile.objects.get(user=self.user)
        position = {"floor": "rooftop", "x": 1800, "y": 1500, "dir": "left"}
        profile.last_position = position
        profile.last_position_at = timezone.now()
        profile.save(update_fields=["last_position", "last_position_at"])
        old.post("/accounts/logout/", {"last_position": '{"floor":"campus","x":1200,"y":500,"dir":"up"}'})
        profile.refresh_from_db()
        self.assertEqual(profile.last_position, position)
        self.assertTrue(check_session(key)["authenticated"])
        self.assertEqual(new.get("/").status_code, 200)

    def test_latest_accepted_position_is_saved_before_replacement(self):
        _, old_key = self.log_in()
        player = "single-login-position"
        position = {"floor": "rooftop", "x": 1812.25, "y": 1478.5, "dir": "right"}
        session_registry.register(player, old_key, self.user.pk)
        session_registry.update(player, position, timezone.now())
        self.addCleanup(session_registry.unregister, player)
        self.log_in()
        self.assertEqual(Profile.objects.get(user=self.user).last_position, position)

    def test_superseded_legacy_key_cannot_reclaim_after_latest_logout(self):
        old = Client()
        old.force_login(self.user)
        old_key = old.session.session_key
        _, latest_key = self.log_in()
        self.assertEqual(check_session(old_key)["reason"], "replaced")
        Session.objects.filter(pk=latest_key).delete()
        self.assertFalse(check_session(old_key)["authenticated"])
        self.assertEqual(ActiveLogin.objects.get(user=self.user).session_key, latest_key)

    def test_failed_new_session_write_rolls_back_revocation_and_notifications(self):
        _, key = self.log_in()
        from .single_login import replace_login
        session = Client().session
        with patch("accounts.single_login.start_platform_session", side_effect=RuntimeError("write failed")), \
                patch("accounts.session_policy.notify_expiry") as notify:
            with self.assertRaises(RuntimeError):
                replace_login(session, self.user, timezone.now())
            notify.assert_not_called()
        self.assertEqual(ActiveLogin.objects.get(user=self.user).session_key, key)
        self.assertTrue(check_session(key)["authenticated"])

    def test_replacement_notice_and_signup_ownership(self):
        self.assertContains(self.client.get("/accounts/login/?expired=replaced"), "기존 접속이 종료됐습니다")
        response = self.client.post("/accounts/signup/", {
            "username": "single-signup", "cohort": "mlo-1",
            "password1": self.password, "password2": self.password,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ActiveLogin.objects.get(user__username="single-signup").session_key, self.client.session.session_key)


class ConcurrentLoginTests(TransactionTestCase):
    def test_two_simultaneous_logins_leave_only_one_usable_session(self):
        if connection.vendor == 'sqlite' and 'mode=memory' in str(connection.settings_dict['NAME']):
            self.skipTest('Run this threaded login regression with a file-backed SQLite test DB.')
        user = get_user_model().objects.create_user(username="concurrent-login", password="Concurrent!4820")
        Profile.objects.create(user=user, nickname="동시 로그인")
        ready = Barrier(2)

        def browser_login():
            close_old_connections()
            try:
                client = Client()
                ready.wait(timeout=5)
                response = client.post("/accounts/login/", {"username": user.username, "password": "Concurrent!4820"})
                return response.status_code, client.cookies["campus_sessionid"].value
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: browser_login(), range(2)))
        self.assertEqual([code for code, _ in results], [302, 302])
        keys = [key for _, key in results]
        self.assertEqual(sum(check_session(key)["authenticated"] for key in keys), 1)
        self.assertIn(ActiveLogin.objects.get(user=user).session_key, keys)
        self.assertEqual(PlatformSession.objects.filter(user=user, ended_at__isnull=True).count(), 1)
