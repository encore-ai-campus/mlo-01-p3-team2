"""관리자가 소유하는 마스터: 매체·게재 위치(슬롯)·입찰 정책(설계 §4.1)."""
import uuid

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from foundation.api import MAX_AMOUNT, AppendOnlyModel


class PricingUnit(models.TextChoices):
    IMPRESSION = "IMPRESSION", "노출"
    CLICK = "CLICK", "클릭"
    CONVERSION = "CONVERSION", "전환"


class Media(models.Model):
    media_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "masters_media"

    def __str__(self):
        return self.name


class Slot(models.Model):
    slot_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    media = models.ForeignKey(Media, on_delete=models.PROTECT, related_name="slots")
    name = models.CharField(max_length=100)
    pricing_unit = models.CharField(max_length=20, choices=PricingUnit.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "masters_slot"
        constraints = [models.UniqueConstraint(fields=["media", "name"], name="masters_slot_name_per_media")]

    def save(self, *args, **kwargs):
        """과금 단위는 만든 뒤 바꿀 수 없다(입찰 이력의 의미가 섞이지 않게, 설계 §4.1)."""
        if not self._state.adding:
            current = type(self).objects.filter(pk=self.pk).values_list("pricing_unit", flat=True).first()
            if current is not None and current != self.pricing_unit:
                raise ValueError("슬롯의 과금 단위는 바꿀 수 없다.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.media_id}/{self.name}"


class BidPolicy(AppendOnlyModel):
    """슬롯별 입찰 정책의 한 버전. 수정이 아니라 새 버전 행 추가이고, 현재 값 = 최대 버전이다."""

    slot = models.ForeignKey(Slot, on_delete=models.PROTECT, related_name="policies")
    policy_version = models.PositiveIntegerField()
    floor_amount = models.PositiveBigIntegerField()
    base_amount = models.PositiveBigIntegerField()
    cap_amount = models.PositiveBigIntegerField()
    changed_by = models.UUIDField()  # FK 가 아니다: 사용자가 바뀌어도 이력은 그대로(감사 로그와 같은 이유)
    changed_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=200)

    class Meta:
        db_table = "masters_bid_policy"
        constraints = [
            models.UniqueConstraint(fields=["slot", "policy_version"], name="masters_policy_version_per_slot"),
            models.CheckConstraint(
                condition=Q(floor_amount__gt=0, floor_amount__lte=F("base_amount"), base_amount__lte=F("cap_amount"),
                            cap_amount__lte=MAX_AMOUNT),
                name="masters_policy_floor_base_cap_order",
            ),
        ]
