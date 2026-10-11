"""관리자 사이트. 관리자 본인의 비밀번호 변경도 감사 로그에 남긴다(위협 T23).

`UserAdmin` 은 다른 사용자의 비밀번호 초기화만 기록한다. 본인 변경은 AdminSite 의 별도 뷰라 여기서 잡는다.
두 비밀번호 화면 모두 `current_login_only` 로 감싸고 비밀번호 열만 쓴다(`PasswordOnlySave`).
"""
from functools import wraps

from django.contrib import admin
from django.contrib.admin.forms import AdminPasswordChangeForm as OwnPasswordForm
from django.contrib.auth import HASH_SESSION_KEY
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.crypto import constant_time_compare

from .audit import record_audit
from .models import User


class ReadOnlyAdmin(admin.ModelAdmin):
    """읽기 전용 관리자 화면. 서비스 규칙(검증·버전·상태 전이·감사)을 우회하지 않도록 모델 변경은 서비스 함수로만 한다."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PasswordOnlySave:
    """비밀번호 폼의 저장을 **비밀번호 열로만**. Django 기본은 요청 처음에 읽은 사용자 객체를 통째로 저장해, 그 사이 다른 곳이 바꾼 열
    (활성 여부·세션 폐기 버전·프로필)을 되돌린다(외부 검토 3-1d)."""

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save(update_fields=["password"])
        return user


def current_login_only(view):
    """비밀번호를 바꾸는 POST 는 **요청을 인증한 근거가 아직 유효할 때만** 처리한다: 요청한 사람의 행을 잠그고 세션의 인증 해시를 그 최신 행과 대조한 뒤
    같은 트랜잭션 안에서 처리한다 — 확인과 저장 사이에 다른 변경이 끼지 못한다. 서버 명령 `changepassword` 로 급히 끊은 뒤, 진행 중이던 요청이 서버가 정한
    비밀번호를 덮고 로그인을 이어 가던 것을 막는다(외부 검토 3-1d). 잠금을 쥔 동안 들어온 서버 명령은 기다렸다가 그 뒤에 적용된다(서버 명령이 이긴다)."""
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if request.method != "POST":
            return view(request, *args, **kwargs)
        with transaction.atomic():
            me = User.objects.select_for_update().filter(pk=request.user.pk).first()
            if me is None or not me.is_active or not constant_time_compare(request.session.get(HASH_SESSION_KEY, ""), me.get_session_auth_hash()):
                raise PermissionDenied("로그인 정보가 바뀌었습니다. 다시 로그인하세요.")
            return view(request, *args, **kwargs)
    return guarded


class OwnPasswordChangeForm(PasswordOnlySave, OwnPasswordForm):
    pass


class AuditedAdminSite(admin.AdminSite):
    password_change_form = OwnPasswordChangeForm

    def password_change(self, request, extra_context=None):
        response = current_login_only(super().password_change)(request, extra_context)
        if request.method == "POST" and response.status_code == 302:  # 성공(리다이렉트)일 때만
            record_audit(request, "account.password_changed", target=request.user, actor=request.user)
        return response
