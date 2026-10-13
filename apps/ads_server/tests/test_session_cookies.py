from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import TestCase, tag
from django.urls import reverse
from django.utils import timezone

from foundation.models import User
from tests.factories import PW


@tag("security")
class SessionCookieTests(TestCase):
    def setUp(self):
        User.objects.create_user("sess_user", PW, nickname="세션", class_label="1반")

    def login(self):
        return self.client.post(reverse("login"), {"username": "sess_user", "password": PW})

    def test_cookie_names_and_flags(self):
        page = self.client.get(reverse("login"))
        csrf = page.cookies["ads_csrftoken"]
        self.assertEqual(csrf["samesite"], "Lax")
        r = self.login()
        morsel = r.cookies["ads_sessionid"]
        self.assertTrue(morsel["httponly"])
        self.assertEqual(morsel["samesite"], "Lax")
        self.assertNotIn("sessionid", r.cookies)  # 기본 이름을 쓰지 않는다

    def test_logout_requires_post_and_flushes_session(self):
        self.login()
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.get(reverse("advertiser_home")).status_code, 200)  # GET 으로는 로그아웃되지 않는다
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        r = self.client.get(reverse("advertiser_home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])

    def test_session_key_rotates_on_login(self):
        session = self.client.session
        session["anonymous"] = 1
        session.save()
        before = session.session_key
        self.login()
        self.assertNotEqual(self.client.session.session_key, before)

    def test_session_age_is_8_hours(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 60 * 60)
        self.login()
        self.assertEqual(self.client.session.get_expiry_age(), 8 * 60 * 60)

    def test_session_expires(self):
        self.login()
        self.assertEqual(self.client.get(reverse("advertiser_home")).status_code, 200)
        Session.objects.update(expire_date=timezone.now() - timezone.timedelta(seconds=1))
        r = self.client.get(reverse("advertiser_home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])

    def test_authenticated_user_is_redirected_from_login(self):
        self.login()
        self.assertEqual(self.client.get(reverse("login")).status_code, 302)
