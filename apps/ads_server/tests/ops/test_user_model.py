import datetime

from django.template import Context, Template
from django.test import SimpleTestCase, TestCase

from foundation.models import Role, User


class UserModelTests(TestCase):
    def test_user_has_no_email_or_name_fields(self):
        names = {f.name for f in User._meta.get_fields()}
        for forbidden in ("email", "first_name", "last_name", "phone"):
            self.assertNotIn(forbidden, names)

    def test_create_user_defaults_to_advertiser(self):
        u = User.objects.create_user("adv_two", "pw", nickname="닉", class_label="1반")
        self.assertEqual(u.role, Role.ADVERTISER)
        self.assertFalse(u.is_superuser)

    def test_create_superuser_sets_admin_role(self):
        u = User.objects.create_superuser("root_one", "pw", nickname="관리", class_label="-", role=Role.ADVERTISER)  # 역할 인자는 무시한다
        self.assertEqual(u.role, Role.ADMIN)
        self.assertTrue(u.is_superuser)

    def test_is_staff_only_for_active_admin(self):
        adv = User.objects.create_user("adv_three", "pw", nickname="닉", class_label="1반")
        admin = User.objects.create_superuser("root_three", "pw", nickname="관리", class_label="-")
        self.assertFalse(adv.is_staff)
        self.assertTrue(admin.is_staff)
        admin.is_active = False
        self.assertFalse(admin.is_staff)

    def test_created_at_is_utc(self):
        u = User.objects.create_user("adv_four", "pw", nickname="닉", class_label="1반")
        u.refresh_from_db()
        self.assertIsNotNone(u.created_at.tzinfo)
        self.assertEqual(u.created_at.utcoffset(), datetime.timedelta(0))


class KstFilterTests(SimpleTestCase):
    def render(self, value):
        return Template("{% load kst %}{{ v|kst }}").render(Context({"v": value}))

    def test_kst_filter_displays_plus_9(self):
        utc = datetime.datetime(2026, 10, 7, 0, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(self.render(utc), "2026-10-07 09:00")

    def test_kst_filter_crosses_date_boundary(self):
        utc = datetime.datetime(2026, 10, 7, 20, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(self.render(utc), "2026-10-08 05:30")

    def test_kst_filter_none_is_empty(self):
        self.assertEqual(self.render(None), "")

    def test_kst_filter_rejects_naive_datetime(self):
        with self.assertRaises(ValueError):
            Template("{% load kst %}{{ v|kst }}").render(Context({"v": datetime.datetime(2026, 10, 7)}))
