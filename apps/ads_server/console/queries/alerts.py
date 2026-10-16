"""알림 패널(Step 3-2a, C6 `/alerts`, 계획 S5). 저장된 알림이 아니라 **지금 상태에서 계산**한 조건이라, 조건이 풀리면 사라진다.

각 서비스 `api` 의 값을 합치기만 한다: 적용 금액은 campaigns(engine 의 `effect_of`), 잔액·오늘 소진은 billing. 비교는 결정 엔진의 후보 거르기와 같다 —
남은 일예산이나 잔액이 적용 금액보다 적으면 그 위치에 나가지 않는다(`engine/filters/budget.py`·`balance.py`). 잔액 두 단계는 설계 D3-4.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from billing import api as billing
from campaigns import api as campaigns
from foundation.api import errors

ENDED_RECENTLY = timedelta(days=7)  # 끝난 상태는 풀리지 않으므로 끝난 뒤 7일 동안만 알린다
_SEVERITY = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Alert:
    """C6 `Alert` 한 건. `target_type` 은 campaign · ad_group · wallet."""

    code: str
    severity: str
    target_type: str
    target_id: uuid.UUID
    message: str
    since: datetime


def alerts_for(user, now, camps, wallet):
    """광고주의 알림(심각한 것 → 최근 것 순). `camps`·`wallet` 은 화면이 읽은 캠페인 목록(`now` 기준)과 지갑(없으면 `None`) — 화면의 다른 칸과
    같은 읽기를 본다. 질의 수는 캠페인·광고그룹 수와 무관하다."""
    active = {c.campaign_id: c for c in camps if c.status == "ACTIVE"}
    groups = [g for g in campaigns.ad_group_effects(user) if g.enabled and g.campaign_id in active]
    applied_by_campaign = {}
    for g in groups:
        applied_by_campaign.setdefault(g.campaign_id, []).extend(e.applied_amount for e in g.effects if e.eligible)
    alerts = _campaign_alerts(camps, campaigns.latest_review_requests(user), now)
    alerts += _budget_alerts(active, applied_by_campaign, now)
    alerts += _bid_alerts(groups)
    alerts += _balance_alerts(user, wallet, [a for amounts in applied_by_campaign.values() for a in amounts], now)
    return sorted(alerts, key=lambda a: (_SEVERITY[a.severity], -a.since.timestamp()))


def has_alerts(user, now):
    """헤더 종의 점(6-21d): 대시보드 알림 패널과 같은 계산에 한 건이라도 있는지. 광고주 화면마다 부른다(질의 수는 캠페인 수와 무관)."""
    try:
        wallet = billing.get_wallet(user, now=now)
    except errors.NotFound:  # 가입 절차를 거치지 않은 옛 계정
        wallet = None
    return bool(alerts_for(user, now, campaigns.list_campaigns(user, now=now), wallet))


def _campaign_alerts(camps, reviews, now):
    alerts = []
    for c in camps:
        if c.status == "SUSPENDED":
            alerts.append(Alert("campaign_suspended", "critical", "campaign", c.campaign_id,
                                f"‘{c.name}’ 캠페인을 관리자가 중단했습니다. 사유: {c.suspension.reason}", c.suspension.suspended_at))
            review = reviews.get(c.campaign_id)
            if review and review.status == "REJECTED" and review.closed_at >= c.suspension.suspended_at:  # 이번 중단에 대한 반려만
                alerts.append(Alert("review_rejected", "warning", "campaign", c.campaign_id,
                                    f"‘{c.name}’ 재검토 요청이 반려됐습니다. 답변: {review.response_note}", review.closed_at))
        elif c.status == "ENDED":
            ended_at = c.ends_at if c.ends_at is not None and c.ends_at <= now else c.updated_at  # 기간 만료 또는 광고주가 끝낸 시각
            if now - ended_at < ENDED_RECENTLY:
                alerts.append(Alert("campaign_ended", "info", "campaign", c.campaign_id, f"‘{c.name}’ 캠페인이 끝났습니다.", ended_at))
    return alerts


def _budget_alerts(active, applied_by_campaign, now):
    if not active:
        return []
    spent = billing.spend_today(list(active), now=now)
    alerts = []
    for campaign_id, c in active.items():
        remaining = c.daily_budget - spent.get(campaign_id, 0)
        cheapest = min(applied_by_campaign.get(campaign_id) or [1])  # 나갈 위치가 없으면 '남은 예산이 없다'로만 본다
        if remaining < cheapest:
            alerts.append(Alert("budget_exhausted", "warning", "campaign", campaign_id,
                                f"‘{c.name}’ 오늘 일예산({c.daily_budget:,} 포인트)을 다 써서 다음 리셋까지 노출되지 않습니다.", billing.day_start(billing.budget_day_of(now))))
    return alerts


def _bid_alerts(groups):
    alerts = []
    for g in groups:
        below = sum(1 for e in g.effects if e.reason == "below_floor")
        capped = sum(1 for e in g.effects if e.reason == "capped_at_cap")
        if below:
            alerts.append(Alert("bid_below_floor", "warning", "ad_group", g.ad_group_id,
                                f"‘{g.name}’ 입찰({g.bid_amount:,} 포인트)이 하한보다 낮아 구성 {below}곳에 노출되지 않습니다.", g.bid_created_at))
        if capped:
            alerts.append(Alert("bid_capped", "info", "ad_group", g.ad_group_id,
                                f"‘{g.name}’ 입찰이 상한을 넘어 구성 {capped}곳에서는 상한 금액으로 적용됩니다.", g.bid_created_at))
    return alerts


def _balance_alerts(user, wallet, applied, now):
    if not applied or wallet is None:
        return []
    if wallet.balance < min(applied):
        return [Alert("balance_insufficient", "critical", "wallet", user.pk,
                      f"잔액({wallet.balance:,} 포인트)이 가장 낮은 적용 금액보다 적어 어느 구성에도 노출되지 않습니다.", now)]
    if wallet.balance < max(applied):
        return [Alert("balance_low", "warning", "wallet", user.pk,
                      f"잔액({wallet.balance:,} 포인트)이 일부 적용 금액보다 적어 그 구성에는 노출되지 않습니다.", now)]
    return []
