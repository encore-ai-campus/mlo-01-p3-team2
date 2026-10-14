from datetime import timedelta

from axes.models import AccessAttempt
from django.test import RequestFactory, TestCase, override_settings, tag
from django.urls import reverse
from django.utils import timezone

from foundation.models import User
from foundation.net import client_ip
from tests.support.factories import PW


@tag("security")
class LockoutTests(TestCase):
    """Django 6.1 + django-axes 8.x 호환 게이트(설계 §9). 이 테스트가 통과해야 6.1 로 간다."""

    def setUp(self):
        self.url = reverse("login")
        User.objects.create_user("lock_user", PW, nickname="잠금", class_label="1반")
        User.objects.create_user("other_user", PW, nickname="다른", class_label="1반")

    def login(self, username="lock_user", password=PW, ip="10.0.0.1", **extra):
        return self.client.post(self.url, {"username": username, "password": password}, REMOTE_ADDR=ip, **extra)

    def fail(self, times, username="lock_user", ip="10.0.0.1", **extra):
        for _ in range(times):
            self.login(username, "wrong-password-xyz", ip, **extra)

    def authenticated(self):
        return "_auth_user_id" in self.client.session

    def test_locked_after_5_failures(self):
        self.fail(4)
        self.assertEqual(self.login().status_code, 302)  # 4번 실패 뒤에는 아직 잠기지 않는다
        self.client.post(reverse("logout"))
        self.fail(5)
        r = self.login()  # 올바른 비밀번호도 거부
        self.assertContains(r, "잠시 잠겼습니다", status_code=429)
        self.assertFalse(self.authenticated())

    def test_success_resets_failure_counter(self):
        self.fail(4)
        self.assertEqual(self.login().status_code, 302)
        self.client.post(reverse("logout"))
        self.fail(4)
        self.assertEqual(self.login().status_code, 302)

    def test_lock_is_per_username_and_ip(self):
        self.fail(5)
        self.assertEqual(self.login().status_code, 429)
        self.assertEqual(self.login(ip="10.0.0.2").status_code, 302)  # 다른 IP
        self.client.post(reverse("logout"))
        self.assertEqual(self.login("other_user").status_code, 302)  # 같은 IP, 다른 아이디

    def test_unlocked_after_5_minutes(self):
        self.fail(5)
        now = timezone.now()
        AccessAttempt.objects.update(attempt_time=now - timedelta(minutes=4))
        self.assertEqual(self.login().status_code, 429)  # 4분 지난 시점엔 아직 잠김
        AccessAttempt.objects.update(attempt_time=now - timedelta(minutes=6))
        self.assertEqual(self.login().status_code, 302)  # 5분이 지나면 해제

    def test_attempts_during_lockout_do_not_extend_it(self):
        self.fail(5)
        for _ in range(3):
            self.login(password="still-wrong-pass")
        AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=6))
        self.assertEqual(self.login().status_code, 302)

    def test_failed_login_message_is_generic(self):
        wrong_pw = self.login("lock_user", "wrong-password-xyz", ip="10.9.0.1")
        no_user = self.login("no_such_user", "wrong-password-xyz", ip="10.9.0.2")
        self.assertEqual(wrong_pw.status_code, 200)
        self.assertEqual(
            list(wrong_pw.context["form"].non_field_errors()), list(no_user.context["form"].non_field_errors())
        )

    def test_ip_resolution_ignores_untrusted_xff(self):
        """TRUSTED_PROXY_COUNT=0 이면 X-Forwarded-For 를 바꿔도 같은 IP 로 센다(위조로 잠금을 피할 수 없다)."""
        for i in range(5):
            self.fail(1, HTTP_X_FORWARDED_FOR=f"203.0.113.{i}")
        r = self.login(HTTP_X_FORWARDED_FOR="198.51.100.77")
        self.assertEqual(r.status_code, 429)


@tag("security")
class ClientIpTests(TestCase):
    def request(self, xff=None, remote="10.0.0.9"):
        meta = {"REMOTE_ADDR": remote}
        if xff is not None:
            meta["HTTP_X_FORWARDED_FOR"] = xff
        return RequestFactory().get("/", **meta)

    def test_default_uses_remote_addr_only(self):
        self.assertEqual(client_ip(self.request("1.1.1.1")), "10.0.0.9")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_one_trusted_proxy_uses_last_entry(self):
        self.assertEqual(client_ip(self.request("9.9.9.9, 1.2.3.4")), "1.2.3.4")  # 앞쪽 위조 값은 무시

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_two_trusted_proxies_use_second_from_right(self):
        self.assertEqual(client_ip(self.request("9.9.9.9, 1.2.3.4, 10.1.1.1")), "1.2.3.4")

    @override_settings(TRUSTED_PROXY_COUNT=3)
    def test_too_few_entries_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(self.request("1.2.3.4, 5.6.7.8")), "10.0.0.9")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_invalid_ip_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(self.request("not-an-ip")), "10.0.0.9")
        self.assertEqual(client_ip(self.request(None)), "10.0.0.9")
