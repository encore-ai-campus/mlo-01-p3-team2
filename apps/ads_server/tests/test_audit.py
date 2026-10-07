import re

from django.test import TestCase, tag
from django.urls import reverse

from foundation.api import record_audit
from foundation.models import AuditImmutableError, AuditLog, User

PW = "Tr0ub4dor-horse-staple"
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"


def actions():
    return list(AuditLog.objects.order_by("id").values_list("action", flat=True))


@tag("security")
class AuditLogModelTests(TestCase):
    def test_audit_log_is_append_only(self):
        entry = record_audit(None, "test.event")
        entry.action = "changed"
        with self.assertRaises(AuditImmutableError):
            entry.save()
        with self.assertRaises(AuditImmutableError):
            entry.delete()
        with self.assertRaises(AuditImmutableError):
            AuditLog.objects.update(action="x")
        with self.assertRaises(AuditImmutableError):
            AuditLog.objects.all().delete()
        with self.assertRaises(AuditImmutableError):
            AuditLog.objects.filter(pk=entry.pk).delete()
        with self.assertRaises(AuditImmutableError):
            AuditLog.objects.bulk_update([entry], ["action"])
        self.assertEqual(AuditLog.objects.get(pk=entry.pk).action, "test.event")

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

    def test_admin_create_update_and_password_reset_are_audited(self):
        r = self.client.post("/test-admin/foundation/user/add/", {
            "username": "made_by_admin", "nickname": "만든", "class_label": "2반", "role": "advertiser",
            "password1": "Another-Str0ng-pass", "password2": "Another-Str0ng-pass", "usable_password": "true",
        })
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].form.errors)
        created = User.objects.get(username="made_by_admin")
        entry = AuditLog.objects.get(action="account.admin_created")
        self.assertEqual((entry.actor_id, entry.target_id), (self.admin.pk, str(created.pk)))
        self.assertNotIn("Another-Str0ng-pass", str(entry.detail))

        r = self.client.post(f"/test-admin/foundation/user/{created.pk}/change/", {
            "username": "made_by_admin", "nickname": "만든", "class_label": "2반", "role": "advertiser", "_save": "저장",
        })  # is_active 를 보내지 않으면 꺼진다
        self.assertEqual(r.status_code, 302)
        updated = AuditLog.objects.get(action="account.admin_updated")
        self.assertIn("is_active", updated.detail["changed"])
        self.assertFalse(User.objects.get(pk=created.pk).is_active)

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

    def test_user_admin_lists_users_with_kst_column(self):
        r = self.client.get("/test-admin/foundation/user/")
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.content.decode(), r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
