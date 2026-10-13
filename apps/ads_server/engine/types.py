"""engine 의 입력·출력 타입. 모두 불변이고 생성할 때 검증한다(설계 §4.3).

`engine` 은 Django·프로젝트 모듈을 import 하지 않는다. 호출하는 쪽(`records`)이 값을 모아 이 타입으로 넘긴다.
금액은 정수 포인트, 시각은 UTC 이다.
"""
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta

CAMPAIGN_STATUSES = ("ACTIVE", "PAUSED", "SUSPENDED", "ENDED")
CAMPAIGN_ACTIVE = "ACTIVE"


def _uuid(name, value):
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{name} 은(는) UUID 여야 한다: {value!r}")


def _int(name, value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 은(는) 정수여야 한다: {value!r}")
    if value < minimum:
        raise ValueError(f"{name} 은(는) {minimum} 이상이어야 한다: {value!r}")


def _utc(name, value, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} 은(는) UTC 시각이어야 한다: {value!r}")


@dataclass(frozen=True)
class Candidate:
    """(광고그룹 × 소재 × 요청 슬롯) 하나의 **판정 전 사실**. `records` 가 만든다."""

    # 식별
    campaign_id: uuid.UUID
    ad_group_id: uuid.UUID
    creative_id: uuid.UUID
    slot_id: uuid.UUID
    # 입찰
    bid_amount: int
    bid_version: int
    bid_created_at: datetime
    # 정책 스냅샷
    floor: int
    base: int
    cap: int
    policy_version: int
    # 자격 판정용 사실
    campaign_status: str
    ad_group_enabled: bool
    period_start: datetime
    period_end: datetime | None  # 없으면 계속 진행
    wallet_balance: int
    remaining_daily_budget: int

    def __post_init__(self):
        for name in ("campaign_id", "ad_group_id", "creative_id", "slot_id"):
            _uuid(name, getattr(self, name))
        if self.campaign_status not in CAMPAIGN_STATUSES:
            raise ValueError(f"campaign_status 가 올바르지 않다: {self.campaign_status!r}")
        if not isinstance(self.ad_group_enabled, bool):
            raise TypeError("ad_group_enabled 은(는) bool 이어야 한다")
        for name in ("bid_amount", "floor", "base", "cap"):
            _int(name, getattr(self, name))
        for name in ("bid_version", "policy_version"):
            _int(name, getattr(self, name), minimum=1)
        for name in ("wallet_balance", "remaining_daily_budget"):
            _int(name, getattr(self, name))
        if not self.floor <= self.base <= self.cap:
            raise ValueError("정책은 하한 ≤ 기준가 ≤ 상한이어야 한다")
        _utc("bid_created_at", self.bid_created_at)
        _utc("period_start", self.period_start)
        _utc("period_end", self.period_end, nullable=True)


@dataclass(frozen=True)
class Eligible(Candidate):
    """`Candidate` + 적용 금액. 필터를 통과한 것만 `SelectionPolicy` 에 들어간다."""

    applied_amount: int = field(default=0)

    def __post_init__(self):
        super().__post_init__()
        _int("applied_amount", self.applied_amount, minimum=1)

    @classmethod
    def of(cls, candidate, applied_amount):
        return cls(**{f.name: getattr(candidate, f.name) for f in fields(Candidate)}, applied_amount=applied_amount)


@dataclass(frozen=True)
class AdRequest:
    """광고 요청. `now` 는 호출자가 주입한다(엔진은 시계를 읽지 않는다)."""

    slot_id: uuid.UUID
    now: datetime
    subject_id: str | None = None  # V1 알고리즘은 읽지 않는다. 이후 알고리즘이 시그니처 변경 없이 쓰도록 항상 전달한다

    def __post_init__(self):
        _uuid("slot_id", self.slot_id)
        _utc("now", self.now)


@dataclass(frozen=True)
class Effect:
    """입찰 하나가 **이 슬롯의 정책**에서 어떻게 취급되는지(설계 §4.2). 콘솔의 `effects` 와 같은 `reason` 값을 쓴다."""

    eligible: bool
    applied_amount: int | None
    reason: str  # within_range | capped_at_cap | below_floor


@dataclass(frozen=True)
class Selection:
    """선택 결과. `chosen` 이 없으면 광고 없음. `trace` 는 알고리즘별 판단 근거로 Decision 에 그대로 저장된다."""

    chosen: Eligible | None
    trace: dict


@dataclass(frozen=True)
class DecisionResult:
    selection: Selection
    considered: int  # 들어온 후보 수
    rejected: dict  # 필터 거절 사유 → 개수
