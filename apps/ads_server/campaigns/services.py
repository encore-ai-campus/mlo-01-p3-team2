"""campaigns 의 규칙. 광고주용 함수는 `user` 를 받고 소유권 헬퍼를 지난다(남의 것은 404, 위협 T4).

금액 계산(적용 금액·하한 판정)은 하지 않는다 — 입찰·상태·기간의 **값만 공급**한다(설계 §4.2, engine 한 곳).
시계는 `now` 인자로 받는다. 안 주면 `_now()` 한 곳에서만 읽는다.
"""
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlsplit

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from assets.api import store, validate_image
from engine.api import effect_of, is_expired
from foundation.api import MAX_AMOUNT, clean_request_key, clean_text, errors, is_int, is_request_key, owned_or_404, parse_uuid, parse_uuids, record_audit, require_admin, require_advertiser
from masters import api as masters

from . import transitions as tr
from .errors import CampaignSuspended, LimitExceeded, NotSuspended, ReviewPending, UnitImmutable, UnitMismatch
from .models import AdGroup, AdGroupCreative, AdGroupSlot, AdvertiserQuota, Bid, Campaign, CampaignStatus, Creative, CreativeImage, ReviewRequest, ReviewStatus
from .types import (
    AdGroupEffects, AdGroupView, AdvertiserUsage, BidView, CampaignView, CandidateFacts, CreatedAd, CreativeUse, CreativeView, MonitoredCampaign, OwnedCreative,
    ReviewQueueItem, ReviewRequestView, SlotEffect, SuspensionView,
)


def _now(now=None):
    return now if now is not None else timezone.now()


def _audit(actor, action, target, detail=None):
    record_audit(None, action, target=target, actor=actor, detail=detail)


def _problem(pointer, message):
    return errors.InvalidRequest(errors=[{"pointer": pointer, "message": message}])


def _amount(value, pointer="/amount"):
    if not is_int(value) or not (0 < value <= MAX_AMOUNT):
        raise _problem(pointer, f"1 이상 {MAX_AMOUNT} 이하의 정수여야 합니다.")
    return value


def _check_ends_at(ends_at, starts_at, now):
    if not (ends_at > starts_at and ends_at > now):
        raise _problem("/ends_at", "종료 시각은 시작보다 뒤이고 지금보다 뒤여야 합니다.")


def _utc_time(value, pointer):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _problem(pointer, "시각은 시간대가 있는 값이어야 합니다.")
    try:
        return value.astimezone(dt_timezone.utc)
    except (OverflowError, ValueError):  # 표현 범위 밖(예: datetime.min 에 +09:00)
        raise _problem(pointer, "표현할 수 없는 시각입니다.")


def _flag(value):
    if not isinstance(value, bool):
        raise _problem("/enabled", "true 또는 false 여야 합니다.")
    return value


def _assert_seen(expected_updated_at, current, again="수정하세요"):
    """화면이 본 마지막 변경 시각을 잠금 안에서 지금과 대조한다(`None` 이면 대조하지 않음). 다르면 409."""
    if expected_updated_at is not None and expected_updated_at != current:
        raise errors.StaleVersion(f"다른 곳에서 먼저 바뀌었습니다. 새로 불러와 다시 {again}.")


# ---------------------------------------------------------------- 조회 도우미

def _campaign(user, campaign_id, lock=False):
    """`lock=True` 는 행 잠금(`FOR UPDATE`)으로 읽는다 — **캠페인 행을 쓰는 동작**(수정·종료·중단·해제·재검토 요청)과 기간 종료(`transitions.expire_due`)가
    같은 잠금으로 순서를 정해, 읽은 값이 저장할 때까지 유효하다(안 그러면 이미 끝난 캠페인을 전체 행 저장이 되살린다). 트랜잭션 안에서만 쓴다."""
    queryset = Campaign.objects.select_for_update() if lock else Campaign.objects.all()
    return owned_or_404(queryset, user, campaign_id=campaign_id)


def _admin_campaign(campaign_id):
    """관리자 동작(중단·해제)용: 누구의 캠페인이든 행 잠금으로 읽는다. 없으면 404. 트랜잭션 안에서만."""
    c = Campaign.objects.select_for_update().filter(pk=parse_uuid(campaign_id, "캠페인")).first()
    if c is None:
        raise errors.NotFound("캠페인을 찾을 수 없습니다.")
    return c


def _ad_group(user, ad_group_id):
    return owned_or_404(AdGroup.objects.select_related("campaign"), user, owner_field="campaign__owner", ad_group_id=ad_group_id)


def _creative(user, creative_id, archived=False):
    """광고주 자신의 소재(남의 것·없는 것은 404). 보관한 소재는 `archived=True`(읽기)일 때만 — 끝난 캠페인의 광고그룹 화면이 그 이미지를 보인다."""
    queryset = Creative.objects.all() if archived else Creative.objects.filter(archived_at__isnull=True)
    return owned_or_404(queryset, user, creative_id=creative_id)


def _locked_group(user, ad_group_id):
    """광고그룹을 바꾸는 동작용: 소유를 확인한 뒤 **캠페인 행을 먼저 잠그고**(캠페인 행 잠금 규약 — 종료·기간 종료·중단과 줄을 선다) 광고그룹 행을
    잠가 다시 읽는다. 잠그지 않고 읽은 객체를 통째로 저장하면 그 사이의 다른 변경을 되돌리고, 끝난 캠페인에도 쓸 수 있었다(Step 3-2d). 트랜잭션 안에서만."""
    found = _ad_group(user, ad_group_id)
    campaign = Campaign.objects.select_for_update().get(pk=found.campaign_id)
    group = AdGroup.objects.select_for_update().get(pk=found.pk)
    group.campaign = campaign
    return group


def _lock_quota(user):
    """광고주 전체 상한(캠페인·광고그룹·소재 수, 이미지 보유량)의 잠금 행. 만들기·이미지 교체가 **가장 먼저** 잡고(그다음 캠페인 → 광고그룹·소재),
    잠금 안에서 상한을 다시 센다 — 서로 다른 캠페인의 동시 쓰기도 줄을 선다(외부 검토 41d2288). 처음 쓸 때 만든다. 트랜잭션 안에서만."""
    AdvertiserQuota.objects.get_or_create(owner_id=user.pk)  # 동시에 처음 만들면 한쪽은 유일 제약에서 기다렸다가 있는 행을 읽는다
    return AdvertiserQuota.objects.select_for_update().get(owner_id=user.pk)


def _locked_creative(user, creative_id):
    """소재를 바꾸거나 연결·선택·보관하는 동작용: 소유를 확인한 뒤 **소재 행**을 잠가 다시 읽는다(보관한 것은 404). 잠금 순서의 마지막이다 —
    광고주 → 캠페인 → 광고그룹 → 소재(설계 §10 "캠페인 행 잠금 규약"). 소재는 캠페인 밖에 있으므로 캠페인을 잠그지 않는다. 트랜잭션 안에서만."""
    found = _creative(user, creative_id)
    creative = Creative.objects.select_for_update().get(pk=found.pk)
    if creative.archived_at is not None:  # 확인과 잠금 사이에 보관됐다
        raise errors.NotFound("소재를 찾을 수 없습니다.")
    return creative


