from django.contrib.auth.decorators import login_not_required, login_required
from django.shortcuts import redirect, render, resolve_url

from foundation.api import Role


def home_url(user):
    """역할별 첫 화면. 관리자는 관리자 화면, 광고주는 광고주 화면."""
    return resolve_url("admin:index") if user.role == Role.ADMIN else resolve_url("advertiser_home")


@login_not_required
def root(request):
    """루트 주소: 로그인했으면 역할의 첫 화면, 아니면 로그인 화면."""
    return redirect(home_url(request.user) if request.user.is_authenticated else "login")


@login_required
def advertiser_home(request):
    return render(request, "console/advertiser_home.html")
