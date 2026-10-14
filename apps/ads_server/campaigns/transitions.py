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
    # 열린 재검토 요청(캠페인당 최대 1건)은 UPDATE 한 번으로 닫는다 — `expire_due` 와 같은 방식, 캠페인 행 잠금 안이다
    if action == "release":
        ReviewRequest.objects.filter(campaign=campaign, status=ReviewStatus.OPEN).update(status=ReviewStatus.RELEASED, closed_at=now)
    elif to == ENDED:
        ReviewRequest.objects.filter(campaign=campaign, status=ReviewStatus.OPEN).update(status=ReviewStatus.CLOSED_ENDED, closed_at=now)
    return previous


def expire_due(now):
    """기간이 지난 캠페인을 `ENDED` 로. 바뀐 캠페인 ID 목록을 돌려준다. **바깥 트랜잭션 안에서 부른다.**

    후보를 잠금 없이 고른 뒤 **기본 키로** 행을 잠그고(`FOR UPDATE`), 잠근 뒤의 값으로 종료 여부를 다시 본다(`is_expired`): 연장·중단처럼 캠페인 행을 쓰는 동작은
    같은 행 잠금을 쥐고 하므로(services 의 `_campaign(lock=True)`), 먼저 커밋된 쪽이 이기고 진 쪽은 그 결과를 보고 판단한다. 재검토 요청 정리와 감사 로그는 **실제로 바뀐 행에만** 한다.
    잠금을 `ends_at`·`status` 보조 색인으로 잡지 않는다: 보조 색인 레코드를 먼저 잡은 쪽과 기본 키 행을 먼저 잡고 색인 열을 바꾸는 쪽이 서로를 기다려 교착이 난다(1213).
    """
    candidates = list(
        Campaign.objects.filter(ends_at__lte=now).exclude(status=ENDED).values_list("campaign_id", flat=True)
    )
    if not candidates:
        return []
    due = [
        c.campaign_id for c in Campaign.objects.select_for_update().filter(pk__in=candidates).order_by("pk")
        if c.status != ENDED and is_expired(c.ends_at, now)
    ]
    if not due:
        return []
    Campaign.objects.filter(pk__in=due).update(ended_from=F("status"), status=ENDED, updated_at=now)
    ReviewRequest.objects.filter(campaign_id__in=due, status=ReviewStatus.OPEN).update(status=ReviewStatus.CLOSED_ENDED, closed_at=now)
    return due