def _campaign_view(c, now, open_review_id=None):
    expired = is_expired(c.ends_at, now)
    ended = c.status == CampaignStatus.ENDED or expired
    status = CampaignStatus.ENDED if ended else c.status
    ended_from = (c.ended_from if c.status == CampaignStatus.ENDED else c.status) if ended else None
    suspension = None
    if status == CampaignStatus.SUSPENDED:
        suspension = SuspensionView(c.suspended_reason, c.suspended_at, open_review_id)
    return CampaignView(
        campaign_id=c.campaign_id, owner_id=c.owner_id, name=c.name, starts_at=c.starts_at, ends_at=c.ends_at,
        daily_budget=c.daily_budget, status=status, ended_from=ended_from, suspension=suspension,
        created_at=c.created_at, updated_at=c.updated_at,
    )


def _open_review_id(campaign):
    return ReviewRequest.objects.filter(campaign=campaign, status=ReviewStatus.OPEN).values_list("review_request_id", flat=True).first()


def _bid_view(b):
    return BidView(bid_id=b.bid_id, ad_group_id=b.ad_group_id, bid_version=b.bid_version, amount=b.amount, created_at=b.created_at)


def _current_bid(ad_group):
    return Bid.objects.filter(ad_group=ad_group).order_by("-bid_version").first()


def _ad_group_view(g, bid=None, slot_ids=None):
    """`slot_ids`: 이미 읽은 게재 위치(목록이 한 번에 읽는다). 없으면 그 그룹의 것을 읽는다."""
    slot_ids = tuple(sorted(g.slot_links.values_list("slot_id", flat=True) if slot_ids is None else slot_ids, key=str))
    return AdGroupView(
        ad_group_id=g.ad_group_id, campaign_id=g.campaign_id, name=g.name, pricing_unit=g.pricing_unit, enabled=g.enabled, creative_id=g.creative_id,
        slot_ids=slot_ids, current_bid=_bid_view(bid) if bid else None, created_at=g.created_at, updated_at=g.updated_at,
    )


def _creative_view(c):
    return CreativeView(
        creative_id=c.creative_id, title=c.title, redirect_url=c.redirect_url, image_name=c.image_name, image_bytes=c.image_bytes,
        archived=c.archived_at is not None, created_at=c.created_at, updated_at=c.updated_at,
    )


def _review_view(r):
    return ReviewRequestView(
        review_request_id=r.review_request_id, campaign_id=r.campaign_id, message=r.message, status=r.status,
        response_note=r.response_note, created_at=r.created_at, closed_at=r.closed_at,
    )


# ---------------------------------------------------------------- 캠페인

def create_campaign(user, name, starts_at, ends_at, daily_budget, now=None, request_key=None):
    """캠페인만 만든다(6-9d — 광고는 `create_ad` 로 따로). `request_key`(화면 폼 하나마다 새 값)를 주면 **같은 키로는 한 번만** 만든다:
    두 번 누름·동시 제출·응답 실패 뒤 재시도는 처음 만든 캠페인을 돌려준다(키는 캠페인 행에 같은 트랜잭션으로 저장, 유일 제약)."""
    require_advertiser(user)
    now = _now(now)
    request_key = clean_request_key(request_key)
    done = _campaign_by_key(user, request_key, now)
    if done is not None:
        return done
    name = clean_text(name, "캠페인 이름", "/name")
    starts_at = _utc_time(starts_at, "/starts_at")
    ends_at = None if ends_at is None else _utc_time(ends_at, "/ends_at")
    daily_budget = _amount(daily_budget, "/daily_budget")
    if ends_at is not None:
        _check_ends_at(ends_at, starts_at, now)
    try:
        with transaction.atomic():
            _lock_quota(user)  # 같은 광고주의 만들기는 여기서 줄을 선다 — 같은 키의 겹친 재전송도
            done = _campaign_by_key(user, request_key, now)  # 첫 조회와 앞선 요청의 커밋 사이의 틈
            if done is not None:
                return done
            if Campaign.objects.filter(owner=user).count() >= settings.MAX_CAMPAIGNS_PER_ADVERTISER:
                raise LimitExceeded("캠페인 개수 상한에 도달했습니다.")
            c = Campaign.objects.create(owner=user, name=name, starts_at=starts_at, ends_at=ends_at, daily_budget=daily_budget, created_at=now, updated_at=now,
                                        request_key=request_key)
            _audit(user, "campaign.created", ("campaigns.campaign", c.campaign_id), {"name": name, "daily_budget": daily_budget})
    except IntegrityError:
        done = _campaign_by_key(user, request_key, now)
        if done is None:
            raise
        return done
    return _campaign_view(c, now)


def campaign_created_by_key(user, request_key, now=None):
    """이 요청 키로 이미 만든 캠페인, 없거나 키 형식이 틀리면 `None`. 화면이 **폼 검증보다 먼저** 부른다(이미 성공한 제출의 다시 보냄은 처음 결과로). 남의 키면 409."""
    require_advertiser(user)
    return _campaign_by_key(user, request_key, _now(now)) if is_request_key(request_key) else None


def _campaign_by_key(user, request_key, now):
    if request_key is None:
        return None
    c = Campaign.objects.filter(request_key=request_key).first()
    if c is None:
        return None
    if c.owner_id != user.pk:
        raise errors.Conflict("이 캠페인 만들기 폼은 이미 처리됐습니다. 새로 불러와 다시 만드세요.")
    return _campaign_view(c, now)


def get_campaign(user, campaign_id, now=None):
    now = _now(now)
    c = _campaign(user, campaign_id)
    return _campaign_view(c, now, _open_review_id(c))


def list_campaigns(user, now=None):
    now = _now(now)
    return [_campaign_view(c, now) for c in Campaign.objects.filter(owner=user).order_by("-created_at")]


CAMPAIGN_FIELDS = {"name", "ends_at", "daily_budget", "status"}


def update_campaign(user, campaign_id, changes, now=None, expected_updated_at=None):
    """`changes` 는 바꿀 필드만 담는다(name·ends_at·daily_budget·status). status 는 ACTIVE↔PAUSED 만.

    `expected_updated_at`: 화면이 본 캠페인의 마지막 변경 시각. 주면 잠금 안에서 지금과 대조해 다르면 `StaleVersion`(409) — 폼을 연 뒤 다른 탭·기기에서
    바뀐 값을 옛 폼이 덮어쓰지 않게(Step 3-2b). 켜기·끄기처럼 바꿀 값이 분명한 동작은 주지 않는다."""
    require_advertiser(user)
    now = _now(now)
    unknown = set(changes) - CAMPAIGN_FIELDS
    if unknown or not changes:
        raise _problem("/", f"바꿀 수 있는 필드: {sorted(CAMPAIGN_FIELDS)}")
    with transaction.atomic():
        c = _campaign(user, campaign_id, lock=True)
        tr.assert_open(c, now)  # 종료된 캠페인(상태 갱신 전 포함)은 어떤 값도 못 바꾼다
        _assert_seen(expected_updated_at, c.updated_at)
        if "status" in changes:
            target = changes["status"]
            if target not in (CampaignStatus.ACTIVE, CampaignStatus.PAUSED):
                raise _problem("/status", "광고주는 ACTIVE 와 PAUSED 만 고를 수 있습니다.")
        if "name" in changes:
            changes = {**changes, "name": clean_text(changes["name"], "캠페인 이름", "/name")}
        if "daily_budget" in changes:
            _amount(changes["daily_budget"], "/daily_budget")
        if "ends_at" in changes and changes["ends_at"] is not None:
            ends_at = _utc_time(changes["ends_at"], "/ends_at")
            _check_ends_at(ends_at, c.starts_at, now)
            changes = {**changes, "ends_at": ends_at}
        if "status" in changes:
            if c.status == CampaignStatus.SUSPENDED:
                raise CampaignSuspended()
            if changes["status"] != c.status:
                tr.apply(c, "pause" if changes["status"] == CampaignStatus.PAUSED else "resume", tr.ADVERTISER, now)
        for field in ("name", "ends_at", "daily_budget"):
            if field in changes:
                setattr(c, field, changes[field])
        c.updated_at = now
        c.save()
        _audit(user, "campaign.updated", ("campaigns.campaign", c.campaign_id), {"changed": sorted(changes)})
    return _campaign_view(c, now, _open_review_id(c))


