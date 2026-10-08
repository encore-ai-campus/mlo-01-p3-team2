"""결정(Decision)의 불변 스냅샷(설계 §4.4-1). 입찰·정책·소재를 나중에 고쳐도 과거 결정은 변하지 않는다."""
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

from foundation.api import AppendOnlyModel
from masters.api import Audience


class Decision(AppendOnlyModel):
    decision_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    # 요청 쪽 사실
    media_id = models.UUIDField(db_index=True)
    slot_id = models.UUIDField()
    subject_id = models.CharField(max_length=200, null=True, blank=True)  # V1 은 수집만 한다(설계 §3). `shared` 슬롯의 결정에는 없다
    audience = models.CharField(max_length=20)  # 슬롯 성격의 스냅샷(`individual`·`shared`). 슬롯은 바뀌지 않지만 결정은 자기 사실을 들고 있다
    context = models.JSONField(default=dict, blank=True)  # 매체 부가 정보. 저장만 하고 해석하지 않는다(계약 C1, DRD D-2)
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
            models.CheckConstraint(  # 개인 슬롯의 결정은 사람이 있고, 일괄 슬롯의 결정은 사람이 없다(계약 C1 `subject_id`)
                condition=(Q(audience=Audience.INDIVIDUAL, subject_id__isnull=False) | Q(audience=Audience.SHARED, subject_id__isnull=True)),
                name="records_decision_subject_by_audience",
            ),
        ]
        indexes = [models.Index(fields=["media_id", "decided_at"])]


class ReactionType(models.TextChoices):
    IMPRESSION = "IMPRESSION", "노출"
    CLICK = "CLICK", "클릭"
    CONVERSION = "CONVERSION", "전환"


class ReactionStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "접수(처리 대기)"
    ACCEPTED = "ACCEPTED", "인정"
    REJECTED = "REJECTED", "거부"


class Reaction(models.Model):
    """반응 수신함(inbox, 설계 §4.4, DRD P2). 매체가 보고한 노출·클릭·전환을 **받은 그대로** 저장한다.

    **2xx 응답 = 이 행이 커밋됐다**는 뜻이다. 과금 판정(`ACCEPTED`/`REJECTED`)은 이후 별도 트랜잭션이 상태만 바꾼다(2-5).
    접수한 반응은 거부돼도 지우지 않는다. 결정은 FK 가 아니다: 없는 결정·남의 결정에 대한 보고도 일단 받고 나중에 거부한다.
    """

    inbox_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    media_id = models.UUIDField()
    reaction_id = models.UUIDField()  # 매체가 만든 ID. 유일성의 범위는 매체 안이다
    decision_id = models.UUIDField()
    type = models.CharField(max_length=20, choices=ReactionType.choices)
    occurred_at = models.DateTimeField()  # 매체가 감지한 시각. 참고용
    received_at = models.DateTimeField(default=timezone.now)  # 서버 수신 시각. 분석의 기준
    raw = models.JSONField()  # 받은 본문 그대로(검증을 통과한 JSON 객체)
    status = models.CharField(max_length=20, choices=ReactionStatus.choices, default=ReactionStatus.RECEIVED)
    reason_code = models.CharField(max_length=40, null=True, blank=True)  # REJECTED 일 때만
    applied_rule = models.CharField(max_length=64, null=True, blank=True)  # 거부한 규칙의 이름(REJECTED 일 때만)
    processed_at = models.DateTimeField(null=True, blank=True)  # 처리(인정·거부)한 시각. RECEIVED 면 없다
    attempts = models.PositiveSmallIntegerField(default=0)  # 처리에 실패한 횟수(반복 실패하는 반응이 대기열을 막지 않게)

    class Meta:
        db_table = "records_reaction"
        constraints = [
            models.UniqueConstraint(fields=["media_id", "reaction_id"], name="records_reaction_once_per_media"),
            models.CheckConstraint(condition=Q(type__in=ReactionType.values), name="records_reaction_type_valid"),
            models.CheckConstraint(condition=Q(status__in=ReactionStatus.values), name="records_reaction_status_valid"),
            models.CheckConstraint(
                condition=(Q(status="REJECTED", reason_code__isnull=False) | (~Q(status="REJECTED") & Q(reason_code__isnull=True))),
                name="records_reaction_reason_only_when_rejected",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="RECEIVED", processed_at__isnull=True, applied_rule__isnull=True)
                    | Q(status="ACCEPTED", processed_at__isnull=False, applied_rule__isnull=True)
                    | Q(status="REJECTED", processed_at__isnull=False, applied_rule__isnull=False)
                ),
                name="records_reaction_processed_state",
            ),
            # 안전망: 결정당 유형별로 인정된 반응은 하나뿐이다(규칙 `once-per-type` 이 먼저 거르고, 동시 처리가 새도 DB 가 막는다)
            models.UniqueConstraint(fields=["decision_id", "type"], condition=Q(status="ACCEPTED"), name="records_reaction_one_accepted_per_type"),
        ]
        indexes = [models.Index(fields=["status", "received_at"], name="records_reaction_pending_idx")]
