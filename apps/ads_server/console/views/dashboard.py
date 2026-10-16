"""광고주 대시보드(Step 3-2a). 기간의 일별 성과(`records.daily_report`)·상위 캠페인·알림(`console/queries`)·포인트(`billing.get_wallet`)를 부르고 그리기만 한다.

기간은 **오늘을 포함한 최근 N일**(예산 일 경계)이고 비교는 바로 앞의 같은 길이 구간이다(설계 D3-5). 오늘 칸은 아직 집계 중이라 표시한다.
"""
from datetime import timedelta

from django.utils import timezone

from billing import api as billing
from campaigns import api as campaigns
from foundation.api import errors
from records import api as records

from ..forms import METRICS, PeriodForm
from ..queries.alerts import alerts_for
from ..queries.dashboard import TOP, top_campaigns
from .common import present


def _now():
    return timezone.now()


def advertiser_home(request):
    form = PeriodForm(request.GET or None)
    chosen = form.values()
    if form.is_bound and not form.is_valid():
        form = PeriodForm(initial=chosen)
    now = _now()
    today = billing.budget_day_of(now)
    start, end = billing.day_start(today - timedelta(days=chosen["days"] - 1)), billing.day_start(today + timedelta(days=1))
    report = records.daily_report(request.user, start, end)
    try:
        wallet = billing.get_wallet(request.user, now=now)
    except errors.NotFound:  # 가입 절차를 거치지 않은 옛 계정
        wallet = None
    camps = campaigns.list_campaigns(request.user, now=now)  # 지갑과 함께 상위 캠페인 표·알림이 같은 읽기를 본다
    alerts = alerts_for(request.user, now, camps, wallet)
    return present(request, "console/advertiser_home.html", {
        "form": form, "days": chosen["days"], "metric": chosen["metric"], "metric_label": dict(METRICS)[chosen["metric"]],
        "metrics": METRICS, "report": report, "today": today, "wallet": wallet, "top": top_campaigns(request.user, start, end, camps), "top_limit": TOP,
        "alerts": alerts, "has_alerts": bool(alerts),  # 헤더 종의 점 — 패널과 같은 계산(다른 화면은 views/common.py 가 계산)
        "campaign_count": len(camps),  # 0 이면 처음 사용 화면(시작하기 3단계 — 6-21c)
        "daily_budget_total": sum(c.daily_budget for c in camps if c.status == "ACTIVE"),  # 지갑 칸의 '일예산 합계 대비 오늘 소진'(6-21c) — 같은 읽기, 질의 없음
    })
