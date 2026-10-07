"""결정(Decision)의 불변 스냅샷(설계 §4.4-1). 입찰·정책·소재를 나중에 고쳐도 과거 결정은 변하지 않는다."""
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

from foundation.api import AppendOnlyModel


class Decision(AppendOnlyModel):
    decision_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # 요청 쪽 사실
    media_id = models.UUIDField(db_index=True)
    slot_id = models.UUIDField()
    subject_id = models.CharField(max_length=200, null=True, blank=True)  # V1 은 수집만 한다(설계 §3)
    decided_at = models.DateTimeField(default=timezone.now, db_index=True)
    # 선택된 광고의 스냅샷. 광고 없음이면 전부 NULL(그래도 한 건으로 남긴다)
    owner_id = models.UUIDField(null=True, blank=True)  # 과금할 지갑의 주인(그 시점의 값)
    campaign_id = models.UUIDField(null=True, blank=True)
    ad_group_id = models.UUIDField(null=True, blank=True)
    creative_id = models.UUIDField(null=True, blank=True)
    pricing_unit = models.CharField(max_length=20, null=True, blank=True)
    bid_amount = models.PositiveBigIntegerField(null=True, blank=True)
    applied_amount = models.PositiveBigIntegerField(null=True, blank=True)  # 과금액의 근거: 다시 계산하지 않는다(설계 §4.4-10)
    bid_version = models.PositiveIntegerField(null=True, blank=True)
    policy_version = models.PositiveIntegerField(null=True, blank=True)
    bid_id = models.UUIDField(null=True, blank=True)  # 선택된 입찰 버전 행(campaigns_bid.bid_id). FK 아님: 결정은 과거 사실
    bid_policy_id = models.UUIDField(null=True, blank=True)  # 판정에 쓴 정책 버전 행(masters_bid_policy.bid_policy_id)
    snapshot = models.JSONField(null=True, blank=True)  # 응답에 필요한 그 시점의 값: title·redirect_url·image_name
    # 어떤 알고리즘이 어떤 근거로 골랐는지
    selection_policy = models.CharField(max_length=64)
    trace = models.JSONField(default=dict)
    candidate_count = models.PositiveIntegerField()
    rejected_counts = models.JSONField(default=dict)

    class Meta:
        db_table = "records_decision"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(creative_id__isnull=True, campaign_id__isnull=True, ad_group_id__isnull=True, owner_id__isnull=True,
                      pricing_unit__isnull=True, bid_amount__isnull=True, applied_amount__isnull=True, bid_version__isnull=True,
                      policy_version__isnull=True, bid_id__isnull=True, bid_policy_id__isnull=True, snapshot__isnull=True)
                    | Q(creative_id__isnull=False, campaign_id__isnull=False, ad_group_id__isnull=False, owner_id__isnull=False,
                        pricing_unit__isnull=False, bid_amount__isnull=False, applied_amount__isnull=False, bid_version__isnull=False,
                        policy_version__isnull=False, bid_id__isnull=False, bid_policy_id__isnull=False, snapshot__isnull=False)
                ),
                name="records_decision_chosen_all_or_none",
            ),
        ]
        indexes = [models.Index(fields=["media_id", "decided_at"])]
