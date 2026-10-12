from django.db import IntegrityError, transaction
from django.test import TestCase, tag
from django.urls import reverse

from foundation.api import record_audit
from foundation.models import AppendOnlyError, AuditLog, User

PW = "Tr0ub4dor-horse-staple"
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"


def actions():
    return list(AuditLog.objects.order_by("created_at", "log_id").values_list("action", flat=True))


@tag("security")
class AuditLogModelTests(TestCase):
    def test_audit_log_is_append_only(self):
        entry = record_audit(None, "test.event")
        entry.action = "changed"
        with self.assertRaises(AppendOnlyError):
            entry.save()
        with self.assertRaises(AppendOnlyError):
            entry.delete()
        with self.assertRaises(AppendOnlyError):
            AuditLog.objects.update(action="x")
        with self.assertRaises(AppendOnlyError):
            AuditLog.objects.all().delete()
        with self.assertRaises(AppendOnlyError):
            AuditLog.objects.filter(pk=entry.pk).delete()
        with self.assertRaises(AppendOnlyError):
            AuditLog.objects.bulk_update([entry], ["action"])
        self.assertEqual(AuditLog.objects.get(pk=entry.pk).action, "test.event")

    def test_existing_row_cannot_be_overwritten_by_a_new_instance_or_upsert(self):
        """`_state.adding` 은 Python 인스턴스 상태일 뿐이다. 같은 PK 의 새 인스턴스·upsert 로 기존 행을 바꿀 수 없어야 한다."""
        entry = record_audit(None, "test.original")
        with self.assertRaises((IntegrityError, AppendOnlyError)), transaction.atomic():
            AuditLog(pk=entry.pk, action="review.overwritten").save()
        with self.assertRaises(AppendOnlyError):
            AuditLog(pk=entry.pk, action="review.overwritten").save(force_update=True)
        with self.assertRaises(AppendOnlyError):
            AuditLog(pk=entry.pk, action="review.overwritten").save(update_fields=["action"])
        with self.assertRaises(AppendOnlyError):
            AuditLog.objects.bulk_create(
                [AuditLog(pk=entry.pk, action="review.overwritten")],
                update_conflicts=True, update_fields=["action"], unique_fields=["log_id"],
            )
        with self.assertRaises((IntegrityError, AppendOnlyError)), transaction.atomic():
            AuditLog.objects.update_or_create(pk=entry.pk, defaults={"action": "review.overwritten"})
        AuditLog.objects.bulk_create([AuditLog(pk=entry.pk, action="review.overwritten")], ignore_conflicts=True)  # 건너뛸 뿐 덮어쓰지 않는다
        self.assertEqual(AuditLog.objects.get(pk=entry.pk).action, "test.original")
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_audit_detail_strips_secret_keys(self):
        detail = {
            "password": "p", "new_password1": "p", "token": "t", "Authorization": "a", "csrfmiddlewaretoken": "c",
            "api_key": "k", "x-media-key": "m", "sessionid": "s", "secret": "s", "key": "k2", "cookie": "c",
            "nested": {"api_key": "k", "ok": 1}, "list": [{"secret": "s", "fine": 2}],
            "keyword": "kept", "class_label": "1반",
        }
        entry = record_audit(None, "test.redact", detail=detail)
        stored = AuditLog.objects.get(pk=entry.pk).detail
        self.assertEqual(stored, {"nested": {"ok": 1}, "list": [{"fine": 2}], "keyword": "kept", "class_label": "1반"})

    def test_long_values_are_truncated_and_oversized_detail_replaced(self):
        entry = record_audit(None, "test.long", detail={"v": "x" * 10_000})
        self.assertEqual(len(AuditLog.objects.get(pk=entry.pk).detail["v"]), 500)
        big = record_audit(None, "test.big", detail={f"k{i}": "y" * 400 for i in range(40)})
        self.assertEqual(AuditLog.objects.get(pk=big.pk).detail, {"truncated": True})

    def test_target_forms(self):
        user = User.objects.create_user("audit_t1", PW, nickname="t", class_label="1")
        by_instance = record_audit(None, "t.instance", target=user)
        by_tuple = record_audit(None, "t.tuple", target=("campaign", "abc"))
        self.assertEqual((by_instance.target_type, by_instance.target_id), ("foundation.user", str(user.pk)))
        self.assertEqual((by_tuple.target_type, by_tuple.target_id), ("campaign", "abc"))


