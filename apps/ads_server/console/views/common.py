"""광고주 화면이 함께 쓰는 그리기(6-21d, 설계 §10 "광고주 화면 v2"): 화면 데이터에 헤더의 알림 표시(`has_alerts`)를 더한다.
알림은 저장하지 않고 지금 상태에서 계산하므로(대시보드 패널과 같은 `alerts_for`) 화면마다 다시 계산한다. 대시보드는 패널을 그리며 이미 계산해 직접 싣는다."""
from django.utils import timezone

from foundation.api import present as _present

from ..queries.alerts import has_alerts


def present(request, template, context=None, **kwargs):
    context = context or {}
    if request.user.is_authenticated and request.user.role == "advertiser" and "has_alerts" not in context:
        context = {**context, "has_alerts": has_alerts(request.user, timezone.now())}
    return _present(request, template, context, **kwargs)
