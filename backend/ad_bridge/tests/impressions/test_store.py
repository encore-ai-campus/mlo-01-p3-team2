"""공유 결정의 사용자별 노출·접근·중복 방지를 메모리 DB로 검사한다."""

from unittest.mock import patch
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.test import TestCase

from ad_bridge.decisions.store import remember_decision
from ad_bridge.impressions.store import (
    DecisionNotFound, NoAdForDecision, finish_impression, get_impression,
    reserve_impression, update_result,
)
from ad_bridge.models import Impression
from ad_bridge.tests.support import shared_decision


class SharedImpressionStorageTests(TestCase):
    def setUp(self):
        self.decision = shared_decision()
        remember_decision(self.decision)
        self.owner, self.subject = uuid4(), uuid4()
        self.time = "2026-10-15T01:00:01.123000Z"

    def reserve(self, **kwargs):
        return reserve_impression(
            self.decision.decision_id, self.owner, self.time,
            subject_id=self.subject, **kwargs,
        )

    def test_first_shared_impression_fixes_owner_subject_and_request(self):
        record, created = self.reserve()
        self.assertTrue(created)
        row = Impression.objects.get()
        self.assertEqual(row.owner_id, self.owner)
        self.assertEqual(row.subject_id, self.subject)
        self.assertEqual(record.occurred_at, self.time)
        self.assertEqual(UUID(record.reaction_id).version, 4)
        self.assertEqual(record.attempts, 1)
        self.assertIsNotNone(record.lease_token)

    def test_same_user_duplicate_keeps_original_payload_after_secret_change(self):
        first, _ = self.reserve()
        duplicate, created = reserve_impression(
            self.decision.decision_id, str(self.owner).upper(), "2026-10-15T01:00:09Z",
            subject_id=uuid4(),
        )
        self.assertFalse(created)
        self.assertEqual(duplicate, first)
        self.assertEqual(Impression.objects.count(), 1)

    def test_two_users_share_decision_but_have_separate_reactions(self):
        first, _ = self.reserve()
        other_owner, other_subject = uuid4(), uuid4()
        second, created = reserve_impression(
            self.decision.decision_id, other_owner, self.time, subject_id=other_subject,
        )
        self.assertTrue(created)
        self.assertEqual(first.decision_id, second.decision_id)
        self.assertNotEqual(first.reaction_id, second.reaction_id)
        self.assertEqual(second.subject_id, str(other_subject))
        self.assertEqual(get_impression(decision_id=first.decision_id, owner_id=self.owner), first)
        self.assertEqual(get_impression(decision_id=first.decision_id, owner_id=other_owner), second)
        self.assertEqual(Impression.objects.count(), 2)

    def test_another_user_cannot_read_or_update_first_users_reaction(self):
        first, _ = self.reserve()
        other_owner = uuid4()
        with self.assertRaises(DecisionNotFound):
            get_impression(decision_id=first.decision_id, owner_id=other_owner)
        reserve_impression(first.decision_id, other_owner, self.time, subject_id=uuid4())
        with self.assertRaises(DecisionNotFound):
            update_result(
                decision_id=first.decision_id, owner_id=other_owner,
                reaction_id=first.reaction_id, status="ACCEPTED", reason_code=None, request_id=None,
            )
        self.assertEqual(get_impression(decision_id=first.decision_id, owner_id=self.owner), first)

    def test_ad_subject_is_not_an_internal_owner(self):
        first, _ = self.reserve()
        with self.assertRaises(DecisionNotFound):
            get_impression(decision_id=first.decision_id, owner_id=self.subject)

    def test_shared_no_ad_decision_cannot_create_an_impression(self):
        decision = shared_decision(ad=False)
        remember_decision(decision)
        with self.assertRaises(NoAdForDecision):
            reserve_impression(decision.decision_id, self.owner, self.time, subject_id=self.subject)
        self.assertFalse(Impression.objects.exists())

    def test_shared_impression_requires_a_valid_server_supplied_subject(self):
        for subject in (None, "bad", 123):
            with self.subTest(subject=subject), self.assertRaises(ValueError):
                reserve_impression(self.decision.decision_id, self.owner, self.time, subject_id=subject)
        self.assertFalse(Impression.objects.exists())

    def test_unknown_decision_cannot_create_an_impression(self):
        with self.assertRaises(DecisionNotFound):
            reserve_impression(uuid4(), self.owner, self.time, subject_id=self.subject)
        self.assertFalse(Impression.objects.exists())

    def test_database_blocks_second_reaction_for_same_internal_user(self):
        self.reserve()
        # 저장소를 우회하고 가명을 바꿔도 DB가 같은 사용자 중복을 막아야 한다.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Impression.objects.create(
                decision_id=self.decision.decision_id, owner_id=self.owner,
                subject_id=uuid4(), occurred_at=self.time,
            )
        self.assertEqual(Impression.objects.count(), 1)

    def test_database_blocks_second_reaction_for_same_ad_subject(self):
        self.reserve()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Impression.objects.create(
                decision_id=self.decision.decision_id, owner_id=uuid4(),
                subject_id=self.subject, occurred_at=self.time,
            )
        self.assertEqual(Impression.objects.count(), 1)

    def test_snapshot_failure_rolls_back_shared_reservation(self):
        with patch("ad_bridge.impressions.store._snapshot", side_effect=RuntimeError("롤백")):
            with self.assertRaises(RuntimeError):
                self.reserve()
        self.assertFalse(Impression.objects.exists())

    def test_result_update_changes_only_selected_viewers_reaction(self):
        first, _ = self.reserve()
        other, _ = reserve_impression(
            self.decision.decision_id, uuid4(), self.time, subject_id=uuid4(),
        )
        finish_impression(
            first.reaction_id, delivery_state="ACKNOWLEDGED", status="RECEIVED",
            lease_token=first.lease_token,
        )
        result = update_result(
            decision_id=first.decision_id, owner_id=self.owner,
            reaction_id=first.reaction_id, status="ACCEPTED", reason_code=None, request_id="result",
        )
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(result.subject_id, first.subject_id)
        self.assertEqual(Impression.objects.get(pk=other.reaction_id).delivery_state, "SENDING")
