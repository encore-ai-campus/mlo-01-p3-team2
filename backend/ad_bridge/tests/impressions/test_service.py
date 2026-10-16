"""공유 노출의 전송·중복·재시도를 가짜 광고 응답과 실제 저장소로 확인한다."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

from django.test import TestCase

from ad_bridge.api.errors import AdsHTTPError
from ad_bridge.decisions.store import remember_decision
from ad_bridge.delivery.worker import dispatch_due_impressions
from ad_bridge.impressions import store
from ad_bridge.impressions.service import report_impression_once
from ad_bridge.results.service import refresh_result
from ad_bridge.tests.support import received_reaction, shared_decision


class SharedImpressionServiceTests(TestCase):
    def setUp(self):
        self.decision = shared_decision()
        remember_decision(self.decision)
        self.owner, self.subject = uuid4(), uuid4()
        self.now = datetime(2026, 10, 15, 1, 0, 1, tzinfo=timezone.utc)
        self.client = Mock()
        self.client.report_impression.side_effect = received_reaction

    def report(self, *, owner=None, subject=None):
        return report_impression_once(
            client=self.client, store=store, decision_id=self.decision.decision_id,
            owner_id=owner or self.owner, subject_id=subject or self.subject,
            occurred_at="2026-10-15T01:00:01.123000Z", now=lambda: self.now,
        )

    def test_duplicate_notification_sends_only_first_request(self):
        first = self.report()
        duplicate = self.report(subject=uuid4())
        self.assertTrue(first.created)
        self.assertFalse(duplicate.created)
        self.assertEqual(duplicate.record, first.record)
        self.client.report_impression.assert_called_once()
        request = self.client.report_impression.call_args.kwargs
        self.assertEqual(request["subject_id"], str(self.subject))
        self.assertNotIn("owner_id", request)

    def test_each_viewer_sends_their_own_pseudonym(self):
        first = self.report()
        other_subject = uuid4()
        second = self.report(owner=uuid4(), subject=other_subject)
        self.assertNotEqual(first.record.reaction_id, second.record.reaction_id)
        self.assertEqual(self.client.report_impression.call_count, 2)
        self.assertEqual(self.client.report_impression.call_args.kwargs["subject_id"], str(other_subject))

    def test_shared_retry_preserves_original_payload_after_secret_change(self):
        self.client.report_impression.side_effect = AdsHTTPError(503)
        first = self.report()
        request = self.client.report_impression.call_args.kwargs.copy()
        self.assertEqual(first.record.delivery_state, "UNCONFIRMED")
        self.report(subject=uuid4())
        self.client.report_impression.assert_called_once()
        self.client.report_impression.side_effect = received_reaction
        due = first.record.next_attempt_at + timedelta(seconds=1)
        counts = dispatch_due_impressions(client=self.client, store=store, now=lambda: due)
        self.assertEqual(counts["acknowledged"], 1)
        self.assertEqual(self.client.report_impression.call_args.kwargs, request)

    def test_result_lookup_uses_viewers_saved_reaction(self):
        first = self.report()
        other = self.report(owner=uuid4(), subject=uuid4())
        self.client.get_reaction.return_value = received_reaction(
            decision_id=first.record.decision_id, reaction_id=first.record.reaction_id,
            subject_id=first.record.subject_id, occurred_at=first.record.occurred_at,
        )
        result = refresh_result(
            client=self.client, store=store, decision_id=self.decision.decision_id, owner_id=self.owner,
        )
        self.assertEqual(result.reaction_id, first.record.reaction_id)
        self.assertNotEqual(result.reaction_id, other.record.reaction_id)
        self.client.get_reaction.assert_called_once_with(
            decision_id=first.record.decision_id, reaction_id=first.record.reaction_id,
        )
