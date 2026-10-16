"""engine 테스트용 값 도우미. Django 를 쓰지 않는다."""
import uuid
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SLOT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def cand(**kw):
    from engine.api import Candidate

    values = dict(
        campaign_id=uuid.uuid4(), ad_group_id=uuid.uuid4(), creative_id=uuid.uuid4(), slot_id=SLOT,
        bid_amount=30, bid_version=1,
        floor=10, cap=50, policy_version=1,
        campaign_status="ACTIVE", ad_group_enabled=True,
        period_start=NOW - timedelta(days=1), period_end=NOW + timedelta(days=1),
        wallet_balance=10_000, remaining_daily_budget=10_000,
    )
    values.update(kw)
    return Candidate(**values)


def request(**kw):
    from engine.api import AdRequest

    values = dict(slot_id=SLOT, now=NOW, subject_id="subject-1")
    values.update(kw)
    return AdRequest(**values)
