"""공유 결정의 사용자 생략과 불변 저장을 검사한다."""

from dataclasses import replace
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.test import TestCase

from ad_bridge.decisions.store import remember_decision
from ad_bridge.models import IssuedDecision
from ad_bridge.tests.support import shared_decision


class SharedDecisionStorageTests(TestCase):
    def setUp(self):
        self.decision = shared_decision()

    def test_shared_decision_has_no_user_and_is_saved_once(self):
        remember_decision(self.decision)
        remember_decision(self.decision)
        self.assertEqual(IssuedDecision.objects.count(), 1)
        record = IssuedDecision.objects.get()
        self.assertEqual(record.audience, "shared")
        self.assertIsNone(record.owner_id)
        self.assertIsNone(record.subject_id)
        self.assertTrue(record.has_ad)

    def test_shared_decision_rejects_owner_or_subject(self):
        for kwargs in ({"owner_id": uuid4()}, {"subject_id": uuid4()},
                       {"owner_id": uuid4(), "subject_id": uuid4()}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                remember_decision(self.decision, **kwargs)
        self.assertFalse(IssuedDecision.objects.exists())

    def test_shared_no_ad_decision_is_still_remembered(self):
        remember_decision(replace(self.decision, ad=None))
        self.assertFalse(IssuedDecision.objects.get().has_ad)

    def test_existing_shared_decision_cannot_be_changed(self):
        remember_decision(self.decision)
        before = IssuedDecision.objects.values().get()
        for decision in (
            replace(self.decision, slot_id=str(uuid4())),
            replace(self.decision, decided_at="2026-10-15T01:00:10Z"),
            replace(self.decision, ad=None),
        ):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                remember_decision(decision)
        with self.assertRaises(ValueError):
            remember_decision(replace(self.decision, audience="individual"), uuid4(), owner_id=uuid4())
        self.assertEqual(IssuedDecision.objects.values().get(), before)

    def test_personal_decision_cannot_be_reclassified_as_shared(self):
        remember_decision(replace(self.decision, audience="individual"), uuid4(), owner_id=uuid4())
        with self.assertRaises(ValueError):
            remember_decision(self.decision)
        self.assertEqual(IssuedDecision.objects.get().audience, "individual")

    def test_unknown_audience_is_rejected(self):
        with self.assertRaises(ValueError):
            remember_decision(replace(self.decision, audience="unknown"))
        self.assertFalse(IssuedDecision.objects.exists())

    def test_database_rejects_user_bound_shared_decision(self):
        for field in ("owner_id", "subject_id"):
            with self.subTest(field=field), self.assertRaises(IntegrityError), transaction.atomic():
                IssuedDecision.objects.create(
                    decision_id=uuid4(), slot_id=uuid4(), audience="shared",
                    decided_at=self.decision.decided_at, has_ad=True, **{field: uuid4()},
                )

    def test_database_requires_subject_for_individual_decision(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            IssuedDecision.objects.create(
                decision_id=uuid4(), slot_id=uuid4(), audience="individual",
                decided_at=self.decision.decided_at, has_ad=True,
            )
