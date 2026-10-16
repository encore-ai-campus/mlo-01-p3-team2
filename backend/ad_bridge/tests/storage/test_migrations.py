"""0003 개인 기록에서 공유 노출 구조로 이행할 때 요청과 전송 상태를 보존한다."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SharedImpressionMigrationTests(TransactionTestCase):
    def test_migration_preserves_requests_and_does_not_infer_unknown_owners(self):
        previous = [("ad_bridge", "0003_decision_owner")]
        latest = [("ad_bridge", "0004_shared_impressions")]
        executor = MigrationExecutor(connection)
        restore = executor.loader.graph.leaf_nodes("ad_bridge")
        executor.migrate(previous)
        old_apps = executor.loader.project_state(previous).apps
        OldDecision = old_apps.get_model("ad_bridge", "IssuedDecision")
        OldImpression = old_apps.get_model("ad_bridge", "Impression")
        now = datetime(2026, 10, 15, 1, tzinfo=timezone.utc)
        snapshots = []
        try:
            for state in ("SENDING", "UNCONFIRMED", "ACKNOWLEDGED", "BLOCKED"):
                for owner in (uuid4(), None):
                    decision = OldDecision.objects.create(
                        decision_id=uuid4(), owner_id=owner, subject_id=uuid4(),
                        slot_id=uuid4(), decided_at=now, has_ad=True,
                    )
                    row = OldImpression.objects.create(
                        decision=decision, subject_id=decision.subject_id,
                        occurred_at="2026-10-15T01:00:01.123000Z", delivery_state=state,
                        status="RECEIVED" if state == "ACKNOWLEDGED" else None,
                        reason_code=None, request_id="original-request", attempts=3,
                        next_attempt_at=now + timedelta(seconds=60),
                        lease_token=uuid4(), lease_expires_at=now + timedelta(seconds=30),
                        last_error="ads_http_error", last_http_status=401 if state == "BLOCKED" else 503,
                    )
                    snapshots.append((OldDecision.objects.values().get(pk=decision.pk),
                                      OldImpression.objects.values().get(pk=row.pk)))
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            new_apps = executor.loader.project_state(latest).apps
            Decision = new_apps.get_model("ad_bridge", "IssuedDecision")
            Impression = new_apps.get_model("ad_bridge", "Impression")
            for decision_before, reaction_before in snapshots:
                after = Decision.objects.values().get(pk=decision_before["decision_id"])
                self.assertEqual(after.pop("audience"), "individual")
                self.assertEqual(after, decision_before)
                after = Impression.objects.values().get(pk=reaction_before["reaction_id"])
                self.assertEqual(after.pop("owner_id"), decision_before["owner_id"])
                self.assertEqual(after, reaction_before)
        finally:
            # 다른 테스트가 이전 스키마를 물려받지 않도록 최신 상태로 복구한다.
            MigrationExecutor(connection).migrate(restore)