def end_campaign(user, campaign_id, now=None):
    """조기 종료. 되돌릴 수 없고 `ends_at` 을 현재로 확정한다."""
    require_advertiser(user)
    now = _now(now)
    with transaction.atomic():
        c = _campaign(user, campaign_id, lock=True)
        previous = tr.apply(c, "end", tr.ADVERTISER, now)
        _audit(user, "campaign.ended_early", ("campaigns.campaign", c.campaign_id), {"from": previous})
    return _campaign_view(c, now)


def campaign_names(campaign_ids):
    """캠페인 이름(**표시용**)을 질의 한 번으로 `{campaign_id: 이름}`. 원장 내역의 과금 줄에 캠페인 이름을 붙일 때 쓴다(광고주·관리자 화면).
    호출한 쪽이 보여도 되는 ID 만 넘긴다(자기 원장에 적힌 캠페인). 없는·형식이 틀린 ID 는 결과에 없다."""
    return dict(Campaign.objects.filter(pk__in=parse_uuids(campaign_ids)).values_list("campaign_id", "name"))


def campaign_ids_of(user):
    """이 광고주의 모든 캠페인 ID(보고서 범위용). 광고주만."""
    require_advertiser(user)
    return list(Campaign.objects.filter(owner=user).values_list("campaign_id", flat=True))


def campaign_end_times(campaign_ids):
    """캠페인 ID들의 종료 시각(`ends_at`, 미포함 경계) 하나의 질의로. 끝이 없으면 값이 `None`, 없는 ID는 결과에 없다. 반응 판정이 쓴다."""
    return dict(Campaign.objects.filter(pk__in=parse_uuids(campaign_ids)).values_list("campaign_id", "ends_at"))


def end_expired_campaigns(now=None):
    """기간이 지난 캠페인을 `ENDED` 로(시스템 작업, 멱등). 바뀐 개수를 돌려준다."""
    now = _now(now)
    with transaction.atomic():
        changed = tr.expire_due(now)
        for campaign_id in changed:  # 변경과 같은 트랜잭션에 기록한다(감사 없는 변경이 없게)
            record_audit(None, "campaign.expired", target=("campaigns.campaign", campaign_id))
    return len(changed)


def suspend_campaign(actor, campaign_id, reason, now=None):
    require_admin(actor)
    now = _now(now)
    reason = clean_text(reason, "중단 사유", "/reason", 500)
    with transaction.atomic():
        c = _admin_campaign(campaign_id)
        previous = tr.apply(c, "suspend", tr.ADMIN, now, reason=reason)
        _audit(actor, "campaign.suspended", ("campaigns.campaign", c.campaign_id), {"from": previous, "reason": reason})
    return _campaign_view(c, now, _open_review_id(c))


def release_campaign(actor, campaign_id, now=None, expected_suspended_at=None, review_request_id=None):
    """중단 해제. 열린 재검토 요청은 해제로 닫힌다(transitions).

    화면에서 누르는 해제는 **화면이 본 중단 회차**(`expected_suspended_at` = 그 중단 시각)와, 대기열에서는 그 재검토 요청(`review_request_id`)을 싣는다.
    캠페인 행을 잠근 뒤 대조해 다르면 `StaleVersion` — 화면을 연 뒤 다른 관리자가 해제하고 다시 중단했거나 새 요청이 왔는데, 오래된 버튼이 새 중단까지 풀지 않게 한다(외부 검토 3-1c P2).
    """
    require_admin(actor)
    now = _now(now)
    with transaction.atomic():
        c = _admin_campaign(campaign_id)
        tr.assert_open(c, now)
        if c.status != CampaignStatus.SUSPENDED:
            raise NotSuspended("중단된 캠페인이 아닙니다.")
        if expected_suspended_at is not None and c.suspended_at != expected_suspended_at:
            raise errors.StaleVersion("다른 곳에서 먼저 바뀌었습니다: 화면을 연 뒤 이 캠페인이 다시 중단됐습니다. 새로 불러와 지금의 사유를 확인하세요.")
        if review_request_id is not None and _open_review_id(c) != parse_uuid(review_request_id, "재검토 요청"):
            raise errors.StaleVersion("다른 곳에서 먼저 바뀌었습니다: 화면을 연 뒤 재검토 요청이 처리되거나 새로 들어왔습니다. 새로 불러와 확인하세요.")
        tr.apply(c, "release", tr.ADMIN, now)
        _audit(actor, "campaign.released", ("campaigns.campaign", c.campaign_id))
    return _campaign_view(c, now)


# ---------------------------------------------------------------- 재검토 요청

def create_review_request(user, campaign_id, message="", now=None):
    require_advertiser(user)
    now = _now(now)
    message = clean_text(message, "메모", "/message", 500) if message else ""
    try:
        with transaction.atomic():
            c = _campaign(user, campaign_id, lock=True)
            tr.assert_open(c, now)
            if c.status != CampaignStatus.SUSPENDED:
                raise NotSuspended()
            if ReviewRequest.objects.filter(campaign=c, status=ReviewStatus.OPEN).exists():
                raise ReviewPending()
            review = ReviewRequest.objects.create(campaign=c, message=message, created_at=now)
            _audit(user, "campaign.review_requested", ("campaigns.campaign", c.campaign_id), {"review_request_id": str(review.review_request_id)})
    except IntegrityError:  # 동시에 두 요청이 들어온 경우의 안전망(열린 요청의 유일 제약)
        raise ReviewPending()
    return _review_view(review)


def list_review_requests(user, campaign_id):
    c = _campaign(user, campaign_id)
    return [_review_view(r) for r in ReviewRequest.objects.filter(campaign=c).order_by("-created_at")]


def latest_review_requests(user):
    """캠페인마다 가장 최근의 재검토 요청 `{campaign_id: ReviewRequestView}`(알림용 — 반려 답변을 보인다). 질의 한 번."""
    require_advertiser(user)
    latest = {}
    for r in ReviewRequest.objects.filter(campaign__owner=user).order_by("created_at"):
        latest[r.campaign_id] = _review_view(r)
    return latest


