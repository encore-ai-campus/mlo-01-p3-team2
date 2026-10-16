"""개인·공유 광고 결정과 사용자별 최초 노출 요청을 게임 DB에 고정한다."""

import uuid

from django.db import models


class IssuedDecision(models.Model):
    decision_id = models.UUIDField(primary_key=True, editable=False)
    audience = models.CharField(max_length=16, default="individual", editable=False)
    # 내부 소유자는 외부 전송 가명과 분리한다. 기존 기록의 소유자는 자동 추정하지 않는다.
    owner_id = models.UUIDField(null=True, default=None, editable=False)
    # 결정 발급 당시의 가명은 비밀 교체 뒤에도 노출 요청에 그대로 사용한다.
    # 공유 결정에는 사용자를 넣지 않고, 실제 본 사람의 가명을 노출 기록에 저장한다.
    subject_id = models.UUIDField(null=True, default=None, editable=False)
    slot_id = models.UUIDField(editable=False)
    decided_at = models.DateTimeField(editable=False)
    has_ad = models.BooleanField(editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(audience="individual", subject_id__isnull=False)
                    | models.Q(audience="shared", owner_id__isnull=True, subject_id__isnull=True)
                ),
                name="ad_bridge_decision_audience",
            ),
        ]


class Impression(models.Model):
    reaction_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    decision = models.ForeignKey(IssuedDecision, on_delete=models.PROTECT)
    # 소유자를 모르는 이전 기록만 NULL로 남긴다. 광고 가명으로 소유자를 추정하지 않는다.
    owner_id = models.UUIDField(null=True, default=None, editable=False)
    subject_id = models.UUIDField(editable=False)
    # 직렬화된 시각을 그대로 보관하여 재전송 시 정밀도·표기를 바꾸지 않는다.
    occurred_at = models.CharField(max_length=64, editable=False)
    delivery_state = models.CharField(max_length=16, default="SENDING")
    status = models.CharField(max_length=16, null=True, default=None)
    reason_code = models.TextField(null=True, default=None)
    request_id = models.TextField(null=True, default=None)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, default=None)
    last_error = models.CharField(max_length=64, null=True, default=None)
    last_http_status = models.PositiveSmallIntegerField(null=True, default=None)
    lease_token = models.UUIDField(null=True, default=None, editable=False)
    lease_expires_at = models.DateTimeField(null=True, default=None)

    class Meta:
        constraints = [
            # 비밀이 교체돼 가명이 달라져도 같은 사람의 최초 노출을 재사용한다.
            models.UniqueConstraint(fields=["decision", "owner_id"], name="ad_bridge_impression_owner"),
            models.UniqueConstraint(fields=["decision", "subject_id"], name="ad_bridge_impression_subject"),
        ]
        indexes = [
            models.Index(fields=["delivery_state", "next_attempt_at"], name="ad_bridge_retry_due"),
            models.Index(fields=["delivery_state", "lease_expires_at"], name="ad_bridge_lease_due"),
        ]


class PlacementBatch(models.Model):
    """공통 회차·이동 한 번을 예약하여 비멱등 광고 발급을 한 번만 시도한다."""

    key = models.CharField(max_length=100, primary_key=True)
    owner_id = models.UUIDField(null=True, editable=False)
    state = models.CharField(max_length=16, default="PENDING")
    payload = models.JSONField(default=list)
    expires_at = models.DateTimeField()
