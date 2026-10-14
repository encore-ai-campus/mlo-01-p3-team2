"""DB 오류 분류(`foundation/dberrors.py`): 유일 제약 위반은 다른 무결성 오류(NOT NULL·CHECK)와 구분한다. DB-1c(S6): 교착(1213)·잠금 대기 초과(1205)는 **실패가 아니라 일시 오류**다.

MySQL 에서는 정상 동작의 일부다(서버가 트랜잭션 하나를 되돌린다). 반응 처리가 이것을 실패로 세면 정상 반응의 `attempts` 가 올라 상한(5)에서 자동 재처리에서 빠진다.
그래서 횟수를 올리지 않고 다음 주기에 다시 한다. API 는 `OperationalError` 를 503 + `Retry-After` 로 바꾼다(`serving_api/auth.py`).
"""
import threading
import uuid
from random import Random
from unittest import mock

from django.db import IntegrityError, OperationalError, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings, tag

from foundation.api import is_transient_lock_error
from foundation.dberrors import is_unique_violation
from foundation.models import User
from records import api as records
from records.models import Reaction
from tests.concurrency import WAIT, Worker
from tests.factories import NOW, SUBJECT, World

DEADLOCK = OperationalError(1213, "Deadlock found when trying to get lock; try restarting transaction")
LOCK_TIMEOUT = OperationalError(1205, "Lock wait timeout exceeded; try restarting transaction")


@tag("security")
class ClassificationTests(TestCase):
    def test_only_deadlock_and_lock_wait_timeout_are_transient(self):
        self.assertTrue(is_transient_lock_error(DEADLOCK))
        self.assertTrue(is_transient_lock_error(LOCK_TIMEOUT))
        for other in (OperationalError(2013, "Lost connection"), OperationalError(1146, "no table"), OperationalError("disk I/O error"), RuntimeError("x"), ValueError(1213)):
            self.assertFalse(is_transient_lock_error(other), other)

    def test_a_wrapped_driver_error_is_recognised_through_its_cause(self):
        import MySQLdb

        try:
            try:
                raise MySQLdb.OperationalError(1213, "Deadlock")
            except MySQLdb.OperationalError as driver:
                raise OperationalError("wrapped") from driver
        except OperationalError as wrapped:
            self.assertTrue(is_transient_lock_error(wrapped))


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class ProcessingRetriesTests(TestCase):
    def setUp(self):
        self.w = World()
        self.media = self.w.slot.media_id
        self.decision = records.decide(self.media, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(self.media, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        self.inbox_id = view.inbox_id

    def row(self):
        return Reaction.objects.get(pk=self.inbox_id)

    def test_a_deadlock_does_not_count_as_a_failure_and_leaves_no_trace(self):
        with mock.patch("records.processing.billing.charge_for_reaction", side_effect=DEADLOCK), self.assertRaises(OperationalError):
            records.process_reaction(self.inbox_id, now=NOW)
        row = self.row()
        self.assertEqual((row.status, row.attempts, row.basis), ("RECEIVED", 0, None))  # 되돌려졌고 횟수는 그대로다
        self.assertEqual(records.process_reaction(self.inbox_id, now=NOW), "ACCEPTED")  # 다시 하면 된다

    def test_a_real_failure_still_counts(self):
        with mock.patch("records.processing.billing.charge_for_reaction", side_effect=OperationalError(2013, "Lost connection")), self.assertRaises(OperationalError):
            records.process_reaction(self.inbox_id, now=NOW)
        self.assertEqual(self.row().attempts, 1)

    def test_a_reaction_that_keeps_hitting_deadlocks_is_never_dropped_from_automatic_retries(self):
        """상한(`REACTION_MAX_ATTEMPTS`=5)보다 많이 교착을 만나도 계속 대상이다 — 실패로 세면 6번째부터 자동 처리에서 빠진다."""
        with mock.patch("records.processing.billing.charge_for_reaction", side_effect=DEADLOCK):
            for _ in range(7):
                counts = records.process_pending(now=NOW)
                self.assertEqual((counts["transient"], counts["failed"]), (1, 0))
        self.assertEqual(self.row().attempts, 0)
        self.assertEqual(records.stuck_count(), 0)
        counts = records.process_pending(now=NOW)
        self.assertEqual((counts["accepted"], counts["transient"]), (1, 0))

    def test_the_command_summary_reports_transient_separately(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        with mock.patch("records.processing.billing.charge_for_reaction", side_effect=LOCK_TIMEOUT):
            call_command("process_reactions", "--once", stdout=out)
        self.assertIn("'transient': 1", out.getvalue())


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class RealLockWaitTimeoutTests(TransactionTestCase):
    """실제 MySQL 의 잠금 대기 초과(1205): 다른 연결이 반응 행을 쥐고 있어 기다리다 시간이 넘으면 횟수를 올리지 않는다."""

    def test_waiting_for_a_held_row_until_the_timeout_is_not_a_failure(self):
        w = World()
        decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)
        holding, release = threading.Event(), threading.Event()

        def hold():
            with transaction.atomic():
                list(Reaction.objects.select_for_update().filter(pk=view.inbox_id))
                holding.set()
                release.wait(WAIT)

        holder = Worker(hold)
        holder.start()
        self.assertTrue(holding.wait(WAIT))
        try:
            with connection.cursor() as cur:
                cur.execute("SET SESSION innodb_lock_wait_timeout = 1")
            with self.assertRaises(OperationalError) as caught:
                records.process_reaction(view.inbox_id, now=NOW)
            self.assertTrue(is_transient_lock_error(caught.exception), caught.exception)
        finally:
            release.set()
            holder.join(WAIT)
        self.assertEqual(Reaction.objects.get(pk=view.inbox_id).attempts, 0)
        self.assertEqual(records.process_reaction(view.inbox_id, now=NOW), "ACCEPTED")


@tag("security")
class TransientErrorResponseTests(TestCase):
    """뷰 밖으로 나온 교착·잠금 대기 초과만 503 + Retry-After 다. 다른 DB 오류(연결 끊김 등 — 커밋 결과가 불명확할 수 있다)는 그대로 500."""

    def test_only_transient_lock_errors_become_503(self):
        from foundation.middleware import ApiErrorMiddleware
        from django.test import RequestFactory

        middleware = ApiErrorMiddleware(lambda request: None)
        for path in ("/advertiser/", "/api/media/v1/decisions"):
            request = RequestFactory().post(path)
            for error in (DEADLOCK, LOCK_TIMEOUT):
                response = middleware.process_exception(request, error)
                self.assertEqual((response.status_code, response["Retry-After"]), (503, "1"), (path, error))
            self.assertIsNone(middleware.process_exception(request, OperationalError(2013, "Lost connection")))
        self.assertEqual(middleware.process_exception(RequestFactory().post("/api/media/v1/decisions"), DEADLOCK)["Content-Type"], "application/problem+json")


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
