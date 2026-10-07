"""포인트 지갑·원장·캠페인 일 소진액(설계 §4.7). billing 은 캠페인을 ID 값으로만 안다(campaigns 를 import 하지 않는다)."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from foundation.api import MAX_AMOUNT, AppendOnlyModel


class EntryType(models.TextChoices):
    SIGNUP_GRANT = "SIGNUP_GRANT", "가입 지급"
    CHARGE = "CHARGE", "반응 과금"
    ADMIN_ADJUST = "ADMIN_ADJUST", "관리자 조정"
    TOPUP = "TOPUP", "충전(예약, C5)"


class Wallet(models.Model):
    wallet_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wallet")
    balance = models.PositiveBigIntegerField(default=0)  # 0 밑으로 내려가지 않고 MAX_AMOUNT 를 넘지 않는다(DB 제약). 값은 원장 합계와 같아야 한다
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "billing_wallet"
        constraints = [models.CheckConstraint(condition=Q(balance__lte=MAX_AMOUNT), name="billing_wallet_balance_max")]


class LedgerEntry(AppendOnlyModel):
    """원장의 한 줄. 추가만 하고 정정은 반대 부호의 새 줄(ADMIN_ADJUST)로 한다(설계 §4.4-8)."""

    entry_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="entries")
    seq = models.PositiveIntegerField()  # 지갑 안의 순서(1부터, 지갑 잠금 안에서 +1). 연속성 점검·목록 커서의 기준
    entry_type = models.CharField(max_length=20, choices=EntryType.choices)
    amount = models.BigIntegerField()  # 부호 있는 정수. 지급·충전은 +, 과금은 −(또는 잔액이 없으면 0)
    balance_after = models.PositiveBigIntegerField()
    campaign_id = models.UUIDField(null=True, blank=True)  # FK 가 아니다: 캠페인은 다른 모듈의 것
    reaction_ref = models.CharField(max_length=100, null=True, blank=True)  # 과금 멱등 키(예: "<매체>:<reaction_id>")
    charge_policy = models.CharField(max_length=64, blank=True)  # 어떤 과금 정책이었는지(R8)
    shortfall = models.PositiveBigIntegerField(default=0)  # 잔액이 모자라 못 받은 금액
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "billing_ledger_entry"
        constraints = [
            models.UniqueConstraint(fields=["wallet", "seq"], name="billing_entry_seq_per_wallet"),
            models.CheckConstraint(condition=Q(seq__gte=1), name="billing_entry_seq_from_one"),
            models.UniqueConstraint(fields=["wallet"], condition=Q(entry_type="SIGNUP_GRANT"), name="billing_one_signup_grant_per_wallet"),
            models.UniqueConstraint(fields=["reaction_ref"], condition=Q(reaction_ref__isnull=False), name="billing_charge_once_per_reaction"),
            models.CheckConstraint(
                condition=(
                    Q(entry_type="CHARGE", amount__lte=0, amount__gte=-MAX_AMOUNT)
                    | Q(entry_type__in=["SIGNUP_GRANT", "TOPUP"], amount__gt=0, amount__lte=MAX_AMOUNT)
                    | (Q(entry_type="ADMIN_ADJUST", amount__gte=-MAX_AMOUNT, amount__lte=MAX_AMOUNT) & ~Q(amount=0))
                ),
                name="billing_entry_amount_sign_by_type",
            ),
            models.CheckConstraint(
                condition=Q(entry_type="CHARGE") | Q(reaction_ref__isnull=True), name="billing_only_charges_have_reaction_ref"
            ),
            models.CheckConstraint(condition=Q(balance_after__lte=MAX_AMOUNT), name="billing_entry_balance_after_max"),
        ]


class CampaignSpend(models.Model):
    """캠페인의 그날 소진액. **원장에서 다시 계산할 수 있는 파생값**이다(recompute_spend)."""

    spend_id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    campaign_id = models.UUIDField()
    budget_day = models.DateField()
    spent = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "billing_campaign_spend"
        constraints = [models.UniqueConstraint(fields=["campaign_id", "budget_day"], name="billing_spend_per_campaign_day")]
