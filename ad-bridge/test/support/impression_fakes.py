"""서비스·게임·재전송 검사가 공유하는 메모리 저장소와 응답 fixture."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ad_bridge.impressions.store import DecisionNotFound, NoAdForDecision, StoredImpression
from ad_bridge.api.types import Reaction


DECISION_ID = "22334455-1234-4234-8234-123456789abc"
SUBJECT_ID = "11223344-1234-4234-8234-123456789abc"
REACTION_ID = "44556677-1234-4234-8234-123456789abc"
OCCURRED_AT = "2026-10-11T12:00:00Z"
PRIVATE_KEY = "private-key-never-return-or-store"


def received_reaction(**payload):
    return Reaction(
        reaction_id=payload["reaction_id"], decision_id=payload["decision_id"],
        subject_id=payload["subject_id"], type="IMPRESSION",
        occurred_at=payload["occurred_at"], received_at="2026-10-11T12:00:01Z",
        status="RECEIVED", reason_code=None, request_id="request-received",
    )


class MemoryImpressionStore:
    """예약 완료 상태와 쓰기 실패 위치를 관측하는 테스트 전용 저장소."""

    def __init__(self, *, owner=SUBJECT_ID, subject=SUBJECT_ID, has_ad=True):
        self.owner = str(owner)
        self.subject = str(subject)
        self.has_ad = has_ad
        self.records = {}
        self.events = []
        self.reserve_error = None
        self.finish_error = None

    @property
    def record(self):
        return self.records.get(REACTION_ID)

    @record.setter
    def record(self, value):
        if value is None:
            self.records.pop(REACTION_ID, None)
        else:
            self.records[value.reaction_id] = value

    def reserve_impression(self, decision_id, owner_id, occurred_at, *, now=None, lease_seconds=60):
        self.events.append("reserve")
        if self.reserve_error:
            raise self.reserve_error
        if str(decision_id) != DECISION_ID or str(owner_id) != self.owner:
            raise DecisionNotFound()
        if not self.has_ad:
            raise NoAdForDecision()
        if self.record is not None:
            return self.record, False
        current = now or datetime.now(timezone.utc)
        self.record = StoredImpression(
            decision_id=str(decision_id), reaction_id=REACTION_ID,
            subject_id=self.subject, occurred_at=occurred_at, delivery_state="SENDING",
            attempts=1, lease_token=str(uuid4()),
            lease_expires_at=current + timedelta(seconds=lease_seconds),
        )
        return self.record, True

    def finish_impression(self, reaction_id, **changes):
        self.events.append("finish")
        if self.finish_error:
            raise self.finish_error
        record = self.records.get(reaction_id)
        if record is None:
            raise AssertionError("예약하지 않은 반응을 완료 처리했습니다.")
        token = changes.pop("lease_token", None)
        # 오래된 작업자의 실패가 최신 결과를 덮지 않도록 실제 저장소 계약을 흉내 낸다.
        acknowledged = changes["delivery_state"] == "ACKNOWLEDGED"
        if record.delivery_state == "ACKNOWLEDGED":
            return record
        suggested_at = changes.get("next_attempt_at")
        if token != record.lease_token and not acknowledged:
            # 늦게 도착한 대기 지시는 상태·예약을 건드리지 않고 다음 시각만 늦출 수 있다.
            if (changes["delivery_state"] == "UNCONFIRMED"
                    and record.delivery_state in {"SENDING", "UNCONFIRMED"}
                    and suggested_at is not None
                    and (record.next_attempt_at is None or suggested_at > record.next_attempt_at)):
                record = replace(record, next_attempt_at=suggested_at)
                self.records[reaction_id] = record
            return record
        if changes["delivery_state"] == "UNCONFIRMED" and record.next_attempt_at is not None:
            if suggested_at is None or suggested_at < record.next_attempt_at:
                changes["next_attempt_at"] = record.next_attempt_at
        if acknowledged:
            changes["next_attempt_at"] = None
        saved = replace(record, **changes, lease_token=None, lease_expires_at=None)
        self.records[reaction_id] = saved
        return saved

    def claim_due_impression(self, *, now, lease_seconds):
        self.events.append("claim")
        for reaction_id, record in self.records.items():
            unconfirmed = record.delivery_state == "UNCONFIRMED" and (
                record.next_attempt_at is None or record.next_attempt_at <= now
            )
            abandoned = (record.delivery_state == "SENDING"
                         and (record.lease_expires_at is None or record.lease_expires_at <= now)
                         and (record.next_attempt_at is None or record.next_attempt_at <= now))
            if unconfirmed or abandoned:
                claimed = replace(
                    record, delivery_state="SENDING", attempts=record.attempts + 1,
                    lease_token=str(uuid4()), lease_expires_at=now + timedelta(seconds=lease_seconds),
                    next_attempt_at=None,
                )
                self.records[reaction_id] = claimed
                return claimed
        return None


