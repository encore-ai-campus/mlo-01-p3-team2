"""records 0009(판정 근거): 이미 판정된 행에는 그때의 사실이 없으므로 지어내지 않고 '기록 이전'이라고만 표시한 뒤 제약(판정한 행에는 근거)을 건다."""
import uuid
from datetime import UTC, datetime

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, tag

BEFORE = [("records", "0008_decision_owner_index")]
AFTER = [("records", "0009_reaction_basis")]
WHEN = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@tag("security")
class BasisMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())  # 다른 시험을 위해 최신으로

    def test_decided_rows_are_marked_as_before_the_record_and_undecided_rows_stay_empty(self):
        Reaction = self.migrate(BEFORE).get_model("records", "Reaction")
        media, decision, person = uuid.uuid4(), uuid.uuid4(), "0197a5c0-0000-7000-8000-000000000001"
        make = lambda **kw: Reaction.objects.create(media_id=media, reaction_id=uuid.uuid4(), decision_id=decision, occurred_at=WHEN, raw={}, **kw)  # noqa: E731
        accepted = make(type="IMPRESSION", status="ACCEPTED", processed_at=WHEN, person_id=person, accepted_key=f"{decision}:{person}:IMPRESSION")
        rejected = make(type="IMPRESSION", status="REJECTED", reason_code="duplicate_type", applied_rule="once-per-type", processed_at=WHEN)
        waiting = make(type="CLICK", status="RECEIVED")

        Reaction = self.migrate(AFTER).get_model("records", "Reaction")
        for row in (accepted, rejected):
            basis = Reaction.objects.get(pk=row.pk).basis
            self.assertEqual(basis["v"], 0)
            self.assertIn("legacy", basis)
        self.assertIsNone(Reaction.objects.get(pk=waiting.pk).basis)
        with self.assertRaises(IntegrityError), transaction.atomic():  # 제약이 걸렸다
            Reaction.objects.filter(pk=accepted.pk).update(basis=None)
