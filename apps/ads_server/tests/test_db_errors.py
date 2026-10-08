from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from foundation.dberrors import is_unique_violation
from foundation.models import User


class UniqueViolationTests(TestCase):
    def raised(self, **kw):
        values = dict(username="dup_user", role="ADVERTISER", nickname="닉", class_label="1반")
        values.update(kw)
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            User.objects.create(**values)
        return caught.exception

    def test_a_unique_violation_is_told_apart_from_other_integrity_errors(self):
        User.objects.create(username="dup_user", role="ADVERTISER", nickname="닉", class_label="1반")
        self.assertTrue(is_unique_violation(self.raised()))
        self.assertFalse(is_unique_violation(self.raised(username=None)))  # NOT NULL 위반
        with connection.cursor() as cur, self.assertRaises(IntegrityError) as caught, transaction.atomic():
            cur.execute("INSERT INTO billing_wallet (wallet_id, owner_id, balance, created_at) VALUES ('x', 'nobody', 9007199254740993, '2026-01-01')")
        self.assertFalse(is_unique_violation(caught.exception))  # CHECK 위반

    def test_an_unknown_backend_error_is_never_called_a_duplicate(self):
        self.assertFalse(is_unique_violation(IntegrityError("duplicate-looking message")))
