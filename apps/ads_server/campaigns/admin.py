"""관리자 화면 등록. **읽기 전용**: 서비스 규칙(상태 전이·종료 가드·검증·감사)을 우회하지 않도록 변경은 서비스 함수로만 한다."""
from django.contrib import admin

from .models import AdGroup, Bid, Campaign, Creative, ReviewRequest


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Campaign)
class CampaignAdmin(ReadOnlyAdmin):
    list_display = ("name", "owner", "status", "starts_at", "ends_at", "daily_budget")
    list_filter = ("status",)


@admin.register(AdGroup)
class AdGroupAdmin(ReadOnlyAdmin):
    list_display = ("name", "campaign", "pricing_unit", "enabled")


@admin.register(Creative)
class CreativeAdmin(ReadOnlyAdmin):
    list_display = ("title", "ad_group", "image_name", "enabled")


@admin.register(Bid)
class BidAdmin(ReadOnlyAdmin):
    list_display = ("ad_group", "bid_version", "amount", "created_at")


@admin.register(ReviewRequest)
class ReviewRequestAdmin(ReadOnlyAdmin):
    list_display = ("campaign", "status", "created_at", "closed_at")