def reject_review_request(actor, review_request_id, note, now=None):
    """반려: 정지는 유지하고 요청만 닫는다. 사유는 필수."""
    require_admin(actor)
    now = _now(now)
    note = clean_text(note, "반려 사유", "/note", 500)
    review_id = parse_uuid(review_request_id, "재검토 요청")
    campaign_id = ReviewRequest.objects.filter(pk=review_id).values_list("campaign_id", flat=True).first()
    if campaign_id is None:
        raise errors.NotFound("재검토 요청을 찾을 수 없습니다.")
    with transaction.atomic():
        # 해제·기간 종료·재검토 접수와 같은 순서: **캠페인 행을 먼저 잠그고** 요청은 그 뒤에 다시 읽는다. 요청 상태를 바꾸는 쪽은 모두 이 잠금을 쥐므로
        # 읽은 OPEN 이 저장할 때까지 유효하다(외부 검토 3-1c P2: 잠금 없이 읽으면 먼저 닫힌 요청을 늦은 반려가 덮었다).
        campaign = Campaign.objects.select_for_update().get(pk=campaign_id)
        review = ReviewRequest.objects.get(pk=review_id)
        tr.assert_open(campaign, now)
        if review.status != ReviewStatus.OPEN:
            raise errors.Conflict("이미 처리된 요청입니다.")
        tr.close_review_request(review, ReviewStatus.REJECTED, now, note)
        _audit(actor, "campaign.review_rejected", ("campaigns.campaign", review.campaign_id), {"review_request_id": str(review.review_request_id), "note": note})
    return _review_view(review)


# ---------------------------------------------------------------- 관리자 모니터링 (Step 3-1c, S5)

def monitoring_list(actor, now=None):
    """모든 광고주의 캠페인과 소재. **마지막 변경**(캠페인·소재 중 늦은 쪽)이 최근인 순 — 소재의 이동 주소만 바꿔도 위로 올라온다(피싱 주소 바꿔치기를 놓치지 않게).
    중단·종료 캠페인도 포함한다. 정렬·쪽 나누기는 DB 에서 하고(P3-4 2단계, 외부 검토 00d3067) 돌려준 줄 묶음을 `Paginator` 에 넘기면 그 쪽만 읽는다."""
    require_admin(actor)
    return _MonitoringRows(_now(now))


class _MonitoringRows:
    """`Paginator` 가 쓰는 두 가지만 있다: 개수(`count()`)와 구간(`[a:b]`). 구간 하나는 질의 세 번(그 쪽 캠페인·그 소재·그 열린 재검토 요청).
    마지막 변경이 같으면 캠페인 ID 역순(uuid7 — 나중에 만든 것 먼저)으로 끊는다 — 쪽마다 따로 읽어도 겹치거나 빠지는 줄이 없다."""

    # ponytail: 정렬 키가 계산 값이라 색인을 못 쓴다 — 쪽마다 모든 캠페인을 훑어 정렬한다(광고주 150명 × 캠페인 상한 20 = 3,000행). 더 커지면 마지막 변경 시각을 캠페인 열로 두고(소재 변경 때 함께 갱신) 색인
    def __init__(self, now):
        self.now = now
        # 연결된 소재의 마지막 수정이나 연결 시각 — 이미 있던 소재를 새로 연결해도 위로 올라온다(6-9c)
        last_creative = (AdGroupCreative.objects.filter(ad_group__campaign=OuterRef("pk")).annotate(at=Greatest("creative__updated_at", "linked_at"))
                         .order_by("-at").values("at")[:1])
        self.campaigns = Campaign.objects.annotate(
            last_changed_at=Greatest("updated_at", Coalesce(Subquery(last_creative), "updated_at")),  # 소재가 없으면 캠페인의 시각(GREATEST 는 NULL 이 섞이면 NULL)
        ).order_by("-last_changed_at", "-campaign_id")

    def count(self):
        return Campaign.objects.count()

    def __getitem__(self, window):
        rows = list(self.campaigns[window])
        ids = [c.campaign_id for c in rows]
        open_reviews = dict(ReviewRequest.objects.filter(status=ReviewStatus.OPEN, campaign_id__in=ids).values_list("campaign_id", "review_request_id"))
        creatives, selected = _creatives_by_campaign(ids)
        return [MonitoredCampaign(_campaign_view(c, self.now, open_reviews.get(c.campaign_id)), tuple(creatives.get(c.campaign_id, ())), c.last_changed_at,
                                  frozenset(selected.get(c.campaign_id, ()))) for c in rows]


def _creatives_by_campaign(campaign_ids):
    """캠페인별로 그 광고그룹들에 **연결된** 소재 `{campaign_id: [CreativeView]}`(만든 순서, 같은 소재는 한 번)와 그중 광고그룹이 **선택한** 소재 ID
    `{campaign_id: {creative_id}}`. 선택하지 않은 연결도 보인다 — 언제든 선택될 수 있어 운영자가 이동 주소를 확인해야 한다. 질의 한 번."""
    found, seen, selected = {}, set(), {}
    links = AdGroupCreative.objects.select_related("creative", "ad_group").filter(ad_group__campaign_id__in=campaign_ids).order_by("creative__created_at", "creative_id")
    for link in links:
        key = (link.ad_group.campaign_id, link.creative_id)
        if link.ad_group.creative_id == link.creative_id:
            selected.setdefault(link.ad_group.campaign_id, set()).add(link.creative_id)
        if key not in seen:
            seen.add(key)
            found.setdefault(link.ad_group.campaign_id, []).append(_creative_view(link.creative))
    return found, selected


def advertiser_usage(actor, owner_ids):
    """광고주마다 캠페인·소재 수와 보유 이미지 총량, 그리고 상한 {owner_id: AdvertiserUsage}(관리자 광고주 목록, Step 3-1d).
    상한 검사와 같은 기준으로 센다(소재는 보관하지 않은 것, 이미지는 교체한 과거 파일·보관한 소재 포함, 같은 파일은 한 번). 없는 광고주도 0 으로 채운다. 질의 세 번."""
    require_admin(actor)
    ids = parse_uuids(owner_ids)
    campaigns = dict(Campaign.objects.filter(owner_id__in=ids).values("owner_id").annotate(n=Count("pk")).values_list("owner_id", "n"))
    creatives = dict(Creative.objects.filter(owner_id__in=ids, archived_at__isnull=True).values("owner_id").annotate(n=Count("pk")).values_list("owner_id", "n"))
    held = {}
    for owner_id, _name, size in CreativeImage.objects.filter(creative__owner_id__in=ids).values_list("creative__owner_id", "image_name", "image_bytes").distinct():
        held[owner_id] = held.get(owner_id, 0) + size
    return {
        i: AdvertiserUsage(campaigns.get(i, 0), settings.MAX_CAMPAIGNS_PER_ADVERTISER, creatives.get(i, 0), settings.MAX_CREATIVES_PER_ADVERTISER,
                           held.get(i, 0), settings.MAX_UPLOAD_BYTES_PER_ADVERTISER)
        for i in ids
    }


def open_review_queue(actor, now=None):
    """열린 재검토 요청(오래된 것부터)과 그 캠페인·소재. 관리자가 해제(`release_campaign`)하거나 반려(`reject_review_request`)한다.
    소재는 **대기 중인 캠페인의 것만** 읽는다(질의 두 번 — 전체 모니터링 목록을 만들지 않는다, 외부 검토 00d3067)."""
    require_admin(actor)
    now = _now(now)
    rows = list(ReviewRequest.objects.select_related("campaign").filter(status=ReviewStatus.OPEN).order_by("created_at"))
    creatives, selected = _creatives_by_campaign([r.campaign_id for r in rows])
    return [ReviewQueueItem(_review_view(r), _campaign_view(r.campaign, now, r.review_request_id), tuple(creatives.get(r.campaign_id, ())),
                            frozenset(selected.get(r.campaign_id, ()))) for r in rows]


