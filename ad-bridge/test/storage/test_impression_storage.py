"""메모리 SQLite로 검사하는 저장소 통합 테스트. 단위 테스트 묶음과 분리한다."""

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.test import TestCase

from ad_bridge.decisions.store import remember_decision
from ad_bridge.impressions.store import (
    DecisionNotFound,
    NoAdForDecision,
    finish_impression,
    reserve_impression,
)
from ad_bridge.models import Impression, IssuedDecision
from ad_bridge.api.types import Ad, Decision


class ImpressionStorageTests(TestCase):
    def setUp(self):
        self.subject_id = UUID("11223344-1234-4234-8234-123456789abc")
        self.time = "2026-10-11T12:00:01.123000Z"
        self.decision = Decision(
            decision_id="22334455-1234-4234-8234-123456789abc",
            slot_id="aabbccdd-1234-4234-8234-123456789abc",
            slot_name="개인 슬롯",
            audience="individual",
            decided_at="2026-10-11T12:00:00Z",
            ad=Ad(
                creative_id="33445566-1234-4234-8234-123456789abc",
                title="광고",
                image_url="http://ads.test/assets/a.png",
                redirect_url="https://example.com/",
                click_url="http://ads.test/c/token",
            ),
            request_id="decision-request",
        )

    def test_remember_decision_persists_owner_and_is_idempotent(self):
        remember_decision(self.decision, str(self.subject_id).upper())
        remember_decision(self.decision, self.subject_id)
        self.assertEqual(IssuedDecision.objects.count(), 1)
        record = IssuedDecision.objects.get()
        self.assertEqual(record.subject_id, self.subject_id)
        self.assertEqual(record.slot_id, UUID(self.decision.slot_id))
        self.assertEqual(record.decided_at, datetime(2026, 10, 11, 12, tzinfo=timezone.utc))
        self.assertTrue(record.has_ad)

    def test_existing_owner_and_decision_fields_cannot_be_overwritten(self):
        remember_decision(self.decision, self.subject_id)
        variants = (
            (self.decision, uuid4()),
            (replace(self.decision, slot_id=str(uuid4())), self.subject_id),
            (replace(self.decision, ad=None), self.subject_id),
            (replace(self.decision, decided_at="2026-10-11T12:01:00Z"), self.subject_id),
        )
        for decision, subject_id in variants:
            with self.subTest(decision=decision.decision_id, subject_id=subject_id):
                with self.assertRaises(ValueError):
                    remember_decision(decision, subject_id)
        record = IssuedDecision.objects.get()
        self.assertEqual(record.subject_id, self.subject_id)
        self.assertEqual(record.slot_id, UUID(self.decision.slot_id))
        self.assertTrue(record.has_ad)

    def test_shared_decision_is_rejected_before_storage(self):
        with self.assertRaises(ValueError):
            remember_decision(replace(self.decision, audience="shared"), self.subject_id)
        self.assertFalse(IssuedDecision.objects.exists())

    def test_missing_and_other_user_decisions_are_not_disclosed(self):
        remember_decision(self.decision, self.subject_id)
        for decision_id, subject_id in (
            (uuid4(), self.subject_id),
            (self.decision.decision_id, uuid4()),
        ):
            with self.subTest(decision_id=decision_id):
                with self.assertRaisesRegex(DecisionNotFound, "발급한 광고 결정이 없습니다"):
                    reserve_impression(decision_id, subject_id, self.time)
        self.assertFalse(Impression.objects.exists())

    def test_no_ad_decision_cannot_create_impression(self):
        remember_decision(replace(self.decision, ad=None), self.subject_id)
        with self.assertRaises(NoAdForDecision):
            reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        self.assertFalse(Impression.objects.exists())

    def test_first_reservation_fixes_uuid_subject_and_original_timestamp(self):
        remember_decision(self.decision, self.subject_id)
        stored, created = reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        self.assertTrue(created)
        self.assertEqual(UUID(stored.reaction_id).version, 4)
        self.assertEqual(stored.decision_id, self.decision.decision_id)
        self.assertEqual(stored.subject_id, str(self.subject_id))
        self.assertEqual(stored.occurred_at, self.time)
        self.assertEqual(stored.delivery_state, "SENDING")
        self.assertIsNone(stored.status)
        self.assertIsNone(stored.reason_code)
        self.assertIsNone(stored.request_id)

    def test_duplicate_reservation_keeps_original_request_after_reload(self):
        remember_decision(self.decision, self.subject_id)
        first, _ = reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        # 함수 사이에 공유하는 객체 없이 DB에서 읽어도 최초 UUID와 원문 시각이 유지된다.
        again, created = reserve_impression(
            self.decision.decision_id.upper(), str(self.subject_id).upper(), "2026-10-11T12:00:30Z"
        )
        self.assertFalse(created)
        self.assertEqual(again, first)
        self.assertEqual(Impression.objects.count(), 1)

    def test_unconfirmed_impression_is_preserved_without_creating_a_new_request(self):
        remember_decision(self.decision, self.subject_id)
        first, _ = reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        result = finish_impression(first.reaction_id, delivery_state="UNCONFIRMED", lease_token=first.lease_token)
        again, created = reserve_impression(
            self.decision.decision_id, self.subject_id, "2026-10-11T12:00:30Z"
        )
        self.assertFalse(created)
        self.assertEqual(again, result)
        self.assertEqual(again.reaction_id, first.reaction_id)
        self.assertEqual(again.occurred_at, self.time)
        self.assertEqual(Impression.objects.count(), 1)

    def test_finish_changes_only_result_and_does_not_overwrite_first_outcome(self):
        remember_decision(self.decision, self.subject_id)
        first, _ = reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        result = finish_impression(
            first.reaction_id,
            lease_token=first.lease_token,
            delivery_state="ACKNOWLEDGED",
            status="REJECTED",
            reason_code="future_reason",
            request_id="first-request",
        )
        late = finish_impression(first.reaction_id, delivery_state="BLOCKED", request_id="late", lease_token=first.lease_token)
        self.assertEqual(late, result)
        self.assertEqual(result.reaction_id, first.reaction_id)
        self.assertEqual(result.subject_id, first.subject_id)
        self.assertEqual(result.occurred_at, first.occurred_at)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.reason_code, "future_reason")
        self.assertEqual(result.request_id, "first-request")

    def test_acknowledgement_can_be_saved_without_a_parseable_reaction(self):
        remember_decision(self.decision, self.subject_id)
        first, _ = reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        result = finish_impression(first.reaction_id, delivery_state="ACKNOWLEDGED", lease_token=first.lease_token)
        self.assertEqual(result.delivery_state, "ACKNOWLEDGED")
        self.assertIsNone(result.status)

    def test_database_unique_constraint_prevents_a_second_impression(self):
        remember_decision(self.decision, self.subject_id)
        first, _ = reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        # 서비스 검사를 우회해도 DB 고유 제약이 같은 결정의 두 번째 기록을 막는다.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Impression.objects.create(
                decision_id=self.decision.decision_id,
                subject_id=self.subject_id,
                occurred_at="2026-10-11T12:00:30Z",
            )
        self.assertEqual(Impression.objects.count(), 1)
        self.assertEqual(str(Impression.objects.get().reaction_id), first.reaction_id)

    def test_failed_transaction_leaves_no_partial_impression(self):
        remember_decision(self.decision, self.subject_id)
        # 저장 뒤 결과 변환이 실패해도 해당 원자적 작업 전체를 롤백한다.
        with patch("ad_bridge.impressions.store._snapshot", side_effect=RuntimeError("롤백")):
            with self.assertRaisesRegex(RuntimeError, "롤백"):
                reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        self.assertFalse(Impression.objects.exists())
        self.assertEqual(IssuedDecision.objects.count(), 1)

    def test_outer_transaction_is_rejected_before_reserving(self):
        remember_decision(self.decision, self.subject_id)
        # 호출자가 나중에 롤백할 수 있는 트랜잭션 안에서는 전송용 기록을 반환하지 않는다.
        with self.assertRaisesRegex(RuntimeError, "durable atomic"), transaction.atomic():
            reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        self.assertFalse(Impression.objects.exists())
        self.assertEqual(IssuedDecision.objects.count(), 1)

    def test_invalid_timestamp_is_rejected_without_a_record(self):
        remember_decision(self.decision, self.subject_id)
        for value in ("2026-10-11T12:00:01+09:00", "2026-13-11T12:00:01Z", "bad", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reserve_impression(self.decision.decision_id, self.subject_id, value)
        self.assertFalse(Impression.objects.exists())

    def test_invalid_finish_metadata_does_not_change_pending_request(self):
        remember_decision(self.decision, self.subject_id)
        first, _ = reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        for values in (
            {"delivery_state": "invalid"},
            {"delivery_state": "ACKNOWLEDGED", "status": "invalid"},
            {"delivery_state": "ACKNOWLEDGED", "request_id": 123},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                finish_impression(first.reaction_id, **values)
        again, _ = reserve_impression(self.decision.decision_id, self.subject_id, self.time)
        self.assertEqual(again, first)
