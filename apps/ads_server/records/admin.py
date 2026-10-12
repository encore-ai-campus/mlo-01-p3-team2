"""관리자 화면 등록. **읽기 전용**: 결정은 한 번 쓰면 바뀌지 않는다."""
from django.contrib import admin

from foundation.api import ReadOnlyAdmin

from .models import Decision


@admin.register(Decision)
class DecisionAdmin(ReadOnlyAdmin):
    list_display = ("decided_at", "media_id", "slot_id", "campaign_id", "applied_amount", "selection_policy", "candidate_count")
    ordering = ("-decided_at",)
