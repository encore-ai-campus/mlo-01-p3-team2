"""캠페인 상태 전이 표 — **상태를 쓰는 곳은 이 파일뿐이다**(설계 §4.4-5). 재검토 요청의 상태 변경도 여기서 한다.

| 동작 | 이전 → 이후 | 누가 |
|---|---|---|
| pause | ACTIVE → PAUSED | 광고주 |
| resume | PAUSED → ACTIVE | 광고주 |
| suspend | ACTIVE·PAUSED → SUSPENDED | 관리자 |
| release | SUSPENDED → ACTIVE | 관리자 |
| end | ACTIVE·PAUSED → ENDED (`ends_at` 을 현재로 확정) | 광고주 |
| expire | ACTIVE·PAUSED·SUSPENDED → ENDED | 시스템(`ends_at ≤ now`) |

`ENDED` 에서 나가는 전이는 없다. 종료 판정(`is_expired`)은 engine 한 곳이고, 이 파일은 그 결과를 상태로 옮길 뿐이다.
"""
from django.db.models import F

from engine.api import is_expired

from .errors import CampaignEnded, CampaignSuspended, InvalidTransition
from .models import Campaign, CampaignStatus, ReviewRequest, ReviewStatus

ADVERTISER, ADMIN, SYSTEM = "advertiser", "admin", "system"
ACTIVE, PAUSED, SUSPENDED, ENDED = (CampaignStatus.ACTIVE, CampaignStatus.PAUSED, CampaignStatus.SUSPENDED, CampaignStatus.ENDED)

TRANSITIONS = {
    "pause": ({ACTIVE}, PAUSED, ADVERTISER),
    "resume": ({PAUSED}, ACTIVE, ADVERTISER),
    "suspend": ({ACTIVE, PAUSED}, SUSPENDED, ADMIN),
    "release": ({SUSPENDED}, ACTIVE, ADMIN),
    "end": ({ACTIVE, PAUSED}, ENDED, ADVERTISER),
    "expire": ({ACTIVE, PAUSED, SUSPENDED}, ENDED, SYSTEM),
}


def assert_open(campaign, now):
    """종료된 캠페인(저장된 상태가 아직 갱신되기 전이라도 기간이 지났으면 포함)에는 어떤 쓰기도 하지 않는다."""
    if campaign.status == ENDED or is_expired(campaign.ends_at, now):
        raise CampaignEnded()


def close_review_request(review, status, now, note=""):
    review.status = status
    review.response_note = note
    review.closed_at = now
    review.save(update_fields=["status", "response_note", "closed_at"])


def apply(campaign, action, by, now, reason=""):
    """전이 하나를 적용하고 저장한다. 호출한 쪽이 바깥 트랜잭션을 연다."""
    allowed_from, to, who = TRANSITIONS[action]
    if by != who:
        raise ValueError(f"{action} 은(는) {who} 만 할 수 있다")
    if campaign.status == ENDED:
        raise CampaignEnded()
    if action != "expire":  # expire 는 기간이 지났을 때 하는 동작이라 기간 가드를 건너뛴다
        assert_open(campaign, now)
    if by == ADVERTISER and campaign.status == SUSPENDED:
        raise CampaignSuspended()
    if campaign.status not in allowed_from:
        raise InvalidTransition(f"{campaign.status} 상태에서는 {action} 을(를) 할 수 없습니다.")
    previous = campaign.status
    campaign.status = to
    if to == ENDED:
        campaign.ended_from = previous
        if action == "end":  # 조기 종료: 종료 시점을 확정한다(아직 시작 전이면 시작 시각으로)
            campaign.ends_at = max(now, campaign.starts_at)
    if to == SUSPENDED:
        campaign.suspended_reason, campaign.suspended_at = reason, now
    if action == "release":
        campaign.suspended_reason, campaign.suspended_at = "", None
    campaign.updated_at = now
    campaign.save()
    if action == "release":
        for review in ReviewRequest.objects.filter(campaign=campaign, status=ReviewStatus.OPEN):
            close_review_request(review, ReviewStatus.RELEASED, now)
    elif to == ENDED:
        for review in ReviewRequest.objects.filter(campaign=campaign, status=ReviewStatus.OPEN):
            close_review_request(review, ReviewStatus.CLOSED_ENDED, now)
    return previous


def expire_due(now):
    """기간이 지난 캠페인을 `ENDED` 로. 조건부 UPDATE 라 멱등이고, 연장과 겹치면 먼저 커밋된 쪽이 이긴다. 바뀐 캠페인 ID 목록을 돌려준다."""
    due = list(
        Campaign.objects.filter(ends_at__lte=now).exclude(status=ENDED).values_list("campaign_id", flat=True)
    )
    if not due:
        return []
    changed = list(Campaign.objects.filter(pk__in=due, ends_at__lte=now).exclude(status=ENDED).values_list("campaign_id", flat=True))
    Campaign.objects.filter(pk__in=changed, ends_at__lte=now).exclude(status=ENDED).update(
        ended_from=F("status"), status=ENDED, updated_at=now
    )
    ReviewRequest.objects.filter(campaign_id__in=changed, status=ReviewStatus.OPEN).update(
        status=ReviewStatus.CLOSED_ENDED, closed_at=now
    )
    return changed
