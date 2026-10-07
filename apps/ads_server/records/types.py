"""records 가 밖으로 내보내는 값 객체(설계 R2)."""
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ChosenView:
    owner_id: uuid.UUID
    campaign_id: uuid.UUID
    ad_group_id: uuid.UUID
    creative_id: uuid.UUID
    pricing_unit: str
    bid_amount: int
    applied_amount: int
    bid_version: int
    policy_version: int
    bid_id: uuid.UUID
    bid_policy_id: uuid.UUID
    title: str  # 광고주가 입력한 값: 신뢰할 수 없는 문자열(이스케이프는 소비자 몫, 계약 C1)
    redirect_url: str
    image_name: str
    image_url: str  # 응답 단계에서 이름으로 만든다(저장하지 않는다)


@dataclass(frozen=True)
class DecisionView:
    decision_id: uuid.UUID
    media_id: uuid.UUID
    slot_id: uuid.UUID
    subject_id: str | None
    decided_at: datetime
    chosen: ChosenView | None  # 광고 없음이면 None
    selection_policy: str
    trace: dict
    candidate_count: int
    rejected_counts: dict