# ---------------------------------------------------------------- 광고그룹·입찰

def _validated_slots(slot_ids, pricing_unit):
    if not isinstance(slot_ids, (list, tuple)) or not slot_ids:
        raise _problem("/slot_ids", "게재 위치를 하나 이상 고르세요.")
    try:
        ids = [parse_uuid(s, "게재 위치") for s in slot_ids]
    except errors.NotFound:
        raise _problem("/slot_ids", "게재 위치 ID 형식이 올바르지 않습니다.")
    if len(set(ids)) != len(ids):
        raise _problem("/slot_ids", "같은 게재 위치를 두 번 고를 수 없습니다.")
    views = masters.get_slots_with_policy(ids)
    for slot_id in ids:
        slot = views.get(slot_id)
        if slot is None or not slot.is_active or not slot.media_is_active:
            raise _problem("/slot_ids", "없거나 쓸 수 없는 게재 위치가 있습니다.")
        if slot.pricing_unit != pricing_unit:
            raise UnitMismatch(errors=[{"pointer": "/slot_ids", "message": f"{slot.name}: 과금 단위가 {pricing_unit} 이(가) 아닙니다."}])
    return ids


def create_ad_group(user, campaign_id, name, pricing_unit, slot_ids, bid_amount=None, now=None):
    require_advertiser(user)
    now = _now(now)
    name = clean_text(name, "광고그룹 이름", "/name")
    if pricing_unit not in masters.PricingUnit.values:
        raise _problem("/pricing_unit", f"{', '.join(masters.PricingUnit.values)} 중 하나여야 합니다.")
    ids = _validated_slots(slot_ids, pricing_unit)
    if bid_amount is not None:
        _amount(bid_amount, "/bid_amount")
    with transaction.atomic():
        _lock_quota(user)
        c = _campaign(user, campaign_id, lock=True)
        tr.assert_open(c, now)
        if AdGroup.objects.filter(campaign__owner=user).count() >= settings.MAX_AD_GROUPS_PER_ADVERTISER:
            raise LimitExceeded("광고그룹 개수 상한에 도달했습니다.")
        group = AdGroup.objects.create(campaign=c, name=name, pricing_unit=pricing_unit, created_at=now, updated_at=now)
        AdGroupSlot.objects.bulk_create([AdGroupSlot(ad_group=group, slot_id=s) for s in ids])
        bid = Bid.objects.create(ad_group=group, bid_version=1, amount=bid_amount, created_by=user.pk, created_at=now) if bid_amount is not None else None
        _audit(user, "ad_group.created", ("campaigns.ad_group", group.ad_group_id), {"name": name, "pricing_unit": pricing_unit, "slots": len(ids)})
    return _ad_group_view(group, bid, ids)  # 방금 넣은 게재 위치(검증한 ID, 중복 없음)를 다시 읽지 않는다


def get_ad_group(user, ad_group_id):
    g = _ad_group(user, ad_group_id)
    return _ad_group_view(g, _current_bid(g))


def list_ad_groups(user, campaign_id):
    """캠페인의 광고그룹(만든 순서)과 현재 입찰. 질의 수는 광고그룹 수와 무관하다(캠페인·그룹·게재 위치·입찰 한 번씩)."""
    c = _campaign(user, campaign_id)
    latest = Bid.objects.filter(ad_group=OuterRef("pk")).order_by("-bid_version").values("bid_id")[:1]
    groups = list(AdGroup.objects.filter(campaign=c).annotate(current_bid_id=Subquery(latest)).order_by("created_at"))
    slots = {}
    for group_id, slot_id in AdGroupSlot.objects.filter(ad_group__in=groups).values_list("ad_group_id", "slot_id"):
        slots.setdefault(group_id, []).append(slot_id)
    bids = Bid.objects.in_bulk([g.current_bid_id for g in groups if g.current_bid_id is not None])
    return [_ad_group_view(g, bids.get(g.current_bid_id), slots.get(g.pk, ())) for g in groups]


AD_GROUP_FIELDS = {"name", "enabled", "slot_ids", "pricing_unit", "creative_id"}


def update_ad_group(user, ad_group_id, changes, now=None, expected_updated_at=None):
    """이름·켜기/끄기·게재 위치·선택한 소재(`creative_id` — 이 광고그룹에 연결된 소재만, 6-9c). `expected_updated_at`(화면이 본 마지막 변경 시각)을 주면
    잠금 안에서 대조해 다르면 409 — 옛 폼이 같은 칸의 최신 변경을 덮지 않게(외부 검토 41d2288 P3). 켜기/끄기처럼 바꿀 값이 분명한 동작은 주지 않는다."""
    require_advertiser(user)
    now = _now(now)
    unknown = set(changes) - AD_GROUP_FIELDS
    if unknown or not changes:
        raise _problem("/", f"바꿀 수 있는 필드: {sorted(AD_GROUP_FIELDS - {'pricing_unit'})}")
    if "pricing_unit" in changes:
        raise UnitImmutable()  # 보내면 항상 거절한다(같은 값이어도)
    with transaction.atomic():
        g = _locked_group(user, ad_group_id)
        tr.assert_open(g.campaign, now)
        _assert_seen(expected_updated_at, g.updated_at)
        if "name" in changes:
            g.name = clean_text(changes["name"], "광고그룹 이름", "/name")
        if "enabled" in changes:
            g.enabled = _flag(changes["enabled"])
        if "slot_ids" in changes:
            ids = _validated_slots(changes["slot_ids"], g.pricing_unit)
            g.slot_links.exclude(slot_id__in=ids).delete()
            have = set(g.slot_links.values_list("slot_id", flat=True))
            AdGroupSlot.objects.bulk_create([AdGroupSlot(ad_group=g, slot_id=s) for s in ids if s not in have])
        if "creative_id" in changes:
            c = _locked_creative(user, changes["creative_id"])  # 남의 것·보관한 것은 404. 잠금 순서: 캠페인 → 광고그룹 → 소재
            if not AdGroupCreative.objects.filter(ad_group=g, creative=c).exists():
                raise _problem("/creative_id", "이 광고그룹에 연결된 소재가 아닙니다.")
            g.creative = c
        g.updated_at = now
        g.save()
        _audit(user, "ad_group.updated", ("campaigns.ad_group", g.ad_group_id), {"changed": sorted(changes)})
    return _ad_group_view(g, _current_bid(g))


def add_bid(user, ad_group_id, amount, expected_version, now=None):
    """새 입찰 버전. 하한 미만·상한 초과도 저장한다. `expected_version`(첫 입찰이면 None)이 현재와 다르면 StaleVersion."""
    require_advertiser(user)
    now = _now(now)
    _amount(amount)
    with transaction.atomic():
        g = _locked_group(user, ad_group_id)
        tr.assert_open(g.campaign, now)
        current = _current_bid(g)
        current_version = current.bid_version if current else None
        if expected_version != current_version:
            raise errors.StaleVersion(f"다른 곳에서 먼저 바뀌었습니다(현재 버전 {current_version}). 새로 불러와 다시 넣으세요.")
        try:
            with transaction.atomic():
                bid = Bid.objects.create(ad_group=g, bid_version=(current_version or 0) + 1, amount=amount, created_by=user.pk, created_at=now)
        except IntegrityError:  # 다른 DB 로 옮겼을 때의 안전망
            raise errors.StaleVersion()
        _audit(user, "bid.added", ("campaigns.ad_group", g.ad_group_id), {"version": bid.bid_version, "amount": amount})
    return _bid_view(bid)


