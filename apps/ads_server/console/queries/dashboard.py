"""대시보드 화면용 조립(계획 §8.1.1: 여러 모듈의 값을 **합치기만** 한다 — 규칙은 각 서비스 `api` 에 있다)."""
from campaigns import api as campaigns
from records import api as records

TOP = 5


def top_campaigns(user, start, end, limit=TOP):
    """기간에 성과가 있는 캠페인을 소진 포인트 → 노출 → 이름 순으로 `limit` 개. `[(CampaignView, ReportTotals)]`."""
    totals = records.campaign_totals(user, start, end)
    named = {c.campaign_id: c for c in campaigns.list_campaigns(user)}
    ranked = sorted(((named[cid], t) for cid, t in totals.items() if cid in named), key=lambda pair: (-pair[1].spent, -pair[1].impressions, pair[0].name))
    return ranked[:limit]
