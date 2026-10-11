"""관리자 화면(Django admin): 사용자 관리와 감사 로그 열람. 변경은 감사 로그에 남는다."""
from axes import admin as axes_admin
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.admin.utils import unquote

from .admin_site import ReadOnlyAdmin
from .audit import record_audit
from .models import AuditLog, User
from .templatetags.kst import kst


class AdminUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "nickname", "class_label", "role")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = AdminUserCreationForm
    list_display = ("username", "nickname", "class_label", "role", "is_active", "created_kst")
    list_filter = ("role", "is_active")
    search_fields = ("username", "nickname")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "last_login")
    filter_horizontal = ()
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("프로필", {"fields": ("nickname", "class_label")}),
        ("권한", {"fields": ("role", "is_active", "is_superuser")}),
        ("기록", {"fields": ("created_at", "last_login")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "nickname", "class_label", "role", "password1", "password2")}),
    )

    @admin.display(description="가입(KST)", ordering="created_at")
    def created_kst(self, obj):
        return kst(obj.created_at)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        changed = [name for name in form.changed_data if "password" not in name]
        record_audit(
            request, "account.admin_updated" if change else "account.admin_created", target=obj,
            detail={"changed": changed, "role": obj.role, "is_active": obj.is_active},
        )

    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url)
        if response.status_code == 302:  # 성공(리다이렉트)일 때만
            record_audit(request, "account.password_reset_by_admin", target=self.get_object(request, unquote(id)))
        return response


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    """읽기 전용. 추가·수정·삭제를 모두 막는다."""

    list_display = ("created_kst", "action", "actor_username", "target_type", "target_id", "ip", "request_id")
    list_filter = ("action",)
    search_fields = ("actor_username", "target_id", "request_id")
    ordering = ("-created_at",)

    @admin.display(description="시각(KST)", ordering="created_at")
    def created_kst(self, obj):
        return kst(obj.created_at, "%Y-%m-%d %H:%M:%S")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]


# ---------------------------------------------------------------- 로그인 잠금 기록(django-axes) — 읽기 전용(설계 §10 "로그인 잠금 기록 관리", 위협 모델 T44)
# 화면에서 기록을 지우거나 고치면 잠금이 풀리는데 그 행위는 감사 로그에 남지 않는다. 그래서 보기만 하고(목록·필터·상세는 axes 의 것 그대로),
# 묶음 동작(삭제·만료 정리)도 뺀다. 급할 때는 서버 명령(`axes_reset_username` 등)으로 푼다. 설정 AXES_ENABLE_ADMIN = False 가 axes 자체 등록을 끈다.

class _ReadOnlyLockoutAdmin(ReadOnlyAdmin):
    actions = None


@admin.register(AccessAttempt)
class AccessAttemptAdmin(_ReadOnlyLockoutAdmin, axes_admin.AccessAttemptAdmin):
    pass


@admin.register(AccessLog)
class AccessLogAdmin(_ReadOnlyLockoutAdmin, axes_admin.AccessLogAdmin):
    pass


@admin.register(AccessFailureLog)
class AccessFailureLogAdmin(_ReadOnlyLockoutAdmin, axes_admin.AccessFailureLogAdmin):
    pass
