"""관리자 화면 등록. **읽기 전용**: 결정은 한 번 쓰면 바뀌지 않는다."""
from django.contrib import admin

from .models import Decision


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ("decided_at", "media_id", "slot_id", "campaign_id", "applied_amount", "selection_policy", "candidate_count")
    ordering = ("-decided_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