@tag("security")
class AuditEventTests(TestCase):
    def signup(self, username="aud_user1", ip="10.20.0.1"):
        return self.client.post(
            reverse("signup"),
            {"username": username, "password": PW, "password_confirm": PW, "nickname": "닉네임", "class_label": "1반"},
            REMOTE_ADDR=ip,
        )

    def test_signup_and_login_events_recorded(self):
        r = self.signup()
        self.assertEqual(r.status_code, 302)
        entry = AuditLog.objects.get(action="account.signup")
        user = User.objects.get(username="aud_user1")
        self.assertEqual(entry.actor_id, user.pk)
        self.assertEqual(entry.target_id, str(user.pk))
        self.assertEqual(entry.ip, "10.20.0.1")
        self.assertEqual(entry.request_id, r["X-Request-ID"])
        self.assertNotIn(PW, str(entry.detail))

        self.client.post(reverse("login"), {"username": "aud_user1", "password": PW}, REMOTE_ADDR="10.20.0.1")
        self.assertIn("auth.login_success", actions())
        self.client.post(reverse("logout"), REMOTE_ADDR="10.20.0.1")
        self.assertIn("auth.logout", actions())

    def test_failed_login_and_lockout_recorded_without_password(self):
        self.signup()
        marker = "Wr0ng-marker-pw-98765"
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "aud_user1", "password": marker}, REMOTE_ADDR="10.20.0.2")
        self.assertEqual(actions().count("auth.login_failed") >= 5, True)
        self.assertIn("auth.lockout", actions())
        for entry in AuditLog.objects.all():
            self.assertNotIn(marker, f"{entry.detail} {entry.action} {entry.actor_username}")
        failed = AuditLog.objects.filter(action="auth.login_failed").first()
        self.assertEqual(failed.detail, {"username": "aud_user1"})

    def test_login_failed_never_records_a_password_typed_into_the_username_field(self):
        accidental = "MyReal-Passw0rd!"  # 형식에 맞지 않는 아이디 → 기록하지 않는다
        self.client.post(reverse("login"), {"username": accidental, "password": "x"}, REMOTE_ADDR="10.20.0.3")
        failed = AuditLog.objects.get(action="auth.login_failed")
        self.assertEqual(failed.detail, {"username": None})
        self.assertNotIn(accidental, str(list(AuditLog.objects.values())))


