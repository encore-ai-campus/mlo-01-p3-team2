from ..types import CAMPAIGN_ACTIVE


def check(candidate, effect, request):
    if candidate.campaign_status != CAMPAIGN_ACTIVE:
        return "campaign_not_active"
    if not candidate.ad_group_enabled:
        return "ad_group_disabled"
    return None