def ad_group_effects(user):
    """광고주의 모든 광고그룹과 현재 입찰의 게재 위치별 결과 `[AdGroupEffects]`(알림 조립용). 질의 수는 그룹 수와 무관(그룹 1 + 위치 1 + 정책 1)."""
    require_advertiser(user)
    latest = Bid.objects.filter(ad_group=OuterRef("pk")).order_by("-bid_version")
    groups = list(
        AdGroup.objects.filter(campaign__owner=user)
        .annotate(bid_amount=Subquery(latest.values("amount")[:1]), bid_created_at=Subquery(latest.values("created_at")[:1]))
        .order_by("created_at")
    )
    links = {}
    for group_id, slot_id in AdGroupSlot.objects.filter(ad_group__in=groups).order_by("slot_id").values_list("ad_group_id", "slot_id"):
        links.setdefault(group_id, []).append(slot_id)
    every_slot = {slot_id for ids in links.values() for slot_id in ids}
    policies = masters.get_slots_with_policy(every_slot) if every_slot else {}

    def effects(g):
        if g.bid_amount is None:
            return ()
        return tuple(_effect(g.bid_amount, slot_id, policies.get(slot_id)) for slot_id in links.get(g.pk, []))
    return [AdGroupEffects(g.ad_group_id, g.campaign_id, g.name, g.pricing_unit, g.enabled, g.bid_amount, g.bid_created_at, effects(g)) for g in groups]


def _effect(amount, slot_id, slot):
    """입찰 금액 하나가 게재 위치 하나에서 어떻게 취급되는지(C6 `SlotEffect`). 적용 금액은 engine 의 `effect_of` 한 곳이 정한다.
    꺼진 위치(슬롯·매체 비활성)는 `slot_inactive`, 없는 위치는 `no_policy`. 3-2c·3-2d 의 입찰 안내도 이것을 쓴다."""
    if slot is None:
        return SlotEffect(slot_id, False, None, "no_policy", None)
    if not (slot.is_active and slot.media_is_active):
        return SlotEffect(slot_id, False, None, "slot_inactive", slot.policy.policy_version)
    e = effect_of(amount, slot.policy.floor, slot.policy.cap)
    return SlotEffect(slot_id, e.eligible, e.applied_amount, e.reason, slot.policy.policy_version)


def list_bids(user, ad_group_id):
    g = _ad_group(user, ad_group_id)
    return [_bid_view(b) for b in Bid.objects.filter(ad_group=g).order_by("-bid_version")]


# ---------------------------------------------------------------- 소재

def _redirect_url(value):
    if not isinstance(value, str):
        raise _problem("/redirect_url", "https 주소여야 합니다.")
    value = value.strip()
    parts = host = port = None
    if len(value) <= 2048 and value.isprintable() and " " not in value:
        try:  # urlsplit 은 유효성 검사가 아니다: 잘못된 대괄호·포트는 ValueError 로 드러난다(`hostname`·`port` 접근 시점에)
            parts = urlsplit(value)
            host, port = parts.hostname, parts.port
        except ValueError:
            parts = None
    if parts is None or parts.scheme != "https" or not host or parts.username or parts.password or port == 0:
        raise _problem("/redirect_url", "사용자 정보가 없는 https 주소(올바른 포트, 2048자 이하)여야 합니다.")
    return value


def _check_creative_count(user):
    """보관하지 않은 소재만 센다(6-9c). 보관한 소재의 이미지는 `_check_image_quota` 가 계속 센다 — 저장 공간은 보유량 상한에서 멈춘다."""
    if Creative.objects.filter(owner=user, archived_at__isnull=True).count() >= settings.MAX_CREATIVES_PER_ADVERTISER:
        raise LimitExceeded("소재 개수 상한에 도달했습니다.")


def _check_image_quota(user, image):
    """광고주가 **보유한 이미지 파일 총량**(현재 + 과거 교체분, 보관한 소재 포함)이 상한을 넘지 않는지. 이미 보유한 같은 파일은 더하지 않는다."""
    held = dict(CreativeImage.objects.filter(creative__owner=user).values_list("image_name", "image_bytes"))
    added = 0 if image.name in held else len(image.data)
    if sum(held.values()) + added > settings.MAX_UPLOAD_BYTES_PER_ADVERTISER:
        raise LimitExceeded("업로드 총량 상한을 넘습니다.")


def create_creative(user, ad_group_id, title, redirect_url, image_file, now=None):
    """소재를 광고주의 목록에 올린다(6-9c). `ad_group_id` 를 주면 그 광고그룹에 연결하고, 선택된 소재가 없으면 이것을 선택한다(광고그룹 화면의
    "올려서 연결"). `None` 이면 목록에만 올린다. 이미지는 검증·재인코딩해 저장한다(`ImageRejected` 는 그대로 전달)."""
    require_advertiser(user)
    now = _now(now)
    title = clean_text(title, "제목", "/title", 200)
    redirect_url = _redirect_url(redirect_url)
    image = validate_image(image_file)
    with transaction.atomic():
        _lock_quota(user)
        group = None
        if ad_group_id is not None:
            group = _locked_group(user, ad_group_id)
            tr.assert_open(group.campaign, now)
        _check_creative_count(user)
        _check_image_quota(user, image)  # 저장(파일 쓰기) 전에 확인한다: 거절된 업로드는 파일을 남기지 않는다
        name = store(image)
        c = Creative.objects.create(owner=user, title=title, redirect_url=redirect_url, image_name=name, image_bytes=len(image.data), created_at=now, updated_at=now)
        CreativeImage.objects.create(creative=c, image_name=name, image_bytes=len(image.data), created_at=now)
        detail = {"image": name}
        if group is not None:
            _link(group, c, now)
            detail["ad_group_id"] = str(group.ad_group_id)
        _audit(user, "creative.created", ("campaigns.creative", c.creative_id), detail)
    return _creative_view(c)


def _link(group, creative, now):
    """연결하고(이미 있으면 그대로), 광고그룹에 선택된 소재가 없으면 이것을 선택한다. 광고그룹·소재 행을 잠근 트랜잭션 안에서만."""
    if not AdGroupCreative.objects.filter(ad_group=group, creative=creative).exists():
        AdGroupCreative.objects.create(ad_group=group, creative=creative, linked_at=now)
    if group.creative_id is None:
        AdGroup.objects.filter(pk=group.pk).update(creative=creative)
        group.creative = creative


def link_creative(user, ad_group_id, creative_id, now=None):
    """등록된 소재를 광고그룹에 연결한다(재사용, 6-9c). 선택된 소재가 없으면 이것을 선택한다. 남의 소재·보관한 소재는 404, 끝난 캠페인은 409.
    잠금 순서: 캠페인 → 광고그룹 → 소재 — 같은 소재의 보관과 소재 행에서 줄을 선다(보관된 소재는 연결되지 않고, 연결된 소재는 보관되지 않는다)."""
    require_advertiser(user)
    now = _now(now)
    with transaction.atomic():
        g = _locked_group(user, ad_group_id)
        tr.assert_open(g.campaign, now)
        c = _locked_creative(user, creative_id)
        _link(g, c, now)
        _audit(user, "creative.linked", ("campaigns.creative", c.creative_id), {"ad_group_id": str(g.ad_group_id)})
    return _ad_group_view(g, _current_bid(g))


