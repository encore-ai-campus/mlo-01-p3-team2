"""실제 저장소로 공통 회차·이동 소유권·동일 소재 결정 통합을 검증한다."""

from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
from uuid import uuid4

from django.core import signing
from django.test import TestCase, override_settings

from ad_bridge.api.errors import AdsTransportError
from ad_bridge.api.types import Ad, Decision
from ad_bridge.models import PlacementBatch, IssuedDecision
from ad_bridge.placements import get_batch, public_batch, transfer_token, transfer_identity


@override_settings(ADS_ROOFTOP_SLOT_ID="10000000-0000-0000-0000-000000000001",
                   ADS_PORTAL_LEFT_SLOT_ID="10000000-0000-0000-0000-000000000002",
                   ADS_PORTAL_RIGHT_SLOT_ID="10000000-0000-0000-0000-000000000003")
class PlacementTests(TestCase):
    def setUp(self):
        self.owner, self.subject, self.creative = uuid4(), uuid4(), str(uuid4())
        self.now = datetime(2026, 10, 15, 1, 0, 1, tzinfo=timezone.utc)
        self.client = Mock()
        self.client.create_decision.side_effect = self.decision

    def decision(self, slot_id, subject_id=None):
        return Decision(str(uuid4()), slot_id, "slot", "shared" if subject_id is None else "individual",
            "2026-10-15T01:00:00Z", Ad(self.creative, "광고", "https://ads.test/image.png",
                "https://example.com", "https://ads.test/c/click?s={subject_id}"), None)

    def batch(self, **kwargs):
        return get_batch(client=self.client, owner_id=self.owner, subject_id=self.subject, now=self.now, **kwargs)

    def test_same_round_shared_by_users_and_next_boundary_issues_once(self):
        first = self.batch()
        self.owner, self.subject = uuid4(), uuid4()
        self.now += timedelta(seconds=8)
        second = self.batch()
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(self.client.create_decision.call_count, 1)
        self.now += timedelta(seconds=1)
        third = self.batch()
        self.assertNotEqual(first.key, third.key)
        self.assertEqual(self.client.create_decision.call_count, 2)
        self.assertIsNone(IssuedDecision.objects.first().owner_id)

    def test_same_creative_uses_one_decision_and_click_target_on_both_sides(self):
        transfer = str(uuid4())
        batch = self.batch(transfer_id=transfer)
        self.assertEqual(len(batch.payload), 2)
        self.assertEqual(batch.payload[0], batch.payload[1])
        self.assertEqual(self.batch(transfer_id=transfer).payload, batch.payload)
        self.assertEqual(self.client.create_decision.call_count, 2)
        self.batch(transfer_id=str(uuid4()))
        self.assertEqual(self.client.create_decision.call_count, 4)

    def test_different_creatives_keep_separate_decisions(self):
        def different(**kwargs):
            self.creative = str(uuid4())
            return self.decision(**kwargs)
        self.client.create_decision.side_effect = different
        batch = self.batch(transfer_id=str(uuid4()))
        self.assertNotEqual(batch.payload[0]["decision_id"], batch.payload[1]["decision_id"])

    def test_pending_claim_does_not_start_a_second_external_request(self):
        PlacementBatch.objects.create(key=f"roof:{int(self.now.timestamp())//10*10}", expires_at=self.now+timedelta(seconds=9))
        self.assertEqual(self.batch().state, "PENDING")
        self.client.create_decision.assert_not_called()

    def test_ambiguous_failure_is_not_reissued_within_the_same_round(self):
        self.client.create_decision.side_effect = AdsTransportError("timeout")
        self.assertEqual(self.batch().state, "FAILED")
        self.assertEqual(self.batch().state, "FAILED")
        self.assertEqual(self.client.create_decision.call_count, 1)

    def test_portal_owner_cannot_be_substituted(self):
        transfer = str(uuid4())
        self.batch(transfer_id=transfer)
        self.owner = uuid4()
        with self.assertRaises(ValueError):
            self.batch(transfer_id=transfer)

    def test_public_payload_has_viewer_click_url_without_internal_owner(self):
        payload = public_batch(self.batch(), self.subject)
        self.assertIn(str(self.subject), payload["ads"][0]["ad"]["click_url"])
        self.assertNotIn(str(self.owner), str(payload))
        self.assertNotIn("redirect_url", str(payload))

    def test_transfer_token_is_bound_to_user_and_rejects_tampering(self):
        transfer = uuid4()
        token = transfer_token(1, transfer)
        self.assertEqual(transfer_identity(token, 1), str(transfer))
        for value, user in ((token, 2), (token + "x", 1)):
            with self.assertRaises(signing.BadSignature):
                transfer_identity(value, user)
