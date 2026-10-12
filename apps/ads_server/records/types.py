"""records 가 밖으로 내보내는 값 객체(설계 R2)."""
import uuid
from dataclasses import dataclass
from datetime import date, datetime


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
    audience: str  # 슬롯 성격 스냅샷: `individual` | `shared`
    decided_at: datetime
    chosen: ChosenView | None  # 광고 없음이면 None
    selection_policy: str
    trace: dict
    candidate_count: int
    rejected_counts: dict


@dataclass(frozen=True)
class ReportTotals:
    """인정된(`ACCEPTED`) 반응의 합과 소진 포인트. 비율은 저장하지 않고 필요할 때 계산한다(분모가 0 이면 `None`)."""

    impressions: int
    clicks: int
    conversions: int  # 이 구간에 **받은** 전환 수(수신일 기준) — 이전 구간 클릭의 전환도 들어 있다
    converted_clicks: int  # 이 구간에 받은 클릭 중 인정된 전환이 이어진 클릭 수(클릭 코호트). 전환이 나중에 와도 조회 시점에 센다. 항상 clicks 이하
    spent: int

    @property
    def ctr(self):
        """클릭률 = 클릭 / 노출."""
        return self.clicks / self.impressions if self.impressions else None

    @property
    def conversion_rate(self):
        """전환율 = 클릭 코호트 기준: 이 구간의 클릭 중 전환으로 이어진 비율(`converted_clicks / clicks`)이라 1 을 넘지 않는다.

        `conversions / clicks` 로 나누지 않는다: 전환은 수신일, 클릭도 수신일로 세므로 이전 구간 클릭의 전환이 섞여 1 을 넘을 수 있다.
        """
        return self.converted_clicks / self.clicks if self.clicks else None


@dataclass(frozen=True)
class ReportRow:
    date: date  # 예산 일 경계 기준의 날짜
    totals: ReportTotals


@dataclass(frozen=True)
class DailyReportView:
    start: datetime  # 포함
    end: datetime  # 미포함
    rows: tuple  # ReportRow, 구간의 **모든 날**(반응이 없는 날도 0 으로)
    totals: ReportTotals
    previous_totals: ReportTotals  # 바로 앞의 같은 길이 구간(증감률용)


@dataclass(frozen=True)
class ReactionView:
    inbox_id: uuid.UUID  # 서버 쪽 식별자(응답에 싣지 않는다. 처리 단계가 쓴다)
    reaction_id: uuid.UUID
    decision_id: uuid.UUID
    type: str
    occurred_at: datetime
    received_at: datetime
    status: str
    reason_code: str | None
    subject_id: str | None = None  # 보고에 실린 사람(소문자 UUID). 없으면 None
