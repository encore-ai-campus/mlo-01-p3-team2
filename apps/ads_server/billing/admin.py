"""관리자 화면 등록. **읽기 전용**: 잔액·원장은 서비스 함수(조정·과금)로만 바뀐다."""
from django.contrib import admin

from foundation.api import ReadOnlyAdmin

from .models import CampaignSpend, LedgerEntry, Wallet


@admin.register(Wallet)
class WalletAdmin(ReadOnlyAdmin):
    list_display = ("owner", "balance", "created_at")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "wallet", "entry_type", "amount", "balance_after", "campaign_id", "charge_policy", "shortfall")
    list_filter = ("entry_type",)
    ordering = ("-created_at", "-seq")


@admin.register(CampaignSpend)
class CampaignSpendAdmin(ReadOnlyAdmin):
    list_display = ("campaign_id", "budget_day", "spent")
