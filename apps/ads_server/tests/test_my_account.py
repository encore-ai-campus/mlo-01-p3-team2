"""Step 3-2f 광고주 내 정보: 닉네임·반 수정, 비밀번호 변경. 현재 비밀번호 확인은 로그인 잠금(axes)과 같은 계수를 쓴다(설계 §10 "비밀번호 변경의 시도 제한", 위협 모델 T43)."""
import threading

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, tag
from django.urls import reverse

from foundation.models import AuditLog, User
from foundation.api import set_advertiser_active
from tests.concurrency import WAIT, Worker
from tests.factories import PW, make_admin

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


@tag("security")
class PasswordChangeRaceTests(TransactionTestCase):
    """외부 검토(3-1d) P2 와 같은 결함: 현재 비밀번호를 확인한 뒤 저장 직전까지 계정이 바뀌어도(비활성화) 진행 중이던 변경이 저장하고 세션을 갱신해,
    다시 활성화하면 그 세션이 살아났다. 잠근 최신 행을 이 요청을 인증한 세션과 대조해 거절한다."""

    def setUp(self):
        self.user = User.objects.create_user("race_user", PW, nickname="광고주", class_label="1반")
        self.client = Client()
        self.client.force_login(self.user)

    def change_with(self, in_between):
        """현재 비밀번호를 확인한 뒤, 저장 전 행 잠금 직전에 멈춘 사이 `in_between()` 을 커밋한다. 변경 요청의 응답을 돌려준다."""
        paused, release = threading.Event(), threading.Event()

        def hook(execute, sql, params, many, context):
            if "FOR UPDATE" in sql and "`foundation_user`" in sql and not paused.is_set():
                paused.set()
                assert release.wait(WAIT)
            return execute(sql, params, many, context)

        def change():
            with connection.execute_wrapper(hook):
                return self.client.post(reverse("my_password"), {"current_password": PW, "new_password": NEW_PW, "new_password_confirm": NEW_PW})
        worker = Worker(change)
        worker.start()
        self.assertTrue(paused.wait(WAIT), "저장 직전에 이르지 않았다")
        in_between()
        release.set()
        worker.join(WAIT)
        self.assertEqual(worker.errors, [])
        self.assertContains(worker.result, "계정 상태가 바뀌었습니다", status_code=400)
        return worker.result

    def test_a_deactivation_in_between_is_not_undone_by_an_in_flight_change(self):
        self.change_with(lambda: set_advertiser_active(make_admin(), self.user.pk, False, "스팸 소재"))
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(PW))  # 바뀌지 않았다
        set_advertiser_active(make_admin(), self.user.pk, True)
        self.assertEqual(self.client.get(reverse("my_account")).status_code, 302)  # 다시 활성화해도 그 세션은 끝난 채

    def test_an_admin_reset_in_between_is_not_overridden_by_an_in_flight_change(self):
        """계정은 활성 그대로지만 관리자가 비밀번호를 초기화했다(탈취 대응) — 그 전에 인증한 요청이 덮어쓰고 세션을 이어 가면 안 된다."""
        def reset():
            admin = Client()
            admin.force_login(make_admin())
            r = admin.post(reverse("admin:auth_user_password_change", args=[self.user.pk]),
                           {"password1": "Admin-Reset-5-pass", "password2": "Admin-Reset-5-pass", "usable_password": "true"})
            self.assertEqual(r.status_code, 302)
        self.change_with(reset)
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password("Admin-Reset-5-pass"))
        self.assertEqual(self.client.get(reverse("my_account")).status_code, 302)

    def test_a_shell_style_deactivation_in_between_is_respected_too(self):
        """셸에서 is_active 만 끈 경우(폐기 버전은 그대로 — 운영 안내상 쓰지 않는 길)에도 진행 중인 변경이 저장하지 않는다."""
        self.change_with(lambda: User.objects.filter(pk=self.user.pk).update(is_active=False))
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(PW))
