"""개인 광고의 소유권과 최초 노출 요청을 게임 DB에 고정한다."""

import uuid

from django.db import models


class IssuedDecision(models.Model):
    decision_id = models.UUIDField(primary_key=True, editable=False)
    subject_id = models.UUIDField(editable=False)
    slot_id = models.UUIDField(editable=False)
    decided_at = models.DateTimeField(editable=False)
    has_ad = models.BooleanField(editable=False)


class Impression(models.Model):
    reaction_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 개인 슬롯은 결정당 노출 한 건만 저장하여 중복 알림도 같은 반응 ID를 쓴다.
    decision = models.OneToOneField(IssuedDecision, on_delete=models.PROTECT)
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
        indexes = [
            models.Index(fields=["delivery_state", "next_attempt_at"], name="ad_bridge_retry_due"),
            models.Index(fields=["delivery_state", "lease_expires_at"], name="ad_bridge_lease_due"),
        ]
