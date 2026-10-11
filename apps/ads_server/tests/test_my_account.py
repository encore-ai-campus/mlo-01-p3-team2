"""Step 3-2f 광고주 내 정보: 닉네임·반 수정, 비밀번호 변경. 현재 비밀번호 확인은 로그인 잠금(axes)과 같은 계수를 쓴다(설계 §10 "비밀번호 변경의 시도 제한", 위협 모델 T43)."""
from django.test import Client, TestCase, tag
from django.urls import reverse

from foundation.models import AuditLog, User
from tests.factories import PW

NEW_PW = "Correct-battery-9-staple"
WRONG = "wrong-password-xyz"


class MyAccountBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me_user", PW, nickname="광고주", class_label="1반")
        self.client.force_login(self.user)
        self.page = reverse("my_account")
        self.password_url = reverse("my_password")

    def change(self, current=PW, new=NEW_PW, confirm=None, ip="10.0.0.1", client=None):
        return (client or self.client).post(self.password_url, {"current_password": current, "new_password": new,
                                                               "new_password_confirm": confirm or new}, REMOTE_ADDR=ip)

    def login_fail(self, times, ip="10.0.0.1"):
        anonymous = Client()
        for _ in range(times):
            anonymous.post(reverse("login"), {"username": "me_user", "password": WRONG}, REMOTE_ADDR=ip)


@tag("security")
class ProfilePageTests(MyAccountBase):
    def test_page_shows_the_profile_without_the_password(self):
        r = self.client.get(self.page)
        self.assertContains(r, 'value="광고주"')
        self.assertContains(r, "me_user")
        self.assertContains(r, 'aria-current="page"')  # 내비게이션의 현재 위치

    def test_update_profile(self):
        r = self.client.post(self.page, {"nickname": "새이름", "class_label": "2반"})
        self.assertRedirects(r, self.page)
        self.assertEqual(User.objects.get(pk=self.user.pk).nickname, "새이름")
        self.assertContains(self.client.get(self.page), "새이름(2반)")  # 머리글도 새 값

    def test_profile_rules_come_from_the_service(self):
        self.assertContains(self.client.post(self.page, {"nickname": "가", "class_label": "1반"}), "닉네임", status_code=400)
        self.assertEqual(User.objects.get(pk=self.user.pk).nickname, "광고주")


@tag("security")
class PasswordChangePageTests(MyAccountBase):
    def test_change_keeps_this_session_and_ends_others(self):
        other = Client()
        other.force_login(self.user)
        self.assertRedirects(self.change(), self.page)
        self.assertEqual(self.client.get(self.page).status_code, 200)  # 이 기기는 그대로
        self.assertEqual(other.get(self.page).status_code, 302)  # 다른 기기는 로그인으로
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(NEW_PW))

    def test_wrong_current_password_or_mismatch(self):
        self.assertContains(self.change(current=WRONG), "현재 비밀번호가 맞지 않습니다", status_code=400)
        self.assertContains(self.change(confirm="Another-battery-9-x"), "일치하지 않습니다", status_code=400)
        self.assertContains(self.change(new="1234567890123"), "new_password", status_code=400)  # 가입과 같은 검증(오류가 그 칸에)
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(PW))
        self.assertEqual(AuditLog.objects.filter(action="account.password_change_rejected").count(), 1)

    def test_five_wrong_current_passwords_lock_like_the_login(self):
        for _ in range(4):
            self.assertEqual(self.change(current=WRONG).status_code, 400)
        self.assertEqual(self.change(current=WRONG).status_code, 429)  # 5번째 실패에서 잠금
        self.assertContains(self.change(), "잠시 잠겼습니다", status_code=429)  # 잠금 중에는 맞는 비밀번호도 거절
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(PW))
        self.assertEqual(Client().post(reverse("login"), {"username": "me_user", "password": PW}, REMOTE_ADDR="10.0.0.1").status_code, 429)  # 로그인도 잠김
        self.assertEqual(AuditLog.objects.filter(action="account.password_change_rejected").count(), 6)  # 틀린 시도는 그대로 감사 로그에

    def test_login_and_change_failures_are_counted_together(self):
        self.login_fail(3)
        self.assertEqual(self.change(current=WRONG).status_code, 400)
        self.assertEqual(self.change(current=WRONG).status_code, 429)  # 3 + 2 = 5

    def test_another_ip_is_not_locked(self):
        for _ in range(5):
            self.change(current=WRONG)
        self.assertRedirects(self.change(ip="10.0.0.2"), self.page)  # 피해자는 보통 IP 가 다르다
