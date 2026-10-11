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
    """비밀번호 폼의 저장을 **비밀번호 열로만**. Django 기본의 통째 저장은 폼의 사용자 객체를 읽은 뒤 다른 곳이 바꾼 열(활성 여부·세션 폐기 버전·프로필)을
    되돌린다(외부 검토 3-1d). 본인 변경 폼의 사용자는 인증할 때(잠그기 전) 읽은 객체라 꼭 필요하고, 사용자 관리의 초기화는 대상을 잠근 뒤에 읽지만
    **심층 방어**로 둔다 — 잠금이 대상을 놓치면(ID 해석 차이 등) 이 보호가 없을 때 비활성화가 되돌려졌다."""

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save(update_fields=["password"])
        return user


def current_login_only(view, *others, audit=None):
    """비밀번호를 바꾸는 POST 는 **요청을 인증한 근거가 아직 유효할 때만** 처리한다: 요청한 사람의 행을 잠그고 세션의 인증 해시를 그 최신 행과 대조한 뒤
    같은 트랜잭션 안에서 처리한다 — 확인과 저장 사이에 다른 변경이 끼지 못한다. 서버 명령 `changepassword` 로 급히 끊은 뒤, 진행 중이던 요청이 서버가 정한
    비밀번호를 덮고 로그인을 이어 가던 것을 막는다(외부 검토 3-1d). 잠금을 쥔 동안 들어온 서버 명령은 기다렸다가 그 뒤에 적용된다(서버 명령이 이긴다).

    `others`: 이 요청이 바꿀 다른 사용자의 **해석이 끝난 PK**(사용자 관리의 초기화 대상 — 화면이 대상을 찾는 것과 같은 해석을 호출한 쪽이 한다).
    요청자와 함께 **ID 순서로 한 번에** 잠근다 — 두 관리자가 서로를 동시에 초기화해도 잠금 순서가 같아 교착 없이 줄을 서고, 뒤의 요청은 앞의 초기화로
    바뀐 자기 인증 근거 때문에 403 이다(요청자부터 잠그면 순서가 엇갈려 교착·500).

    `audit(request)`: 성공(리다이렉트)했을 때 남길 감사 기록. **변경과 같은 트랜잭션**에서 쓴다 — 기록이 실패하면 비밀번호도 되돌려진다
    (커밋 뒤에 쓰면 응답은 500 인데 비밀번호는 바뀌고 기록은 없었다, 외부 검토 7936ac7)."""
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if request.method != "POST":
            return view(request, *args, **kwargs)
        with transaction.atomic():
            locked = User.objects.select_for_update().filter(pk__in=[request.user.pk, *others]).order_by("pk")
            me = next((u for u in locked if u.pk == request.user.pk), None)
            if me is None or not me.is_active or not constant_time_compare(request.session.get(HASH_SESSION_KEY, ""), me.get_session_auth_hash()):
                raise PermissionDenied("로그인 정보가 바뀌었습니다. 다시 로그인하세요.")
            response = view(request, *args, **kwargs)
            if audit is not None and response.status_code == 302:
                audit(request)
            return response
    return guarded


class OwnPasswordChangeForm(PasswordOnlySave, OwnPasswordForm):
    pass


class AuditedAdminSite(admin.AdminSite):
    password_change_form = OwnPasswordChangeForm

    def password_change(self, request, extra_context=None):
        audit = lambda r: record_audit(r, "account.password_changed", target=r.user, actor=r.user)  # noqa: E731
        return current_login_only(super().password_change, audit=audit)(request, extra_context)
