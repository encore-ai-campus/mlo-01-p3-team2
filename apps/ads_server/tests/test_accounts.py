import inspect
import uuid
from datetime import timedelta

from django.test import TestCase, tag
from django.urls import reverse
from django.utils import timezone

from config.settings import base
from foundation.accounts import create_advertiser
from foundation.models import Role, SignupAttempt, User

PW = "Tr0ub4dor-horse-staple"


def signup_data(**over):
    data = {"username": "ad_user1", "password": PW, "password_confirm": PW, "nickname": "홍길동", "class_label": "1반"}
    data.update(over)
    return data


@tag("security")
class SignupTests(TestCase):
    url = None

    def setUp(self):
        self.url = reverse("signup")

    def post(self, ip="10.1.0.1", **over):
        return self.client.post(self.url, signup_data(**over), REMOTE_ADDR=ip)

    def test_signup_creates_advertiser_role(self):
        r = self.post()
        self.assertRedirects(r, reverse("login"))
        u = User.objects.get(username="ad_user1")
        self.assertEqual(u.role, Role.ADVERTISER)
        self.assertEqual((u.nickname, u.class_label), ("홍길동", "1반"))

    def test_signup_ignores_role_field(self):
        self.post(role="admin", is_superuser="1", is_staff="1")
        u = User.objects.get(username="ad_user1")
        self.assertEqual(u.role, Role.ADVERTISER)
        self.assertFalse(u.is_superuser)
        self.assertFalse(u.is_staff)

    def test_usernames_for_display(self):
        from foundation.api import usernames

        u = create_advertiser("name_lookup", PW, "닉네임", "1반")
        self.assertEqual(usernames([u.pk, uuid.uuid4(), "not-a-uuid"]), {u.pk: "name_lookup"})  # 없는·형식이 틀린 ID 는 빠진다

    def test_service_has_no_role_parameter(self):
        self.assertNotIn("role", inspect.signature(create_advertiser).parameters)

    def test_username_rules(self):
        for i, bad in enumerate(["abc", "a" * 21, "UPPER_case", "한글아이디", "bad name", "ab-cd1", ""]):
            r = self.post(ip=f"10.2.0.{i}", username=bad)
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(User.objects.count(), 0)
        for i, good in enumerate(["abcd", "a" * 20, "a_1_b2"]):
            self.assertEqual(self.post(ip=f"10.3.0.{i}", username=good).status_code, 302, good)

    def test_nickname_and_class_label_rules(self):
        bad = [
            {"nickname": "가"}, {"nickname": "가" * 21}, {"nickname": "홍​길동"},  # 제로폭 공백
            {"nickname": "홍\x07길동"}, {"class_label": ""}, {"class_label": "반" * 31}, {"nickname": "   "},
        ]
        for i, over in enumerate(bad):
            self.assertEqual(self.post(ip=f"10.4.0.{i}", **over).status_code, 400, over)
        self.assertEqual(User.objects.count(), 0)

    def test_nickname_and_class_label_are_trimmed(self):
        self.post(nickname="  홍길동  ", class_label=" 1반 ")
        u = User.objects.get(username="ad_user1")
        self.assertEqual((u.nickname, u.class_label), ("홍길동", "1반"))

    def test_password_validators_applied(self):
        cases = {
            "too_short": "Ab1!xyz",
            "numeric_only": "1234567890123",
            "common": "qwertyuiop",
            "similar_to_username": "ad_user1ab",
        }
        for i, (name, pw) in enumerate(cases.items()):
            r = self.post(ip=f"10.5.0.{i}", password=pw, password_confirm=pw)
            self.assertEqual(r.status_code, 400, name)
        self.assertEqual(User.objects.count(), 0)

    def test_password_confirm_mismatch(self):
        self.assertEqual(self.post(password_confirm="different-pass-123").status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_password_stored_as_argon2(self):
        self.assertTrue(base.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher"))
        self.assertEqual(len(base.PASSWORD_HASHERS), 1)
        self.post()
        self.assertTrue(User.objects.get(username="ad_user1").password.startswith("argon2$"))

    def test_duplicate_username_generic_error(self):
        self.post(ip="10.6.0.1")
        r = self.post(ip="10.6.0.2")
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "사용할 수 없는 아이디입니다.", status_code=400)
        self.assertEqual(User.objects.filter(username="ad_user1").count(), 1)

    def test_signup_rate_limit_per_ip(self):
        limit = 5
        for i in range(limit):  # 실패하는 시도도 센다
            self.assertEqual(self.post(ip="10.7.0.1", username="x").status_code, 400)
        r = self.post(ip="10.7.0.1", username="x")
        self.assertEqual(r.status_code, 429)
        self.assertGreater(int(r["Retry-After"]), 0)
        self.assertEqual(self.post(ip="10.7.0.2", username="x").status_code, 400)  # 다른 IP 는 영향 없음

    def test_signup_rate_limit_window_expires(self):
        for _ in range(5):
            self.post(ip="10.8.0.1", username="x")
        self.assertEqual(self.post(ip="10.8.0.1", username="x").status_code, 429)
        SignupAttempt.objects.update(created_at=timezone.now() - timedelta(minutes=61))
        self.assertEqual(self.post(ip="10.8.0.1", username="x").status_code, 400)

    def test_authenticated_user_is_redirected_from_signup(self):
        self.post()
        self.client.post(reverse("login"), {"username": "ad_user1", "password": PW})
        self.assertRedirects(self.client.get(self.url), reverse("advertiser_home"), fetch_redirect_response=False)
