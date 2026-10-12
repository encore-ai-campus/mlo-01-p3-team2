"""재전송 저장소 통합 검사: 메모리 SQLite에서 예약·임대·마이그레이션을 확인한다."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.query import QuerySet
from django.test import TestCase, TransactionTestCase

from ad_bridge.impressions.store import claim_due_impression, finish_impression, reserve_impression
from ad_bridge.models import Impression, IssuedDecision


class RetryStorageTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
        self.subject = uuid4()
        self.owner = uuid4()
        self.decision = IssuedDecision.objects.create(
            decision_id=uuid4(), owner_id=self.owner, subject_id=self.subject, slot_id=uuid4(),
            decided_at=self.now, has_ad=True,
        )

    def reserve(self):
        return reserve_impression(
            self.decision.pk, self.owner, "2026-10-11T12:00:00.123000Z", now=self.now,
        )[0]

    def fail(self, record, *, due=None):
        return finish_impression(
            record.reaction_id, delivery_state="UNCONFIRMED", lease_token=record.lease_token,
            next_attempt_at=due if due is not None else self.now + timedelta(seconds=10),
            last_error="ads_http_error", last_http_status=503, request_id="request-503",
        )

    def test_reservation_has_first_attempt_and_active_lease(self):
        record = self.reserve()
        self.assertEqual(record.attempts, 1)
        self.assertEqual(UUID(record.lease_token).version, 4)
        self.assertEqual(record.lease_expires_at, self.now + timedelta(seconds=60))
        self.assertIsNone(record.next_attempt_at)
        self.assertIsNone(claim_due_impression(now=self.now))

    def test_due_time_and_retry_metadata_are_persisted(self):
        first = self.reserve()
        saved = self.fail(first)
        self.assertIsNone(saved.lease_token)
        self.assertIsNone(saved.lease_expires_at)
        self.assertEqual(saved.last_error, "ads_http_error")
        self.assertEqual(saved.last_http_status, 503)
        self.assertEqual(saved.request_id, "request-503")
        self.assertIsNone(claim_due_impression(now=self.now + timedelta(seconds=9)))
        claimed = claim_due_impression(now=self.now + timedelta(seconds=10))
        self.assertEqual(claimed.reaction_id, first.reaction_id)
        self.assertEqual(claimed.occurred_at, first.occurred_at)
        self.assertEqual(claimed.subject_id, first.subject_id)
        self.assertEqual(claimed.decision_id, first.decision_id)
        self.assertEqual(claimed.attempts, 2)
        self.assertNotEqual(claimed.lease_token, first.lease_token)
        self.assertIsNone(claimed.next_attempt_at)

    def test_expired_lease_recovers_crashed_sending_record(self):
        first = self.reserve()
        self.assertIsNone(claim_due_impression(now=self.now + timedelta(seconds=59)))
        claimed = claim_due_impression(now=self.now + timedelta(seconds=60))
        self.assertEqual(claimed.reaction_id, first.reaction_id)
        self.assertEqual(claimed.attempts, 2)
        self.assertNotEqual(claimed.lease_token, first.lease_token)
        self.assertIsNone(claim_due_impression(now=self.now + timedelta(seconds=60)))

    def test_terminal_records_cannot_be_claimed(self):
        record = self.reserve()
        for state in ("ACKNOWLEDGED", "BLOCKED"):
            Impression.objects.filter(pk=record.reaction_id).update(
                delivery_state=state, next_attempt_at=self.now, lease_expires_at=self.now,
            )
            with self.subTest(state=state):
                self.assertIsNone(claim_due_impression(now=self.now + timedelta(days=1)))

    def test_stale_failure_does_not_overwrite_current_owner(self):
        first = self.reserve()
        current = claim_due_impression(now=self.now + timedelta(seconds=60))
        hint = self.now + timedelta(seconds=90)
        saved = self.fail(first, due=hint)
        self.assertEqual(saved, replace(current, next_attempt_at=hint))
        self.assertEqual(saved.delivery_state, "SENDING")
        current_done = self.fail(current)
        self.assertEqual(current_done.delivery_state, "UNCONFIRMED")
        self.assertEqual(current_done.next_attempt_at, hint)

    def test_late_retry_after_survives_lease_races_and_shorter_failure_delays(self):
        first = self.reserve()
        current = claim_due_impression(now=self.now + timedelta(seconds=60))
        current_failed = self.fail(current, due=self.now + timedelta(seconds=63))
        late_due = self.now + timedelta(seconds=662)
        delayed = finish_impression(
            first.reaction_id, delivery_state="UNCONFIRMED", lease_token=first.lease_token,
            next_attempt_at=late_due, last_error="ads_http_error", last_http_status=429,
        )
        # 뒤늦은 응답은 현 상태·진단 정보를 덮어쓰지 않고 더 긴 대기만 남긴다.
        self.assertEqual(delayed, replace(current_failed, next_attempt_at=late_due))
        self.assertIsNone(claim_due_impression(now=self.now + timedelta(seconds=63)))
        recovered = claim_due_impression(now=late_due)
        self.assertIsNotNone(recovered)

        later_due = self.now + timedelta(seconds=1000)
        finish_impression(
            first.reaction_id, delivery_state="UNCONFIRMED", lease_token=first.lease_token,
            next_attempt_at=later_due,
        )
        # 현재 전송의 임대가 끝나도 이전 응답의 최소 대기보다 일찍 선점할 수 없다.
        self.assertIsNone(claim_due_impression(now=self.now + timedelta(seconds=722)))
        shorter = self.fail(recovered, due=self.now + timedelta(seconds=724))
        self.assertEqual(shorter.next_attempt_at, later_due)
        self.assertIsNone(claim_due_impression(now=self.now + timedelta(seconds=999)))

        original_update = QuerySet.update
        raced = False
        race_due = self.now + timedelta(seconds=1100)

        def hint_during_claim(queryset, **values):
            nonlocal raced
            if queryset.model is Impression and "attempts" in values and not raced:
                raced = True
                # 후보 선택 뒤 대기 힌트가 늘어나도 조건부 UPDATE가 조기 선점을 거절한다.
                original_update(
                    Impression.objects.filter(pk=first.reaction_id), next_attempt_at=race_due,
                )
            return original_update(queryset, **values)

        with patch.object(QuerySet, "update", hint_during_claim):
            self.assertIsNone(claim_due_impression(now=later_due))
        self.assertTrue(raced)
        final = claim_due_impression(now=race_due)
        self.assertEqual(final.reaction_id, first.reaction_id)
        # 접수 확인은 모든 대기 힌트보다 우선하며 오래된 실패가 다시 예약하지 못한다.
        acknowledged = finish_impression(
            first.reaction_id, delivery_state="ACKNOWLEDGED", lease_token=first.lease_token,
        )
        late_failure = self.fail(final, due=self.now + timedelta(seconds=2000))
        self.assertEqual(late_failure, acknowledged)
        self.assertIsNone(late_failure.next_attempt_at)

    def test_missing_token_cannot_finish_a_new_lease(self):
        record = self.reserve()
        saved = finish_impression(record.reaction_id, delivery_state="BLOCKED")
        self.assertEqual(saved, record)

    def test_stale_acknowledgement_dominates_current_and_late_failures(self):
        first = self.reserve()
        current = claim_due_impression(now=self.now + timedelta(seconds=60))
        received = finish_impression(
            first.reaction_id, delivery_state="ACKNOWLEDGED", lease_token=first.lease_token,
            status="RECEIVED", request_id="ack",
        )
        after_error = self.fail(current)
        self.assertEqual(after_error, received)
        self.assertEqual(received.delivery_state, "ACKNOWLEDGED")
        self.assertIsNone(received.next_attempt_at)
        self.assertIsNone(received.lease_token)
        self.assertIsNone(claim_due_impression(now=self.now + timedelta(days=1)))

    def test_stale_acknowledgement_can_confirm_previously_blocked_request(self):
        first = self.reserve()
        current = claim_due_impression(now=self.now + timedelta(seconds=60))
        finish_impression(current.reaction_id, delivery_state="BLOCKED", lease_token=current.lease_token)
        acknowledged = finish_impression(
            first.reaction_id, delivery_state="ACKNOWLEDGED", lease_token=first.lease_token,
        )
        self.assertEqual(acknowledged.delivery_state, "ACKNOWLEDGED")

    def test_duplicate_notification_does_not_extend_or_replace_lease(self):
        first = self.reserve()
        repeated, created = reserve_impression(
            self.decision.pk, self.owner, "2026-10-11T12:00:30Z",
            now=self.now + timedelta(seconds=30), lease_seconds=600,
        )
        self.assertFalse(created)
        self.assertEqual(repeated, first)

    def test_legacy_missing_schedule_or_lease_is_claimable(self):
        first = self.reserve()
        for state in ("UNCONFIRMED", "SENDING"):
            Impression.objects.filter(pk=first.reaction_id).update(
                delivery_state=state, next_attempt_at=None, lease_token=None, lease_expires_at=None,
            )
            with self.subTest(state=state):
                claimed = claim_due_impression(now=self.now)
                self.assertEqual(claimed.reaction_id, first.reaction_id)
                self.assertIsNotNone(claimed.lease_token)

    def test_lost_conditional_update_cannot_return_another_workers_lease(self):
        first = self.reserve()
        self.fail(first, due=self.now)
        original_update = QuerySet.update
        rival_token = uuid4()
        raced = False

        def racing_update(queryset, **values):
            nonlocal raced
            if queryset.model is Impression and "attempts" in values and not raced:
                raced = True
                # 후보를 읽은 직후 다른 작업자가 같은 행을 먼저 확보한 상황을 재현한다.
                original_update(
                    Impression.objects.filter(pk=first.reaction_id),
                    delivery_state="SENDING", lease_token=rival_token,
                    lease_expires_at=self.now + timedelta(seconds=60), attempts=2,
                )
            return original_update(queryset, **values)

        with patch.object(QuerySet, "update", racing_update):
            self.assertIsNone(claim_due_impression(now=self.now))
        self.assertTrue(raced)
        row = Impression.objects.get()
        self.assertEqual(row.lease_token, rival_token)
        self.assertEqual(row.attempts, 2)

    def test_claim_rollback_preserves_previous_schedule(self):
        first = self.reserve()
        self.fail(first, due=self.now)
        with patch("ad_bridge.impressions.store._snapshot", side_effect=RuntimeError("rollback")):
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                claim_due_impression(now=self.now)
        row = Impression.objects.get()
        self.assertEqual(row.delivery_state, "UNCONFIRMED")
        self.assertEqual(row.attempts, 1)
        self.assertEqual(row.next_attempt_at, self.now)

    def test_claim_rejects_external_transaction_before_modification(self):
        first = self.reserve()
        self.fail(first, due=self.now)
        with self.assertRaisesRegex(RuntimeError, "durable atomic"), transaction.atomic():
            claim_due_impression(now=self.now)
        self.assertEqual(Impression.objects.get().attempts, 1)

    def test_invalid_clock_and_lease_are_rejected(self):
        for now in (datetime(2026, 10, 11), "2026-10-11T12:00:00Z", None):
            with self.subTest(now=now), self.assertRaises(ValueError):
                claim_due_impression(now=now)
        for seconds in (True, 0, -1, float("nan"), float("inf"), 1e30, 10**1000, "60"):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                claim_due_impression(now=self.now, lease_seconds=seconds)

    def test_diagnostics_reject_exception_text_and_invalid_http_metadata(self):
        first = self.reserve()
        for fields in (
            {"last_error": "raw exception with secret"},
            {"last_http_status": True},
            {"last_http_status": 600},
            {"next_attempt_at": datetime(2026, 10, 11)},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                finish_impression(
                    first.reaction_id, delivery_state="UNCONFIRMED", lease_token=first.lease_token, **fields,
                )
        self.assertEqual(Impression.objects.get().delivery_state, "SENDING")


class RetryMigrationTests(TransactionTestCase):
    """기존 0001 상태에서 실제 0002 전환 후 미확인 기록의 회수를 검사한다."""

    def test_migration_recovers_pending_and_preserves_terminal_rows(self):
        previous = [("ad_bridge", "0001_initial")]
        latest = [("ad_bridge", "0002_impression_retry")]
        executor = MigrationExecutor(connection)
        executor.migrate(previous)
        old_apps = executor.loader.project_state(previous).apps
        OldDecision = old_apps.get_model("ad_bridge", "IssuedDecision")
        OldImpression = old_apps.get_model("ad_bridge", "Impression")
        identities = {}
        try:
            for state in ("SENDING", "UNCONFIRMED", "ACKNOWLEDGED", "BLOCKED"):
                decision = OldDecision.objects.create(
                    decision_id=uuid4(), subject_id=uuid4(), slot_id=uuid4(),
                    decided_at=datetime(2026, 10, 11, tzinfo=timezone.utc), has_ad=True,
                )
                row = OldImpression.objects.create(
                    decision=decision, subject_id=decision.subject_id,
                    occurred_at="2026-10-11T12:00:00Z", delivery_state=state,
                )
                identities[state] = row.pk
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            for state, reaction_id in identities.items():
                row = Impression.objects.get(pk=reaction_id)
                self.assertEqual(row.delivery_state, state)
                self.assertEqual(row.occurred_at, "2026-10-11T12:00:00Z")
                if state in {"SENDING", "UNCONFIRMED"}:
                    self.assertEqual(row.attempts, 1)
                    self.assertEqual(row.last_error, "legacy_unconfirmed")
                    self.assertIsNotNone(row.lease_expires_at if state == "SENDING" else row.next_attempt_at)
                else:
                    self.assertIsNone(row.next_attempt_at)
                    self.assertIsNone(row.lease_expires_at)
        finally:
            MigrationExecutor(connection).migrate([("ad_bridge", "0003_decision_owner")])


class OwnerMigrationTests(TransactionTestCase):
    def test_migration_preserves_existing_decision_and_impression_payloads(self):
        previous = [("ad_bridge", "0002_impression_retry")]
        latest = [("ad_bridge", "0003_decision_owner")]
        executor = MigrationExecutor(connection)
        executor.migrate(previous)
        old_apps = executor.loader.project_state(previous).apps
        OldDecision = old_apps.get_model("ad_bridge", "IssuedDecision")
        OldImpression = old_apps.get_model("ad_bridge", "Impression")
        snapshots = []
        try:
            # 원본 UUID 기반 기록과 이전 가명 기반 기록 모두 내용을 그대로 남긴다.
            for subject in (UUID("11223344-1234-4234-8234-123456789abc"),
                            UUID("d8d3d672-5458-ddcc-c90c-a7844b3aa51a")):
                decision = OldDecision.objects.create(decision_id=uuid4(), subject_id=subject,
                    slot_id=uuid4(), decided_at=datetime(2026, 10, 11, tzinfo=timezone.utc), has_ad=True)
                row = OldImpression.objects.create(decision=decision, subject_id=subject,
                    occurred_at="2026-10-11T12:00:00.123000Z", delivery_state="UNCONFIRMED",
                    attempts=3, next_attempt_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
                    last_error="ads_http_error", last_http_status=503, lease_token=uuid4())
                snapshots.append((OldDecision.objects.values().get(pk=decision.pk),
                                  OldImpression.objects.values().get(pk=row.pk)))
            MigrationExecutor(connection).migrate(latest)
            for decision_before, impression_before in snapshots:
                decision_after = IssuedDecision.objects.values().get(pk=decision_before["decision_id"])
                self.assertIsNone(decision_after.pop("owner_id"))
                self.assertEqual(decision_after, decision_before)
                self.assertEqual(Impression.objects.values().get(pk=impression_before["reaction_id"]), impression_before)
        finally:
            MigrationExecutor(connection).migrate(latest)
