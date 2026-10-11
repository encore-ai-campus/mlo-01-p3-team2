"""campaigns 가 밖으로 내보내는 값 객체. 다른 모듈은 모델이 아니라 이것만 받는다(설계 R2, 계획 §6.0-1)."""
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SuspensionView:
    reason: str
    suspended_at: datetime
    open_review_request_id: uuid.UUID | None


@dataclass(frozen=True)
class CampaignView:
    campaign_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    starts_at: datetime
    ends_at: datetime | None
    daily_budget: int
    status: str  # 보이는 상태: 기간이 지났으면 저장된 상태가 아직 ACTIVE 여도 ENDED 다(판정은 engine 한 곳)
    ended_from: str | None  # 종료 직전 상태. ENDED 일 때만 값이 있다
    suspension: SuspensionView | None  # SUSPENDED 일 때만
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BidView:
    bid_id: uuid.UUID
    ad_group_id: uuid.UUID
    bid_version: int
    amount: int
    created_by: uuid.UUID
    created_at: datetime


@dataclass(frozen=True)
class AdGroupView:
    ad_group_id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    pricing_unit: str
    enabled: bool
    slot_ids: tuple
    current_bid: BidView | None
    created_at: datetime


@dataclass(frozen=True)
class CreativeView:
    creative_id: uuid.UUID
    ad_group_id: uuid.UUID
    title: str
    redirect_url: str
    image_name: str
    image_bytes: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreatedAd:
    """광고 만들기(`create_ad`)가 한 번에 만든 세 가지."""

    campaign: CampaignView
    ad_group: AdGroupView
    creative: CreativeView


@dataclass(frozen=True)
class MonitoredCampaign:
    """관리자 광고 모니터링의 한 줄(S5): 캠페인과 그 소재, 캠페인·소재 중 늦은 마지막 변경 시각."""

    campaign: CampaignView
    creatives: tuple  # CreativeView 들
    last_changed_at: datetime


@dataclass(frozen=True)
class ReviewRequestView:
    review_request_id: uuid.UUID
    campaign_id: uuid.UUID
    message: str
    status: str
    response_note: str
    created_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True)
class CandidateFacts:
    """슬롯 하나의 후보 후보. 판정은 하지 않은 **사실**이다(기간·금액 판정은 engine). records 가 이것으로 `Candidate` 를 조립한다."""

    owner_id: uuid.UUID
    campaign_id: uuid.UUID
    ad_group_id: uuid.UUID
    creative_id: uuid.UUID
    slot_id: uuid.UUID
    pricing_unit: str
    bid_id: uuid.UUID
    bid_amount: int
    bid_version: int
    bid_created_at: datetime
    campaign_status: str  # 저장된 상태
    ad_group_enabled: bool
    period_start: datetime
    period_end: datetime | None
    daily_budget: int
    title: str
    redirect_url: str
    image_name: str


@dataclass(frozen=True)
class ReviewQueueItem:
    """관리자 재검토 대기 목록의 한 줄: 열린 요청과 그 캠페인(중단 사유 포함), 그 캠페인의 소재(썸네일로 판단을 돕는다)."""

    review: ReviewRequestView
    campaign: CampaignView
    creatives: tuple = ()  # CreativeView 들


@dataclass(frozen=True)
class AdvertiserUsage:
    """관리자 광고주 목록의 사용량과 상한(남용 방지, 설계 §5.1). 업로드는 보유한 이미지 파일 총량(교체한 과거 파일 포함 — 상한 검사와 같은 기준)."""

    campaigns: int
    campaign_limit: int
    creatives: int
    creative_limit: int
    image_bytes: int
    image_bytes_limit: int


@dataclass(frozen=True)
class SlotEffect:
    """입찰 금액 하나가 **이 게재 위치의 현재 정책**에서 어떻게 취급되는지(C6 `SlotEffect`). 적용 금액 규칙은 engine 한 곳(`effect_of`)."""

    slot_id: uuid.UUID
    eligible: bool
    applied_amount: int | None
    reason: str  # within_range | capped_at_cap | below_floor | no_policy | slot_inactive
    policy_version: int | None


@dataclass(frozen=True)
class AdGroupEffects:
    """광고그룹 하나의 현재 입찰과 게재 위치별 결과(알림·화면 조립용). 입찰이 없으면 `bid_amount` 가 `None` 이고 `effects` 는 비어 있다."""

    ad_group_id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    pricing_unit: str
    enabled: bool
    bid_amount: int | None
    bid_created_at: datetime | None
    effects: tuple  # SlotEffect 들
