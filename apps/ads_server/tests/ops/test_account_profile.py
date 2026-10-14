"""Step 3-0 S2: 내 정보(닉네임·반) 수정과 비밀번호 변경 서비스(C6 `PATCH /me`, `PUT /me/password`)."""
from django.contrib.auth import HASH_SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, tag
from django.urls import reverse

from foundation.api import ProfileView, change_password, errors, update_profile
from foundation.models import AuditLog, User
from tests.support.factories import PW, make_admin, make_advertiser
from tests.support.cases import Cases

NEW_PW = "Correct-battery-9-staple"


def field_errors(error):
    return error.exception.message_dict


@tag("security")
class UpdateProfileTests(Cases, TestCase):
    def setUp(self):
        self.user = make_advertiser("profile_user")

    def case_changes_only_the_given_fields_and_returns_the_profile(self):
        view = update_profile(self.user, nickname="  새닉네임 ")
        self.assertIsInstance(view, ProfileView)
        self.assertEqual((view.username, view.nickname, view.class_label), ("profile_user", "새닉네임", "1반"))
        row = User.objects.get(pk=self.user.pk)
        self.assertEqual((row.nickname, row.class_label), ("새닉네임", "1반"))  # 공백을 다듬는 가입 규칙 그대로
        self.assertEqual(self.user.nickname, "새닉네임")  # 호출한 쪽의 객체도 맞춘다(같은 요청의 화면이 옛 값을 보이지 않게)
        update_profile(self.user, class_label="2반")
        self.assertEqual(User.objects.get(pk=self.user.pk).class_label, "2반")

    def case_uses_the_signup_rules_and_reports_each_field(self):
        with self.assertRaises(ValidationError) as e:
            update_profile(self.user, nickname="가", class_label="반​")  # 너무 짧음, 보이지 않는 문자
        self.assertEqual(set(field_errors(e)), {"nickname", "class_label"})
        self.assertEqual(User.objects.get(pk=self.user.pk).nickname, "광고주")  # 하나라도 틀리면 아무것도 바꾸지 않는다

    def case_something_must_change(self):
        with self.assertRaises(ValidationError):
            update_profile(self.user)

    def case_audit_records_before_and_after(self):
        update_profile(self.user, nickname="바뀐이름")
        log = AuditLog.objects.get(action="account.profile_updated")
        self.assertEqual((log.actor_id, log.target_id), (self.user.pk, str(self.user.pk)))
        self.assertEqual(log.detail, {"before": {"nickname": "광고주"}, "after": {"nickname": "바뀐이름"}})

    def case_only_an_active_advertiser(self):
        for actor in (make_admin(), User.objects.create_user("inactive_u", PW, nickname="비활성", class_label="1반", is_active=False)):
            with self.assertRaises(errors.Forbidden):
                update_profile(actor, nickname="바꿈")

    def test_account_profile_update_profile(self):
        self.run_cases()


@tag("security")
class ChangePasswordTests(Cases, TestCase):
    def setUp(self):
        self.user = make_advertiser("pw_user")

    def case_wrong_current_password_changes_nothing_and_is_audited(self):
        with self.assertRaises(ValidationError) as e:
            change_password(self.user, "not-the-password", NEW_PW)
        self.assertEqual(set(field_errors(e)), {"current_password"})
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(PW))
        self.assertEqual(AuditLog.objects.filter(action="account.password_change_rejected", actor_id=self.user.pk).count(), 1)

    def case_new_password_gets_the_signup_validation(self):
        for weak in ("short1!", "1234567890123", "password12", "pw_user1234"):  # 길이·숫자만·흔한 것·아이디와 비슷함
            with self.subTest(weak), self.assertRaises(ValidationError) as e:
                change_password(self.user, PW, weak)
            self.assertEqual(set(field_errors(e)), {"new_password"})
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(PW))

    def case_success_changes_the_password_and_audits_without_secrets(self):
        change_password(self.user, PW, NEW_PW)
        row = User.objects.get(pk=self.user.pk)
        self.assertTrue(row.check_password(NEW_PW))
        self.assertFalse(row.check_password(PW))
        self.assertEqual(self.user.password, row.password)  # 호출한 쪽의 객체도 새 해시
        log = AuditLog.objects.get(action="account.password_changed")
        self.assertEqual(log.target_id, str(self.user.pk))
        self.assertNotIn(NEW_PW, str(log.detail))
        self.assertNotIn(PW, str(log.detail))

    def case_other_sessions_are_logged_out_and_the_given_request_keeps_its_session(self):
        other = self.client_class()
        other.force_login(self.user)
        home = reverse("advertiser_home")
        self.assertEqual(other.get(home).status_code, 200)
        request = RequestFactory().post("/")
        request.session, request.user = SessionStore(), self.user
        request.session[HASH_SESSION_KEY] = self.user.get_session_auth_hash()
        before = request.session.session_key
        change_password(self.user, PW, NEW_PW, request=request)
        self.assertRedirects(other.get(home), f"{reverse('login')}?next={home}", fetch_redirect_response=False)  # 다른 기기의 세션은 끝난다
        self.assertEqual(request.session[HASH_SESSION_KEY], User.objects.get(pk=self.user.pk).get_session_auth_hash())  # 이 세션은 새 해시로 유지
        self.assertNotEqual(request.session.session_key, before)  # 세션 키도 새로(고정 공격 방지)

    def case_only_an_active_advertiser(self):
        with self.assertRaises(errors.Forbidden):
            change_password(make_admin(), PW, NEW_PW)

    def test_change_password(self):
        self.run_cases()
