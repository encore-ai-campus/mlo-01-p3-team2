from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from unittest.mock import patch

from .cohorts import COHORT_CHOICES, allowed_avatars
from .forms import ProfileSetupForm
from .models import Profile

User = get_user_model()


class AccountFlowTests(TestCase):
    password = "Mango!River4820"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="learner", password=cls.password)

    def signup_data(self, username="new_learner", password=None):
        password = password or self.password
        return {"username": username, "cohort": "mlo-1", "password1": password, "password2": password}

    def test_anonymous_map_requires_login(self):
        self.assertRedirects(
            self.client.get(reverse("campus:map")),
            reverse("accounts:login") + "?next=/",
        )

    def test_map_zoom_permission_uses_staff_role_not_username(self):
        user = User.objects.create_user(username="encore", password=self.password)
        self.client.force_login(user)
        regular = self.client.get(reverse("campus:map"))
        self.assertContains(regular, 'id="campusViewConfig"')
        self.assertContains(regular, '"canZoom": false')
        self.assertNotContains(regular, 'id="overviewBtn"')
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        admin = self.client.get(reverse("campus:map"))
        self.assertContains(admin, '"canZoom": true')

    def test_signup_hashes_password_and_opens_setup_before_map(self):
        response = self.client.post(reverse("accounts:signup"), self.signup_data())
        self.assertRedirects(response, reverse("accounts:setup"))
        new_user = User.objects.get(username="new_learner")
        self.assertNotEqual(new_user.password, self.password)
        self.assertTrue(new_user.check_password(self.password))
        self.assertFalse(new_user.is_staff)
        self.assertFalse(new_user.is_superuser)
        self.assertEqual(self.client.session[SESSION_KEY], str(new_user.pk))
        self.assertRedirects(self.client.get(reverse("campus:map")), reverse("accounts:setup"))
        self.assertFalse(new_user.campus_profile.setup_complete)
        self.assertRedirects(self.client.post(reverse("accounts:setup"), {"nickname": "새로운 조원", "avatar": "male-1"}), reverse("campus:map"))
        new_user.campus_profile.refresh_from_db()
        map_response = self.client.get(reverse("campus:map"))
        self.assertEqual(new_user.campus_profile.nickname, "새로운 조원")
        self.assertContains(map_response, "새로운 조원님")
        self.assertContains(map_response, 'id="campusPresenceConfig"')
        self.assertContains(map_response, 'id="mapCanvas"')
        self.assertContains(map_response, '<base href="/static/campus/">')
        self.assertContains(map_response, 'action="/accounts/logout/"')
        self.assertContains(map_response, 'name="csrfmiddlewaretoken"')
        self.assertIn("no-store", map_response.headers["Cache-Control"])

    def test_signup_rejects_duplicate_usernames_including_case_variants(self):
        for username in ["learner", "LEARNER"]:
            with self.subTest(username=username):
                response = self.client.post(
                    reverse("accounts:signup"), self.signup_data(username)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("username", response.context["form"].errors)
                self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(User.objects.count(), 1)

    def test_all_five_cohorts_share_their_course_avatar_pair(self):
        for cohort, _ in COHORT_CHOICES:
            for avatar in allowed_avatars(cohort):
                with self.subTest(cohort=cohort, avatar=avatar):
                    self.client.logout()
                    data = {**self.signup_data(username=cohort + "_" + avatar), "cohort": cohort}
                    self.assertRedirects(self.client.post(reverse("accounts:signup"), data), reverse("accounts:setup"))
                    response = self.client.get(reverse("accounts:setup"))
                    offered = [option[0] for option in response.context["form"].fields["avatar"].choices]
                    self.assertEqual(set(offered), set(allowed_avatars(cohort)))
                    for option in offered:
                        self.assertContains(response, option + "-preview.png")
                    self.assertRedirects(self.client.post(reverse("accounts:setup"), {"nickname": "새 조원", "avatar": avatar}), reverse("campus:map"))
                    profile = Profile.objects.get(user__username=data["username"])
                    self.assertEqual((profile.cohort, profile.avatar, profile.nickname), (cohort, avatar, "새 조원"))
                    self.assertTrue(profile.setup_complete)
                    self.assertEqual(profile.course, cohort.split("-")[0])
                    self.client.logout()
                    self.assertTrue(self.client.login(username=data["username"], password=self.password))
                    self.assertContains(self.client.get(reverse("campus:map")), '"avatar": "' + avatar + '"')

    def test_signup_requires_one_of_the_five_cohorts(self):
        for cohort in ["", "mlo-4", "skn-35", "mlo", "SKN 34기"]:
            response = self.client.post(reverse("accounts:signup"), {**self.signup_data(), "cohort": cohort})
            self.assertEqual(response.status_code, 200)
            self.assertIn("cohort", response.context["form"].errors)
            self.assertEqual(User.objects.count(), 1)
            self.assertFalse(Profile.objects.exists())

    def test_signup_only_shows_account_and_cohort_fields(self):
        response = self.client.get(reverse("accounts:signup"))
        self.assertContains(response, 'name="cohort"')
        for cohort, label in COHORT_CHOICES:
            self.assertContains(response, label)
            self.assertContains(response, 'value="' + cohort + '"')
        for field in ["nickname", "gender", "avatar"]:
            self.assertNotContains(response, 'name="' + field + '"')

    def test_setup_enforces_saved_course_and_rejects_posted_course_or_other_user(self):
        self.client.post(reverse("accounts:signup"), self.signup_data())
        profile = Profile.objects.get(user__username="new_learner")
        for avatar in ["male-2", "female-1", "unknown", ""]:
            response = self.client.post(reverse("accounts:setup"), {"nickname": "새 조원", "avatar": avatar, "cohort": "skn-34", "user": self.user.pk})
            self.assertIn("avatar", response.context["form"].errors)
            profile.refresh_from_db()
            self.assertFalse(profile.setup_complete)
            self.assertEqual(profile.cohort, "mlo-1")
        self.assertRedirects(self.client.post(reverse("accounts:setup"), {"nickname": "새 조원", "avatar": "female-2", "cohort": "skn-34", "user": self.user.pk}), reverse("campus:map"))
        self.assertFalse(Profile.objects.filter(user=self.user).exists())

    def test_initial_selection_is_frozen_and_change_controls_and_endpoint_are_removed(self):
        profile = Profile.objects.create(user=self.user, nickname="내 이름", cohort="skn-36", avatar="male-2")
        self.client.force_login(self.user)
        self.assertRedirects(self.client.post(reverse("accounts:setup"), {"nickname": "새 이름", "avatar": "female-1"}), reverse("campus:map"))
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method("/accounts/avatar/", {"avatar": "female-1"}).status_code, 404)
        profile.refresh_from_db()
        self.assertEqual((profile.avatar, profile.nickname, profile.cohort), ("male-2", "내 이름", "skn-36"))
        response = self.client.get(reverse("campus:map"))
        for text in ['id="avatarBtn"', "캐릭터 변경", '"avatarUrl"', "/accounts/avatar/"]:
            self.assertNotContains(response, text)

    def test_pending_setup_requires_login_csrf_and_blocks_map_and_nickname_shortcuts(self):
        self.assertRedirects(self.client.get(reverse("accounts:setup")), reverse("accounts:login") + "?next=/accounts/setup/")
        self.client.post(reverse("accounts:signup"), self.signup_data())
        for route in ["campus:map", "accounts:nickname", "accounts:signup"]:
            self.assertRedirects(self.client.get(reverse(route)), reverse("accounts:setup"))
        csrf_client = Client(enforce_csrf_checks=True)
        user = User.objects.get(username="new_learner")
        csrf_client.force_login(user)
        self.assertEqual(csrf_client.post(reverse("accounts:setup"), {"nickname": "새 조원", "avatar": "male-1"}).status_code, 403)
        self.assertFalse(Profile.objects.get(user=user).setup_complete)

    def test_setup_requires_valid_nickname(self):
        self.client.post(reverse("accounts:signup"), self.signup_data())
        for nickname in ["", "가", "가" * 21, "<script>", "   "]:
            response = self.client.post(reverse("accounts:setup"), {"nickname": nickname, "avatar": "male-1"})
            self.assertIn("nickname", response.context["form"].errors)
            self.assertFalse(Profile.objects.get(user__username="new_learner").setup_complete)

    def test_incomplete_signup_resumes_setup_after_logout_and_login(self):
        self.client.post(reverse("accounts:signup"), self.signup_data())
        self.client.post(reverse("accounts:logout"))
        response = self.client.post(reverse("accounts:login"), {"username": "new_learner", "password": self.password, "next": "/"})
        self.assertRedirects(response, reverse("accounts:setup"))

    def test_first_setup_write_wins_when_another_tab_finishes_during_validation(self):
        self.client.post(reverse("accounts:signup"), self.signup_data())
        profile = Profile.objects.get(user__username="new_learner")
        original = ProfileSetupForm.is_valid

        def other_tab_finishes(form):
            valid = original(form)
            Profile.objects.filter(pk=profile.pk).update(nickname="먼저 정한 이름", avatar="female-2", setup_complete=True)
            return valid

        with patch.object(ProfileSetupForm, "is_valid", other_tab_finishes):
            self.assertRedirects(self.client.post(reverse("accounts:setup"), {"nickname": "나중 이름", "avatar": "male-1"}), reverse("campus:map"))
        profile.refresh_from_db()
        self.assertEqual((profile.nickname, profile.avatar), ("먼저 정한 이름", "female-2"))

    def test_nickname_page_requires_login(self):
        self.assertRedirects(
            self.client.get(reverse("accounts:nickname")),
            reverse("accounts:login") + "?next=/accounts/nickname/",
        )

    def test_existing_account_can_set_and_update_nickname_without_changing_login(self):
        self.client.force_login(self.user)
        for nickname in ["첫 닉네임", "변경한 이름"]:
            response = self.client.post(reverse("accounts:nickname"), {"nickname": nickname})
            self.assertRedirects(response, reverse("campus:map"))
            self.assertContains(self.client.get(reverse("campus:map")), nickname + "님")
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "learner")
        self.assertTrue(self.user.check_password(self.password))
        self.client.logout()
        self.assertTrue(self.client.login(username="learner", password=self.password))

    def test_nickname_update_does_not_change_another_account(self):
        other = User.objects.create_user(username="other")
        other_profile = Profile.objects.create(user=other, nickname="다른 조원")
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:nickname"), {"nickname": "내 닉네임", "user": other.pk})
        other_profile.refresh_from_db()
        self.assertEqual(other_profile.nickname, "다른 조원")
        self.assertEqual(Profile.objects.get(user=self.user).nickname, "내 닉네임")

    def test_nickname_update_is_validated_and_csrf_protected(self):
        Profile.objects.create(user=self.user, nickname="기존 이름")
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:nickname"), {"nickname": "<img src=x>"})
        self.assertIn("nickname", response.context["form"].errors)
        self.assertEqual(Profile.objects.get(user=self.user).nickname, "기존 이름")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse("accounts:nickname"), {"nickname": "바꿀 이름"}).status_code, 403)

    def test_signup_rejects_invalid_username(self):
        response = self.client.post(
            reverse("accounts:signup"), self.signup_data("invalid username")
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_signup_rejects_mismatched_passwords(self):
        data = self.signup_data()
        data["password2"] = "Another!Password4820"
        response = self.client.post(reverse("accounts:signup"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_signup_rejects_weak_passwords(self):
        for password in ["ab!", "123456789", "password", "new_learner123"]:
            with self.subTest(password=password):
                response = self.client.post(
                    reverse("accounts:signup"), self.signup_data(password=password)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("password2", response.context["form"].errors)
                self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(User.objects.count(), 1)

    def test_login_persists_session_and_logout_removes_access(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "learner", "password": self.password},
        )
        self.assertRedirects(response, reverse("campus:map"))
        self.assertContains(self.client.get(reverse("campus:map")), "learner님")
        self.assertRedirects(
            self.client.post(reverse("accounts:logout")), reverse("accounts:login")
        )
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertRedirects(
            self.client.get(reverse("campus:map")),
            reverse("accounts:login") + "?next=/",
        )

    def test_exit_confirmation_uses_csrf_protected_logout_form(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.get(reverse("campus:map"))
        self.assertContains(response, 'id="exitDialog"')
        self.assertContains(response, "나가시겠습니까?")
        self.assertContains(response, 'id="exitYes"')
        self.assertContains(response, 'id="exitNo"')
        self.assertContains(response, 'id="campusLogoutForm"')
        self.assertContains(response, 'method="post" action="/accounts/logout/"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertRedirects(
            csrf_client.post(
                reverse("accounts:logout"),
                {"csrfmiddlewaretoken": csrf_client.cookies[settings.CSRF_COOKIE_NAME].value},
            ),
            reverse("accounts:login"),
        )
        self.assertNotIn(SESSION_KEY, csrf_client.session)
        self.assertRedirects(
            csrf_client.get(reverse("campus:map")),
            reverse("accounts:login") + "?next=/",
        )

    def test_invalid_login_stays_on_form_without_authenticating(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "learner", "password": "wrong-password"},
        )
        self.assertContains(response, "아이디 또는 비밀번호를 확인해 주세요.")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "learner", "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_ignores_external_redirect(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "learner",
                "password": self.password,
                "next": "https://untrusted.example/",
            },
        )
        self.assertRedirects(response, reverse("campus:map"))

    def test_authenticated_user_returns_to_map_from_account_forms(self):
        self.client.force_login(self.user)
        for page in ["accounts:login", "accounts:signup"]:
            with self.subTest(page=page):
                self.assertRedirects(self.client.get(reverse(page)), reverse("campus:map"))

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    def test_all_account_posts_require_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        for page, data in [
            ("accounts:signup", self.signup_data()),
            ("accounts:login", {"username": "learner", "password": self.password}),
        ]:
            with self.subTest(page=page):
                self.assertEqual(csrf_client.post(reverse(page), data).status_code, 403)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse("accounts:logout")).status_code, 403)
        self.assertEqual(csrf_client.session[SESSION_KEY], str(self.user.pk))
        self.assertEqual(User.objects.count(), 1)
