"""인증 사건을 감사 로그로 남긴다(가입 외의 로그인 성공·실패·잠금·로그아웃)."""
from axes.signals import user_locked_out
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .audit import record_audit
from .validators import USERNAME_RE


def _safe_username(value):
    """형식에 맞는 아이디만 남긴다. 아이디 칸에 실수로 입력한 비밀번호가 기록되지 않게 한다."""
    return value if isinstance(value, str) and USERNAME_RE.fullmatch(value) else None


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    record_audit(request, "auth.login_success", target=user, actor=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    record_audit(request, "auth.login_failed", detail={"username": _safe_username((credentials or {}).get("username"))})


@receiver(user_locked_out)
def on_locked_out(sender, request=None, username=None, ip_address=None, **kwargs):
    record_audit(request, "auth.lockout", detail={"username": _safe_username(username)})


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        record_audit(request, "auth.logout", target=user, actor=user)