def archive_creative(user, creative_id, now=None):
    """소재 보관 — 화면의 "삭제"(6-9c, 설계 §10 "소재 목록"). 끝나지 않은 캠페인(일시 중지·중단 포함)의 광고그룹에 **연결된** 소재는 409다 —
    선택하지 않은 연결도 막는다(그 광고그룹으로 이미 나간 결정이 화면에 남아 있을 수 있다). 소재 행만 잠그고 캠페인 상태는 잠그지 않고 읽는다:
    끝난 캠페인은 되돌릴 수 없어 늦게 읽어도 "끝나지 않음"을 끝났다고 잘못 볼 수 없다. 보관한 소재는 개수 상한에서 빠지고 이미지 보유량에는 남는다."""
    require_advertiser(user)
    now = _now(now)
    with transaction.atomic():
        c = _locked_creative(user, creative_id)
        in_use = (AdGroupCreative.objects.filter(creative=c).exclude(ad_group__campaign__status=CampaignStatus.ENDED)
                  .filter(Q(ad_group__campaign__ends_at__isnull=True) | Q(ad_group__campaign__ends_at__gt=now)).exists())
        if in_use:
            raise errors.Conflict("끝나지 않은 캠페인의 광고그룹에 연결된 소재는 삭제할 수 없습니다.")
        c.archived_at = now
        c.save(update_fields=["archived_at"])
        _audit(user, "creative.archived", ("campaigns.creative", c.creative_id))
    return _creative_view(c)


def list_owned_creatives(user, now=None):
    """광고주의 소재 목록(보관하지 않은 것, 만든 순서)과 소재마다 연결된 광고그룹(`CreativeUse`). 질의 두 번."""
    require_advertiser(user)
    now = _now(now)
    creatives = list(Creative.objects.filter(owner=user, archived_at__isnull=True).order_by("created_at", "creative_id"))
    uses = {}
    links = AdGroupCreative.objects.select_related("ad_group", "ad_group__campaign").filter(creative__in=creatives).order_by("linked_at", "link_id")
    for link in links:
        g, c = link.ad_group, link.ad_group.campaign
        ended = c.status == CampaignStatus.ENDED or is_expired(c.ends_at, now)
        uses.setdefault(link.creative_id, []).append(CreativeUse(g.ad_group_id, g.name, c.campaign_id, c.name, not ended, g.creative_id == link.creative_id))
    return [OwnedCreative(_creative_view(c), tuple(uses.get(c.creative_id, ()))) for c in creatives]


# ---------------------------------------------------------------- 광고 만들기 (6-9d, 설계 §10 "광고 만들기 흐름" — D3-3 대체)

def _part(prefix, create, *args, **kwargs):
    """한 부분을 만든다. 입력 오류의 위치(`pointer`)에 부분 이름을 붙인다 — 두 부분 모두 `/title` 같은 칸이 있을 수 있어 어느 쪽인지 알려야 한다."""
    try:
        return create(*args, **kwargs)
    except errors.ApiError as e:
        if e.errors:
            e.errors = [{**item, "pointer": prefix + item["pointer"]} for item in e.errors]
        raise


def create_ad(user, campaign_id, ad_group, creative=None, creative_id=None, now=None, request_key=None):
    """**이미 있는** 캠페인에 광고(광고그룹 + 입찰)와 소재를 한 트랜잭션으로 만든다(6-9c·6-9d, 설계 §10 "광고 만들기 흐름" — 캠페인은 `create_campaign` 으로 따로). 소재는 `creative`(새로 올리기 —
    `create_creative` 의 인자) 또는 `creative_id`(등록된 소재 재사용) 중 하나이고, 광고그룹에 연결·선택된다. 입력 오류의 위치는 `/ad_group/…`·`/creative/…`.
    `request_key` 는 광고그룹 행에 저장한다 — 같은 키로는 한 번만 만든다(두 번 누름·동시 제출·응답 실패 뒤 재시도는 처음 것을 `duplicate=True` 로)."""
    now = _now(now)
    request_key = clean_request_key(request_key)
    if (creative is None) == (creative_id is None):
        raise _problem("/creative", "새 소재를 올리거나 등록된 소재를 하나 고르세요.")
    done = _created_by_key(user, request_key)
    if done is not None:
        return done
    try:
        with transaction.atomic():
            _lock_quota(user)  # 같은 광고주의 만들기는 여기서 줄을 선다 — 같은 키의 겹친 재전송도
            done = _created_by_key(user, request_key)
            if done is not None:
                return done
            g = _part("/ad_group", create_ad_group, user, campaign_id, now=now, **ad_group)
            if creative_id is not None:
                _part("/creative", link_creative, user, g.ad_group_id, creative_id, now=now)
            else:
                _part("/creative", create_creative, user, g.ad_group_id, now=now, **creative)
            if request_key is not None:
                AdGroup.objects.filter(pk=g.ad_group_id).update(request_key=request_key)  # 동시에 같은 키가 오면 여기서 유일 제약이 막는다
    except IntegrityError:
        done = _created_by_key(user, request_key)
        if done is None:
            raise
        return done
    return _created_ad(AdGroup.objects.select_related("campaign", "creative").get(pk=g.ad_group_id), now)


def _created_ad(group, now, duplicate=False):
    return CreatedAd(_campaign_view(group.campaign, now), _ad_group_view(group, _current_bid(group)), _creative_view(group.creative), duplicate=duplicate)


def ad_created_by_key(user, request_key):
    """이 요청 키로 이미 만든 광고(`CreatedAd`, `duplicate=True`), 없거나 키 형식이 틀리면 `None`. 화면이 **폼 검증보다 먼저** 부른다 —
    이미 성공한 제출의 다시 보냄은 그 사이 바뀐 위치 목록·상한과 상관없이 처음 결과로 가야 한다(외부 검토 41d2288). 남의 키면 409."""
    require_advertiser(user)
    if not is_request_key(request_key):
        return None
    return _created_by_key(user, request_key)


def _created_by_key(user, request_key):
    """이 요청 키로 이미 만든 광고(`duplicate=True`), 없으면 `None`. 키는 광고그룹 행에 있다. 남의 것에 붙은 키(위조한 폼)면 409."""
    if request_key is None:
        return None
    g = AdGroup.objects.select_related("campaign", "creative").filter(request_key=request_key).first()
    if g is None:
        return None
    if g.campaign.owner_id != user.pk:
        raise errors.Conflict("이 광고 만들기 폼은 이미 처리됐습니다. 새로 불러와 다시 만드세요.")
    return _created_ad(g, _now(), duplicate=True)


def bid_effects(amount, slot_ids, slots=None):
    """입찰 금액 하나가 고른 게재 위치마다 어떻게 취급되는지(광고 만들기의 '미리보기', C6 `effects`). 적용 금액은 engine 한 곳(`_effect`). 질의 한 번.
    형식이 틀린 위치 ID 는 `no_policy` 로 보인다(입력은 막지 않는다 — 저장은 `create_ad` 가 다시 검증한다).
    `slots`: 호출한 쪽이 이미 읽은 `masters.get_slots_with_policy` 결과 — 주면 다시 읽지 않는다(광고그룹 상세: 위치 정보와 결과가 같은 읽기를 본다)."""
    _amount(amount, "/bid_amount")
    parsed = [(raw, _maybe_uuid(raw)) for raw in slot_ids]
    if slots is None:
        slots = masters.get_slots_with_policy([u for _, u in parsed if u is not None])
    return tuple(_effect(amount, u or raw, slots.get(u)) for raw, u in parsed)


