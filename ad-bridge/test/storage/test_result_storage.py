"""임시 SQLite에서 판정 갱신과 전송 기록 보존을 확인한다."""
from datetime import datetime, timezone
from unittest.mock import patch
from django.test import TestCase
from django.db import DatabaseError
from ad_bridge.models import IssuedDecision, Impression
from ad_bridge.impressions.store import get_impression, update_result, DecisionNotFound, ImpressionNotReady
from test.support.impression_fakes import DECISION_ID, REACTION_ID, SUBJECT_ID, OCCURRED_AT


class ResultStorageTests(TestCase):
    def setUp(self):
        IssuedDecision.objects.create(decision_id=DECISION_ID, subject_id=SUBJECT_ID,
            slot_id=REACTION_ID, decided_at=datetime.now(timezone.utc), has_ad=True)
        Impression.objects.create(reaction_id=REACTION_ID, decision_id=DECISION_ID, subject_id=SUBJECT_ID,
            occurred_at=OCCURRED_AT, delivery_state="ACKNOWLEDGED", attempts=3, status="RECEIVED")

    def update(self, status="ACCEPTED", reason=None):
        return update_result(decision_id=DECISION_ID, subject_id=SUBJECT_ID, reaction_id=REACTION_ID,
                             status=status, reason_code=reason, request_id="lookup")

    def test_save(self):
        before = Impression.objects.values().get()
        self.update("REJECTED", "future_reason")
        after = Impression.objects.values().get()
        self.assertEqual(after["status"], "REJECTED")
        self.assertEqual(after["reason_code"], "future_reason")
        for key in before.keys() - {"status", "reason_code", "request_id"}:
            self.assertEqual(after[key], before[key])

    def test_terminal(self):
        self.update()
        self.update("RECEIVED")
        self.update("REJECTED", "late")
        self.assertEqual(Impression.objects.get().status, "ACCEPTED")

    def test_owner(self):
        with self.assertRaises(DecisionNotFound):
            get_impression(decision_id=DECISION_ID, subject_id=REACTION_ID)
        with self.assertRaises(DecisionNotFound):
            get_impression(decision_id=SUBJECT_ID, subject_id=SUBJECT_ID)

    def test_pending(self):
        Impression.objects.update(delivery_state="UNCONFIRMED")
        with self.assertRaises(ImpressionNotReady):
            self.update()
        self.assertEqual(Impression.objects.get().status, "RECEIVED")

    def test_failure(self):
        with patch("django.db.models.query.QuerySet.update", side_effect=DatabaseError("failed")):
            with self.assertRaises(DatabaseError):
                self.update()
        self.assertEqual(Impression.objects.get().status, "RECEIVED")

    def test_race(self):
        # 첫 읽기 직후 다른 조회가 확정한 상황을 재현한다.
        original = get_impression
        def raced(**kwargs):
            record = original(**kwargs)
            Impression.objects.update(status="ACCEPTED", reason_code=None)
            return record
        with patch("ad_bridge.impressions.store.get_impression", side_effect=raced):
            self.update("RECEIVED")
        self.assertEqual(Impression.objects.get().status, "ACCEPTED")
