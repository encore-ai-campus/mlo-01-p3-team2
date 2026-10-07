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
    media_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "masters_media"

    def __str__(self):
        return self.name


class Slot(models.Model):
    slot_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
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


class MediaKey(models.Model):
    """매체 서버가 `X-Media-Key` 로 보내는 키(설계 §3 C1). **평문은 저장하지 않는다** — 발급할 때 한 번만 돌려준다.

    키 형식은 `<key_id>.<비밀>` 이다. `key_id`(공개 식별자)로 행을 찾고 비밀의 해시를 상수시간으로 비교한다.
    비밀은 256비트 무작위 값이라 비밀번호용 느린 해시가 필요 없다(SHA-256 으로 충분하고 요청마다 비교해도 싸다).
    매체마다 여러 개가 동시에 유효할 수 있다(교체 유예 기간).
    """

    key_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    media = models.ForeignKey(Media, on_delete=models.PROTECT, related_name="keys")
    secret_hash = models.CharField(max_length=64)
    label = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)  # 교체 유예가 끝나는 시각. 없으면 계속 유효
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "masters_media_key"


class BidPolicy(AppendOnlyModel):
    """슬롯별 입찰 정책의 한 버전. 수정이 아니라 새 버전 행 추가이고, 현재 값 = 최대 버전이다."""

    bid_policy_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)  # 버전 행 하나의 식별자이자 PK(결정·이벤트가 가리킨다)
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
