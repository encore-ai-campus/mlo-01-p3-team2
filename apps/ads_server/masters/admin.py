"""관리자 화면 등록. **읽기 전용**이다: 서비스 규칙(검증·버전·감사)을 우회하지 않도록 변경은 서비스 함수로만 한다.

변경 화면(정책 새 버전·일괄 입력 등)은 Step 3-1 에서 서비스를 호출하는 뷰로 만든다.
"""
from django.contrib import admin

from foundation.api import ReadOnlyAdmin

from .models import BidPolicy, Media, MediaDeactivation, MediaKey, Slot


@admin.register(Media)
class MediaAdmin(ReadOnlyAdmin):
    list_display = ("name", "is_active", "created_at")


@admin.register(MediaDeactivation)
class MediaDeactivationAdmin(ReadOnlyAdmin):
    list_display = ("media", "deactivated_at")
    ordering = ("-deactivated_at",)


@admin.register(Slot)
class SlotAdmin(ReadOnlyAdmin):
    list_display = ("name", "media", "pricing_unit", "audience", "is_active")
    list_filter = ("pricing_unit", "audience", "is_active")


@admin.register(BidPolicy)
class BidPolicyAdmin(ReadOnlyAdmin):
    list_display = ("slot", "policy_version", "floor_amount", "base_amount", "cap_amount", "changed_at", "reason")
    ordering = ("slot", "-policy_version")


@admin.register(MediaKey)
class MediaKeyAdmin(ReadOnlyAdmin):
    """키 평문은 저장하지 않고, 해시도 화면에 보이지 않는다."""

    list_display = ("key_id", "media", "label", "created_at", "expires_at", "revoked_at")
    exclude = ("secret_hash",)
