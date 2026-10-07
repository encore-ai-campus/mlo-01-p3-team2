"""masters 가 밖으로 내보내는 값 객체. 다른 모듈은 모델이 아니라 이것만 받는다(설계 R2, 계획 §6.0-1)."""
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MediaView:
    media_id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime


@dataclass(frozen=True)
class PolicyView:
    slot_id: uuid.UUID
    policy_version: int
    floor: int
    base: int
    cap: int
    changed_by: uuid.UUID
    changed_at: datetime
    reason: str


@dataclass(frozen=True)
class SlotView:
    slot_id: uuid.UUID
    media_id: uuid.UUID
    media_name: str
    media_is_active: bool
    name: str
    pricing_unit: str
    is_active: bool
    policy: PolicyView  # 현재 정책. 슬롯은 항상 정책을 가진다(create_slot 이 함께 만든다)
