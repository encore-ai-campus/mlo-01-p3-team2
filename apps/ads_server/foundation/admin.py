"""관리자 화면(Django admin): 사용자 관리와 감사 로그 열람. 변경은 감사 로그에 남는다."""
from axes import admin as axes_admin
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.admin.utils import unquote

from .admin_site import ReadOnlyAdmin
from .audit import record_audit
from .models import AuditLog, User
from .templatetags.kst import kst


class PasswordResetForm(AdminPasswordChangeForm):
    def save(self, commit=True):
        """비밀번호 열만 쓴다. 기본은 요청 처음에 읽은 사용자 객체를 통째로 저장해, 그 사이 운영 화면이 한 비활성화(`is_active`·`session_epoch`)를 되돌린다."""
        user = super().save(commit=False)
        if commit:
            user.save(update_fields=["password"])
        return user


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """프로필(아이디·닉네임·반)과 비밀번호 초기화만 한다. 계정을 **추가하지 않고, 역할·활성 여부·슈퍼유저 여부를 바꾸지 않는다**(설계 §10).

    - 관리자는 서버 명령(`createsuperuser`)으로만, 광고주는 가입(`billing.register_advertiser`: 계정·지갑·가입 지급이 한 트랜잭션)으로만 생긴다.
    - 광고주의 활성 여부는 운영 화면(`set_advertiser_active`: 사유 필수·감사·세션 폐기 버전, 송출도 멈춤)으로만 바꾼다. 역할을 바꿀 수 있으면 역할을 거쳐 이를 우회했다.
    - 관리자 계정은 처음에 몇 개 만들고 끝이라 화면에서 끌 일이 없다. 급히 끊을 때는 서버 명령 `changepassword`(비밀번호가 바뀌면 세션이 모두 끝난다).
      화면에 두면 관리자 세션을 탈취한 사람이 다른 관리자를 끌 수 있고, 폼을 연 뒤 바뀐 값을 옛 체크박스가 되돌린다.
    - `is_superuser`: admin 사이트 입장은 역할(`is_staff`)이 정하지만 모델 화면은 권한 검사라, 그룹·권한을 주지 않는 이 프로젝트에서는 `is_superuser` 만 통과시킨다.
      역할과 따로 바뀌면 "들어가지만 아무것도 못 보는 관리자"처럼 뜻이 엇갈린다 — 관리자 ⇔ 슈퍼유저를 계정을 만든 곳(매니저)이 정한다.
    """

    change_password_form = PasswordResetForm
    list_display = ("username", "nickname", "class_label", "role", "is_active", "created_kst")
    list_filter = ("role", "is_active")
    search_fields = ("username", "nickname")
    ordering = ("-created_at",)
    readonly_fields = ("role", "is_active", "is_superuser", "created_at", "last_login")
    filter_horizontal = ()
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("프로필", {"fields": ("nickname", "class_label")}),
        ("권한", {"fields": ("role", "is_active", "is_superuser"), "description": (
            "여기서는 바꾸지 않습니다. 광고주의 활성 여부는 관리자 첫 화면의 ‘광고주 · 포인트 조정’에서 사유와 함께 바꿉니다(비활성화하면 광고도 나가지 않습니다). "
            "관리자 계정을 급히 끊을 때는 서버 명령 changepassword 를 씁니다."
        )}),
        ("기록", {"fields": ("created_at", "last_login")}),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description="가입(KST)", ordering="created_at")
    def created_kst(self, obj):
        return kst(obj.created_at)

    def save_model(self, request, obj, form, change):
        """**편집한 칸만** 쓴다. 기본 `obj.save()` 는 요청 처음에 읽은 객체의 모든 열을 다시 써서, 그 사이 운영 화면이 한 광고주 비활성화
        (`is_active`·`session_epoch`)를 프로필 편집이 되돌렸다(외부 검토 3-1d). 읽기 전용 칸은 폼에 없으므로 `changed_data` 에도 없다."""
        changed = [name for name in form.changed_data if name in form.cleaned_data and "password" not in name]
        if changed:
            obj.save(update_fields=changed)
        record_audit(request, "account.admin_updated", target=obj, detail={"changed": changed, "role": obj.role})

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
