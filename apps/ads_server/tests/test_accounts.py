import inspect
import uuid

from django.test import TestCase, tag
from django.urls import reverse

from config.settings import base
from foundation.accounts import create_advertiser
from foundation.models import Role, User
from tests.factories import PW


def signup_data(**over):
    data = {"username": "ad_user1", "password": PW, "password_confirm": PW, "nickname": "홍길동", "class_label": "1반"}
    data.update(over)
    return data


@tag("security")
class SignupTests(TestCase):
    url = None

    def setUp(self):
        self.url = reverse("signup")

    def post(self, **over):
        return self.client.post(self.url, signup_data(**over), REMOTE_ADDR="10.1.0.1")  # 모두 한 IP(강의실 NAT 처럼)

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

    def test_profiles_for_display(self):
        from foundation.api import profiles

        u = create_advertiser("name_lookup", PW, "닉네임", "1반")
        found = profiles([u.pk, uuid.uuid4(), "not-a-uuid"])  # 없는·형식이 틀린 ID 는 빠진다
        self.assertEqual({k: (v.username, v.nickname, v.class_label) for k, v in found.items()}, {u.pk: ("name_lookup", "닉네임", "1반")})

    def test_service_has_no_role_parameter(self):
        self.assertNotIn("role", inspect.signature(create_advertiser).parameters)

    def test_username_rules(self):
        for bad in ["abc", "a" * 21, "UPPER_case", "한글아이디", "bad name", "ab-cd1", ""]:
            r = self.post(username=bad)
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(User.objects.count(), 0)
        for good in ["abcd", "a" * 20, "a_1_b2"]:
            self.assertEqual(self.post(username=good).status_code, 302, good)

    def test_nickname_and_class_label_rules(self):
        bad = [
            {"nickname": "가"}, {"nickname": "가" * 21}, {"nickname": "홍​길동"},  # 제로폭 공백
            {"nickname": "홍\x07길동"}, {"class_label": ""}, {"class_label": "반" * 31}, {"nickname": "   "},
        ]
        for over in bad:
            self.assertEqual(self.post(**over).status_code, 400, over)
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
        for name, pw in cases.items():
            r = self.post(password=pw, password_confirm=pw)
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
        self.post()
        r = self.post()
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "사용할 수 없는 아이디입니다.", status_code=400)
        self.assertEqual(User.objects.filter(username="ad_user1").count(), 1)

    def test_signup_has_no_attempt_limit_even_from_one_ip(self):
        """6-5b(설계 §10 "가입 시도 제한"): 같은 내부망(강의실 NAT)은 모두 같은 IP 로 보여 IP당 제한이 정상 사용자를 먼저 막았다.
        가입 시도 제한을 두지 않는다 — 한 IP 에서 실패한 시도도, 가입도 몇 번이든 된다(429 없음)."""
        for _ in range(6):
            self.assertEqual(self.post(username="x").status_code, 400)
        for i in range(6):
            self.assertRedirects(self.post(username=f"class_user{i}"), reverse("login"))
        self.assertEqual(User.objects.filter(username__startswith="class_user").count(), 6)

    def test_authenticated_user_is_redirected_from_signup(self):
        self.post()
        self.client.post(reverse("login"), {"username": "ad_user1", "password": PW})
        self.assertRedirects(self.client.get(self.url), reverse("advertiser_home"), fetch_redirect_response=False)