@tag("security")
class AdminAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root_aud", PW, nickname="관리", class_label="-")
        self.client.force_login(self.admin, backend=MODEL_BACKEND)

    def test_admin_update_and_password_reset_are_audited(self):
        """사용자 관리 화면은 계정을 추가하지 않는다(설계 §10) — 수정과 비밀번호 초기화만 감사 로그에 남는지 본다."""
        created = User.objects.create_user("made_by_signup", PW, nickname="만든", class_label="2반")
        r = self.client.post(f"/test-admin/foundation/user/{created.pk}/change/", {
            "username": "made_by_signup", "nickname": "바꾼", "class_label": "2반", "role": "advertiser", "_save": "저장",
        })
        self.assertEqual(r.status_code, 302)
        updated = AuditLog.objects.get(action="account.admin_updated")
        self.assertEqual(updated.detail["changed"], ["nickname"])  # 광고주의 활성 여부는 여기서 바뀌지 않는다(운영 화면에서만 — test_operator_advertisers)
        self.assertTrue(User.objects.get(pk=created.pk).is_active)

        r = self.client.post(f"/test-admin/foundation/user/{created.pk}/password/", {
            "password1": "Reset-Str0ng-pass-1", "password2": "Reset-Str0ng-pass-1", "usable_password": "true",
        })
        self.assertEqual(r.status_code, 302)
        reset = AuditLog.objects.get(action="account.password_reset_by_admin")
        self.assertEqual(reset.target_id, str(created.pk))
        self.assertNotIn("Reset-Str0ng", str(list(AuditLog.objects.values())))

    def test_audit_log_admin_is_read_only(self):
        entry = record_audit(None, "test.readonly")
        self.assertEqual(self.client.get("/test-admin/foundation/auditlog/").status_code, 200)
        self.assertEqual(self.client.get("/test-admin/foundation/auditlog/add/").status_code, 403)
        self.assertEqual(self.client.get(f"/test-admin/foundation/auditlog/{entry.pk}/change/").status_code, 200)  # 보기만
        self.assertEqual(self.client.post(f"/test-admin/foundation/auditlog/{entry.pk}/change/", {"action": "x"}).status_code, 403)
        self.assertEqual(self.client.post(f"/test-admin/foundation/auditlog/{entry.pk}/delete/", {"post": "yes"}).status_code, 403)
        self.assertEqual(AuditLog.objects.get(pk=entry.pk).action, "test.readonly")

    def test_every_project_model_admin_except_users_is_read_only(self):
        """관리자 화면은 프로젝트 모델을 직접 추가·수정·삭제하지 못한다(변경은 서비스 함수로만). 사용자 관리만 예외다."""
        from django.apps import apps
        from django.contrib import admin
        from django.test import RequestFactory

        from tests.boundaries.test_layers import LAYERS

        request = RequestFactory().get("/")
        request.user = self.admin
        checked = []
        for model in apps.get_models():
            if model._meta.app_label not in {*LAYERS, "axes"} or model is User or not admin.site.is_registered(model):
                continue
            model_admin = admin.site.get_model_admin(model)
            permissions = (model_admin.has_add_permission(request), model_admin.has_change_permission(request), model_admin.has_delete_permission(request))
            self.assertEqual(permissions, (False, False, False), model.__name__)
            self.assertEqual(model_admin.get_actions(request), {}, model.__name__)  # 묶음 동작(삭제·axes 정리)도 없다
            checked.append(model.__name__)
        self.assertEqual(len(checked), 18, checked)  # 공회전이 아니다: 감사 로그 1, 마스터 5(매체 비활성화 기록 6-1a), 캠페인 5, 지갑·원장 3, 결정 1, 로그인 잠금 기록 3(axes, 위협 모델 T44)

    def test_login_lockout_records_are_read_only(self):
        """잠금 기록을 화면에서 지우거나 고쳐 잠금을 풀 수 없다(설계 §10 "로그인 잠금 기록 관리", 위협 모델 T44). 급할 때는 서버 명령(axes_reset_username)."""
        from datetime import timedelta

        from axes.models import AccessAttempt, AccessFailureLog, AccessLog
        from django.utils import timezone

        old = timezone.now() - timedelta(days=1)  # 만료된 시도도 화면의 정리 동작으로 지우지 못한다
        attempt = AccessAttempt.objects.create(username="locked", ip_address="10.0.0.9", user_agent="ua", failures_since_start=5, attempt_time=old)
        log = AccessLog.objects.create(username="locked", ip_address="10.0.0.9", user_agent="ua")
        failure = AccessFailureLog.objects.create(username="locked", ip_address="10.0.0.9", user_agent="ua", locked_out=True)
        counts = lambda: (AccessAttempt.objects.count(), AccessLog.objects.count(), AccessFailureLog.objects.count())  # noqa: E731
        before = counts()
        for name, obj in (("accessattempt", attempt), ("accesslog", log), ("accessfailurelog", failure)):
            base = f"/test-admin/axes/{name}/"
            self.assertEqual(self.client.get(base).status_code, 200, name)  # 목록·상세 보기는 남는다
            self.assertEqual(self.client.get(f"{base}{obj.pk}/change/").status_code, 200, name)
            self.assertEqual(self.client.post(f"{base}{obj.pk}/delete/", {"post": "yes"}).status_code, 403, name)
            self.assertEqual(self.client.post(f"{base}{obj.pk}/change/", {"username": "x"}).status_code, 403, name)
            for action in ("delete_selected", "cleanup_expired_attempts"):
                self.client.post(base, {"action": action, "_selected_action": [obj.pk], "post": "yes"})
        self.assertEqual(counts(), before)
        self.assertEqual(AccessAttempt.objects.get(pk=attempt.pk).username, "locked")

    def test_user_admin_lists_users_with_kst_column(self):
        r = self.client.get("/test-admin/foundation/user/")
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.content.decode(), r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


@tag("security")
class AdminSelfPasswordAuditTests(TestCase):
    NEW = "Brand-New-Str0ng-pass-9"

    def setUp(self):
        self.admin = User.objects.create_superuser("root_pw", PW, nickname="관리", class_label="-")
        self.client.force_login(self.admin, backend=MODEL_BACKEND)

    def test_own_password_change_is_audited_once_without_the_password(self):
        r = self.client.post("/test-admin/password_change/", {
            "old_password": PW, "new_password1": self.NEW, "new_password2": self.NEW,
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.get(pk=self.admin.pk).check_password(self.NEW))
        entry = AuditLog.objects.get(action="account.password_changed")
        self.assertEqual((entry.actor_id, entry.target_id), (self.admin.pk, str(self.admin.pk)))
        self.assertEqual(AuditLog.objects.filter(action="account.password_changed").count(), 1)
        dump = str(list(AuditLog.objects.values()))
        self.assertNotIn(self.NEW, dump)
        self.assertNotIn(PW, dump)

    def test_failed_password_change_is_not_audited_as_success(self):
        r = self.client.post("/test-admin/password_change/", {
            "old_password": "wrong-old-password", "new_password1": self.NEW, "new_password2": self.NEW,
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action="account.password_changed").exists())
        self.assertTrue(User.objects.get(pk=self.admin.pk).check_password(PW))
        self.assertNotIn("wrong-old-password", str(list(AuditLog.objects.values())))

    def test_get_of_the_form_is_not_audited(self):
        self.assertEqual(self.client.get("/test-admin/password_change/").status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action="account.password_changed").exists())
