"""광고주 포인트(Step 3-2e): 잔액·오늘 소진·리셋 시각과 원장 내역(최신순 커서 쪽 나누기, 과금 줄은 캠페인 이름). 자기 원장만 보인다(서비스가 로그인한 광고주로 좁힌다)."""
from django.utils import timezone

from billing import api as billing
from campaigns import api as campaigns
from foundation.api import errors

from .common import present


def _now():
    return timezone.now()


def points(request):
    try:
        wallet = billing.get_wallet(request.user, now=_now())
    except errors.NotFound:  # 가입 절차를 거치지 않은 옛 계정
        wallet = None
    entries, next_cursor = billing.list_ledger(request.user, before=request.GET.get("before"))  # 틀린 커서는 첫 쪽(서비스)
    return present(request, "console/points.html", {
        "wallet": wallet, "entries": entries, "next_cursor": next_cursor,
        "names": campaigns.campaign_names({e.campaign_id for e in entries if e.campaign_id}),
    })
