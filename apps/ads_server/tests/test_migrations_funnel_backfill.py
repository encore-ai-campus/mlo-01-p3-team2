"""records 0007(퍼널 판정): 2-9 이전에 인정된 반응이 이미 있는 DB 에서도 새 제약(인정된 행에는 인정 키)이 걸리도록 기존 행을 채운다."""
import uuid
from datetime import UTC, datetime

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, tag

BEFORE = [("records", "0006_reaction_source")]
AFTER = [("records", "0007_funnel")]
WHEN = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@tag("security")
class FunnelBackfillTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())  # 다른 시험을 위해 최신으로

    def test_accepted_reactions_get_their_person_and_key_and_the_constraints_hold(self):
        old = self.migrate(BEFORE)
        Decision, Reaction = old.get_model("records", "Decision"), old.get_model("records", "Reaction")
        person, decision_id, media = "0197a5c0-0000-7000-8000-000000000001", uuid.uuid4(), uuid.uuid4()
        Decision.objects.create(
            decision_id=decision_id, media_id=media, slot_id=uuid.uuid4(), subject_id=person, audience="individual", decided_at=WHEN,
            selection_policy="p", candidate_count=0,
        )
        make = lambda **kw: Reaction.objects.create(media_id=media, reaction_id=uuid.uuid4(), decision_id=decision_id, occurred_at=WHEN, raw={}, **kw)  # noqa: E731
        accepted = make(type="IMPRESSION", status="ACCEPTED", processed_at=WHEN)
        rejected = make(type="IMPRESSION", status="REJECTED", reason_code="duplicate_type", applied_rule="once-per-type", processed_at=WHEN)
        received = make(type="CLICK", status="RECEIVED")

        new = self.migrate(AFTER)
        Reaction = new.get_model("records", "Reaction")
        row = Reaction.objects.get(pk=accepted.pk)
        self.assertEqual((row.person_id, row.accepted_key), (person, f"{decision_id}:{person}:IMPRESSION"))
        for other in (rejected, received):  # 인정되지 않은 행에는 키가 없다
            self.assertEqual((Reaction.objects.get(pk=other.pk).person_id, Reaction.objects.get(pk=other.pk).accepted_key), (None, None))