def _maybe_uuid(value):
    ids = parse_uuids([value])
    return ids[0] if ids else None


def get_creative(user, creative_id):
    """보관한 소재도 읽는다(끝난 캠페인의 광고그룹 화면이 그 이미지를 보인다). 바꾸는 동작은 보관한 소재에 404 다."""
    return _creative_view(_creative(user, creative_id, archived=True))


def list_creatives(user, ad_group_id):
    """광고그룹에 연결된 소재(만든 순서, 보관한 것 포함). 선택된 것은 광고그룹의 `creative_id` 다."""
    g = _ad_group(user, ad_group_id)
    return [_creative_view(c) for c in Creative.objects.filter(ad_group_links__ad_group=g).order_by("created_at", "creative_id")]


CREATIVE_FIELDS = {"title", "redirect_url"}


def update_creative(user, creative_id, changes, now=None, expected_updated_at=None):
    """제목·이동 주소. 그 소재를 쓰는 모든 광고그룹에 다음 결정부터 적용된다(과거 결정은 스냅샷, 6-9c — 캠페인 밖의 소재라 캠페인 종료로 막지 않는다).
    `expected_updated_at`(화면이 본 마지막 변경 시각)을 주면 다르면 409 — 옛 폼이 그 사이의 변경(이미지 교체 포함)을 덮지 않게."""
    require_advertiser(user)
    now = _now(now)
    unknown = set(changes) - CREATIVE_FIELDS
    if unknown or not changes:
        raise _problem("/", f"바꿀 수 있는 필드: {sorted(CREATIVE_FIELDS)}")
    with transaction.atomic():
        c = _locked_creative(user, creative_id)
        _assert_seen(expected_updated_at, c.updated_at)
        if "title" in changes:
            c.title = clean_text(changes["title"], "제목", "/title", 200)
        if "redirect_url" in changes:
            c.redirect_url = _redirect_url(changes["redirect_url"])
        c.updated_at = now
        c.save()
        _audit(user, "creative.updated", ("campaigns.creative", c.creative_id), {"changed": sorted(changes)})
    return _creative_view(c)


def replace_creative_image(user, creative_id, image_file, now=None, expected_updated_at=None):
    """이미지 교체. 새 이름으로 바꾸고 이전 파일은 지우지 않는다(과거 결정이 참조할 수 있다). 보유량 상한은 광고주 잠금 안에서 센다.
    `expected_updated_at`(화면이 본 소재의 마지막 변경 시각)을 주면 다르면 409 — 옛 화면의 교체가 그 사이의 교체를 덮지 않게."""
    require_advertiser(user)
    now = _now(now)
    image = validate_image(image_file)
    with transaction.atomic():
        _lock_quota(user)
        c = _locked_creative(user, creative_id)  # 잠금 순서: 광고주 → 소재
        _assert_seen(expected_updated_at, c.updated_at, again="바꾸세요")
        _check_image_quota(user, image)
        c.image_name, c.image_bytes, c.updated_at = store(image), len(image.data), now
        c.save()
        CreativeImage.objects.get_or_create(creative=c, image_name=c.image_name, defaults={"image_bytes": c.image_bytes, "created_at": now})
        _audit(user, "creative.image_replaced", ("campaigns.creative", c.creative_id), {"image": c.image_name})
    return _creative_view(c)


# ---------------------------------------------------------------- 다른 모듈이 쓰는 읽기

def candidate_facts_for_slot(slot_id):
    """슬롯 하나의 후보 사실. **질의 한 번.** 조회 조건은 구조적 소속(저장된 상태·꺼짐 여부·그 슬롯을 고른 그룹)만 쓴다.
    비활성화된 광고주의 광고도 꺼진 것으로 본다(Step 3-1d — 캠페인 상태는 그대로라 다시 활성화하면 다시 후보다).

    기간·금액 판정은 넣지 않는다(판정은 engine 한 곳). 상태 갱신이 늦은 종료 캠페인이 섞여 와도 engine 이 거른다.
    입찰이 없는 광고그룹은 후보가 아니다.
    """
    slot_id = parse_uuid(slot_id, "게재 위치")
    latest = Bid.objects.filter(ad_group=OuterRef("pk")).order_by("-bid_version")
    rows = (
        AdGroup.objects.filter(
            enabled=True, creative__isnull=False, campaign__status=CampaignStatus.ACTIVE, campaign__owner__is_active=True, slot_links__slot_id=slot_id,
        )
        .select_related("campaign", "creative")  # 소재는 광고그룹이 **선택한** 것(6-9c)
        .annotate(
            bid_id=Subquery(latest.values("bid_id")[:1]),
            bid_version=Subquery(latest.values("bid_version")[:1]),
            bid_amount=Subquery(latest.values("amount")[:1]),
            bid_created_at=Subquery(latest.values("created_at")[:1]),
        )
        .filter(bid_version__isnull=False)
        .order_by("ad_group_id")
    )
    return [
        CandidateFacts(
            owner_id=g.campaign.owner_id, campaign_id=g.campaign_id, ad_group_id=g.ad_group_id,
            creative_id=g.creative_id, slot_id=slot_id, pricing_unit=g.pricing_unit,
            bid_id=g.bid_id, bid_amount=g.bid_amount, bid_version=g.bid_version, bid_created_at=g.bid_created_at,
            campaign_status=g.campaign.status, ad_group_enabled=g.enabled,
            period_start=g.campaign.starts_at, period_end=g.campaign.ends_at,
            daily_budget=g.campaign.daily_budget, title=g.creative.title, redirect_url=g.creative.redirect_url, image_name=g.creative.image_name,
        )
        for g in rows
    ]


def is_asset_servable(name, now=None):
    """C3 이미지를 내보내도 되는가: 그 이름을 **보유한**(현재 또는 과거 교체분) 소재가 **연결된 적 있는** 광고그룹 중 하나라도, 그 캠페인이
    ACTIVE·PAUSED 이고 기간이 끝나지 않았으며 광고주가 활성일 때만(6-9c — 소재는 캠페인 밖에 있고, 연결은 끊지 않는다).

    교체하거나 선택을 바꾼 뒤에도 과거 결정의 이미지 URL 은 계속 열린다(캠페인이 살아 있는 동안). 중단·종료되거나 광고주가 비활성화되면 404 다.

    `config` 가 `ASSET_SERVABLE_CHECK` 로 연결한다(assets 는 campaigns 를 import 하지 않는다).
    """
    now = _now(now)
    campaign = "creative__ad_group_links__ad_group__campaign"
    return CreativeImage.objects.filter(  # 한 filter() 안에 둔다 — 여러 값 관계(연결)를 나눠 거르면 서로 다른 연결끼리 조건이 섞인다
        Q(**{f"{campaign}__ends_at__isnull": True}) | Q(**{f"{campaign}__ends_at__gt": now}),
        image_name=name, **{f"{campaign}__status__in": [CampaignStatus.ACTIVE, CampaignStatus.PAUSED], f"{campaign}__owner__is_active": True},
    ).exists()
