"""광고주 캠페인 화면용 조립(Step 3-2b, 계획 §8.1.1 — 각 서비스 `api` 의 값을 합치기만 한다). C6 `Campaign.today` 와 같은 값을 채운다."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from billing import api as billing
from campaigns import api as campaigns
from records import api as records

RECENT_DAYS = 7


@dataclass(frozen=True)
class Today:
    """오늘(예산 일)의 소진·남은 일예산과 리셋 시각(C6 `Today`)."""

    spent: int
    remaining: int
    resets_at: datetime


@dataclass(frozen=True)
class CampaignRow:
    campaign: object  # CampaignView
    today: Today
    recent: object | None  # 최근 7일 ReportTotals(성과가 없으면 None)


def _today(campaign, spent, now):
    return Today(spent, max(campaign.daily_budget - spent, 0), billing.next_reset(now))


def campaign_rows(user, now):
    """캠페인 목록(최근 등록순)과 오늘 소진·최근 7일 성과. 질의 수는 캠페인 수와 무관(캠페인 1 + 소진 1 + 성과 3)."""
    camps = campaigns.list_campaigns(user, now=now)
    spent = billing.spend_today([c.campaign_id for c in camps], now=now) if camps else {}
    today = billing.budget_day_of(now)
    recent = records.campaign_totals(user, billing.day_start(today - timedelta(days=RECENT_DAYS - 1)), billing.day_start(today + timedelta(days=1)))
    return [CampaignRow(c, _today(c, spent.get(c.campaign_id, 0), now), recent.get(c.campaign_id)) for c in camps]


def campaign_page(user, campaign_id, now):
    """캠페인 상세: (캠페인, 오늘, 광고그룹과 위치별 결과, 재검토 요청 내역). 남의 캠페인은 서비스가 404."""
    campaign = campaigns.get_campaign(user, campaign_id, now=now)
    spent = billing.spend_today([campaign.campaign_id], now=now).get(campaign.campaign_id, 0)
    groups = [g for g in campaigns.ad_group_effects(user) if g.campaign_id == campaign.campaign_id]
    return campaign, _today(campaign, spent, now), groups, campaigns.list_review_requests(user, campaign.campaign_id)


def placement_summary(group):
    """광고그룹의 위치별 결과를 화면용으로 센다: {나감, 하한 미만, 상한 적용, 꺼짐}."""
    count = lambda *reasons: sum(1 for e in group.effects if e.reason in reasons)  # noqa: E731
    return {"eligible": count("within_range", "capped_at_cap"), "below_floor": count("below_floor"), "capped": count("capped_at_cap"),
            "inactive": count("slot_inactive", "no_policy")}

