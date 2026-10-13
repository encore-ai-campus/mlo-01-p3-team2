"""광고주가 소유하는 운영 데이터: 캠페인·광고그룹·소재·입찰·재검토 요청(설계 §4.5~4.6)."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Case, F, Q, When
from django.utils import timezone

from foundation.api import MAX_AMOUNT, AppendOnlyModel


class CampaignStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "집행 중"
    PAUSED = "PAUSED", "일시 중지"
    SUSPENDED = "SUSPENDED", "관리자 중단"
    ENDED = "ENDED", "종료"


class ReviewStatus(models.TextChoices):
    OPEN = "OPEN", "대기"
    RELEASED = "RELEASED", "해제됨"
    REJECTED = "REJECTED", "반려됨"
    CLOSED_ENDED = "CLOSED_ENDED", "캠페인 종료로 닫힘"


class Campaign(models.Model):
    campaign_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="campaigns")
    name = models.CharField(max_length=100)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)  # 끝나는 시각(미포함). 없으면 계속 진행
    daily_budget = models.PositiveBigIntegerField()
    status = models.CharField(max_length=20, choices=CampaignStatus.choices, default=CampaignStatus.ACTIVE)  # 쓰는 곳은 transitions.py 뿐
    ended_from = models.CharField(max_length=20, choices=CampaignStatus.choices, null=True, blank=True)
    suspended_reason = models.CharField(max_length=500, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    request_key = models.CharField(max_length=64, null=True, blank=True)  # 캠페인 만들기 화면 폼 하나 = 캠페인 하나(같은 키로는 다시 만들지 않는다, 6-9d)

    class Meta:
        db_table = "campaigns_campaign"
        indexes = [models.Index(fields=["status", "ends_at"])]
        constraints = [
            models.UniqueConstraint(fields=["request_key"], name="campaigns_campaign_once_per_request"),  # NULL(키 없이 만든 캠페인)은 서로 다르다
            models.CheckConstraint(condition=Q(daily_budget__gt=0, daily_budget__lte=MAX_AMOUNT), name="campaigns_campaign_budget_range"),
            models.CheckConstraint(condition=Q(ends_at__isnull=True) | Q(ends_at__gte=F("starts_at")), name="campaigns_campaign_period_order"),
        ]


class AdGroup(models.Model):
    ad_group_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="ad_groups")
    name = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)
    # 선택된 소재 — 결정에 나가는 소재다. 연결(`AdGroupCreative`)된 것 중에서만 고른다(서비스가 지킨다). 없으면 후보가 아니다(6-9c)
    creative = models.ForeignKey("Creative", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    request_key = models.CharField(max_length=64, null=True, blank=True)  # 기존 캠페인에 광고 만들기 폼 하나 = 광고그룹 하나(6-9c)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)  # 화면이 본 값과 대조해 옛 폼(이름·게재 위치)이 그 사이의 변경을 덮지 않게(3-2d)

    class Meta:
        db_table = "campaigns_ad_group"
        constraints = [models.UniqueConstraint(fields=["request_key"], name="campaigns_ad_group_once_per_request")]  # NULL 은 서로 다르다


class AdGroupSlot(models.Model):
    ad_group_slot_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    ad_group = models.ForeignKey(AdGroup, on_delete=models.CASCADE, related_name="slot_links")
    slot = models.ForeignKey("masters.Slot", on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "campaigns_ad_group_slot"
        constraints = [models.UniqueConstraint(fields=["ad_group", "slot"], name="campaigns_ad_group_slot_unique")]


class Creative(models.Model):
    """광고주 소유의 소재 목록(6-9c, 설계 §10 "소재 목록"). 광고그룹에는 `AdGroupCreative` 로 연결하고, 광고그룹이 그중 하나를 선택한다.
    화면의 "삭제"는 보관(`archived_at`)이다 — 행은 남는다(감사 기록·연결 기록이 참조). 끝나지 않은 캠페인의 광고그룹에 연결돼 있으면 보관하지 못한다.
    소재 끄기는 없다 — 광고를 멈추는 것은 광고그룹 ON/OFF 하나다(6-9b)."""

    creative_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creatives")
    title = models.CharField(max_length=200)
    redirect_url = models.CharField(max_length=2048)
    image_name = models.CharField(max_length=80, db_index=True)  # assets 의 `<sha256>.<ext>`
    image_bytes = models.PositiveIntegerField()
    archived_at = models.DateTimeField(null=True, blank=True)  # 보관(화면의 "삭제"). 보관한 소재는 개수 상한에서 빠지고 이미지 보유량에는 남는다
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "campaigns_creative"


class AdGroupCreative(AppendOnlyModel):
    """광고그룹에 연결한 소재(6-9c). **끊지 않는다**(추가만) — 연결 기록이 ① 보관 가능 여부(끝나지 않은 캠페인에 연결돼 있으면 불가) ②
    이미지 공개 판정(연결된 적 있는 광고그룹의 캠페인이 살아 있으면 공개)의 근거다. 선택을 바꿔도 이전 결정의 이미지가 깨지지 않는다."""

    link_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    ad_group = models.ForeignKey(AdGroup, on_delete=models.PROTECT, related_name="creative_links")
    creative = models.ForeignKey(Creative, on_delete=models.PROTECT, related_name="ad_group_links")
    linked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "campaigns_ad_group_creative"
        constraints = [models.UniqueConstraint(fields=["ad_group", "creative"], name="campaigns_ad_group_creative_unique")]


class CreativeImage(AppendOnlyModel):
    """소재가 지금까지 **보유한 이미지 파일**(현재 + 과거). 쿼터와 서빙 가능 여부를 이 관계로 판단한다.

    이전 이미지는 지우지 않는다(과거 결정이 URL 을 참조한다). 그래서 보유량에 포함하지 않으면 교체를 반복해 쿼터를 우회할 수 있고,
    서빙 판정에서 빼면 교체 직후 과거 결정의 이미지가 404 가 된다. `Creative.image_name` 은 그중 **현재** 것을 가리킨다.
    """

    creative_image_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    creative = models.ForeignKey(Creative, on_delete=models.PROTECT, related_name="images")
    image_name = models.CharField(max_length=80, db_index=True)
    image_bytes = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "campaigns_creative_image"
        constraints = [models.UniqueConstraint(fields=["creative", "image_name"], name="campaigns_creative_image_unique")]


class Bid(AppendOnlyModel):
    """입찰의 한 버전. 하한 미만·상한 초과도 그대로 저장한다(설계 §4.2). 현재 값 = 최대 버전."""

    bid_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)  # 버전 행 하나의 식별자이자 PK(결정·이벤트가 가리킨다)
    ad_group = models.ForeignKey(AdGroup, on_delete=models.PROTECT, related_name="bids")
    bid_version = models.PositiveIntegerField()
    amount = models.PositiveBigIntegerField()
    created_by = models.UUIDField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "campaigns_bid"
        constraints = [
            models.UniqueConstraint(fields=["ad_group", "bid_version"], name="campaigns_bid_version_per_ad_group"),
            models.CheckConstraint(condition=Q(amount__gt=0, amount__lte=MAX_AMOUNT), name="campaigns_bid_amount_range"),
        ]


class ReviewRequest(models.Model):
    """재검토 요청. 만든 뒤에는 상태·답변만 닫히고(transitions.py) 지워지지 않는다."""

    review_request_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="review_requests")
    message = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.OPEN)
    response_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    # MySQL 은 조건부 유일 제약을 만들지 않으므로(W036) DB 가 **계산하는 열**로 같은 일을 한다: 열려 있는 요청에만 캠페인 ID, 닫히면 NULL.
    # 상태를 바꾸는 코드(닫기·일괄 종료)는 이 열을 신경 쓰지 않는다 — DB 가 알아서 비운다.
    open_campaign = models.GeneratedField(
        expression=Case(When(status="OPEN", then=F("campaign")), default=None, output_field=models.UUIDField(null=True)),
        output_field=models.UUIDField(null=True), db_persist=True,
    )

    class Meta:
        db_table = "campaigns_review_request"
        constraints = [models.UniqueConstraint(fields=["open_campaign"], name="campaigns_one_open_review_per_campaign")]


class AdvertiserQuota(models.Model):
    """광고주 전체 상한(캠페인·광고그룹·소재 수, 이미지 보유량)을 지키는 **잠금 행**(값은 담지 않는다 — 수는 잠금 안에서 센다).

    캠페인마다 잠그면 서로 다른 캠페인의 동시 쓰기가 함께 줄을 서지 않아 상한을 넘었다(외부 검토 41d2288). 만들기·이미지 교체는 이 행을 **가장 먼저** 잠그고
    (그다음 캠페인 → 광고그룹·소재), 잠금 안에서 상한을 다시 센 뒤 쓴다. 처음 쓸 때 만든다. 사용자 행을 잠그지 않는 것은 인증·계정 경로와 순서를 섞지 않기 위해서다."""

    quota_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "campaigns_advertiser_quota"
