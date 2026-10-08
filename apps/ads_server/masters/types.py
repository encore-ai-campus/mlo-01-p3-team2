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
class MediaIdentity:
    """키 인증에 성공한 매체. 매체가 비활성이어도 만들어진다(403 은 호출하는 쪽이 판단한다)."""

    media_id: uuid.UUID
    key_id: uuid.UUID
    media_is_active: bool


@dataclass(frozen=True)
class IssuedKey:
    """발급 결과. **`key` 는 이 한 번만 보인다**(저장하지 않는다)."""

    key_id: uuid.UUID
    media_id: uuid.UUID
    key: str
    created_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class MediaKeyView:
    key_id: uuid.UUID
    media_id: uuid.UUID
    label: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    active: bool


@dataclass(frozen=True)
class PolicyView:
    bid_policy_id: uuid.UUID
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
    audience: str  # `individual` | `shared`
    max_viewers: int | None  # `shared` 일 때만
    is_active: bool
    policy: PolicyView  # 현재 정책. 슬롯은 항상 정책을 가진다(create_slot 이 함께 만든다)
