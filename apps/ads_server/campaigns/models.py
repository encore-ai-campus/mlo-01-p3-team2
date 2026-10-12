"""광고주가 소유하는 운영 데이터: 캠페인·광고그룹·소재·입찰·재검토 요청(설계 §4.5~4.6)."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Case, F, Q, When
from django.utils import timezone

from foundation.api import MAX_AMOUNT, AppendOnlyModel
from masters.api import PricingUnit


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

    class Meta:
        db_table = "campaigns_campaign"
        indexes = [models.Index(fields=["status", "ends_at"])]
        constraints = [
            models.CheckConstraint(condition=Q(daily_budget__gt=0, daily_budget__lte=MAX_AMOUNT), name="campaigns_campaign_budget_range"),
            models.CheckConstraint(condition=Q(ends_at__isnull=True) | Q(ends_at__gte=F("starts_at")), name="campaigns_campaign_period_order"),
        ]


class AdGroup(models.Model):
    ad_group_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="ad_groups")
    name = models.CharField(max_length=100)
    pricing_unit = models.CharField(max_length=20, choices=PricingUnit.choices)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "campaigns_ad_group"

    def save(self, *args, **kwargs):
        """과금 단위는 만든 뒤 바꿀 수 없다(입찰 이력의 의미가 섞이지 않게)."""
        if not self._state.adding:
            current = type(self).objects.filter(pk=self.pk).values_list("pricing_unit", flat=True).first()
            if current is not None and current != self.pricing_unit:
                raise ValueError("광고그룹의 과금 단위는 바꿀 수 없다.")
        super().save(*args, **kwargs)


class AdGroupSlot(models.Model):
    ad_group_slot_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    ad_group = models.ForeignKey(AdGroup, on_delete=models.CASCADE, related_name="slot_links")
    slot = models.ForeignKey("masters.Slot", on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "campaigns_ad_group_slot"
        constraints = [models.UniqueConstraint(fields=["ad_group", "slot"], name="campaigns_ad_group_slot_unique")]


class Creative(models.Model):
    creative_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    ad_group = models.ForeignKey(AdGroup, on_delete=models.PROTECT, related_name="creatives")
    title = models.CharField(max_length=200)
    redirect_url = models.CharField(max_length=2048)
    image_name = models.CharField(max_length=80, db_index=True)  # assets 의 `<sha256>.<ext>`
    image_bytes = models.PositiveIntegerField()
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "campaigns_creative"


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
