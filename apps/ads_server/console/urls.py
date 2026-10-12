from django.contrib.auth.decorators import login_not_required
from django.urls import path
from django.views.generic import RedirectView

from .views.auth import ConsoleLoginView, ConsoleLogoutView, SignupView
from .views.home import advertiser_home

urlpatterns = [
    path("", login_not_required(RedirectView.as_view(pattern_name="login")), name="root"),  # 루트 주소는 로그인으로(로그인한 사용자는 로그인 화면이 다시 자기 첫 화면으로 보낸다)
    path("accounts/signup/", login_not_required(SignupView.as_view()), name="signup"),
    path("accounts/login/", login_not_required(ConsoleLoginView.as_view()), name="login"),
    path("accounts/logout/", ConsoleLogoutView.as_view(), name="logout"),
    path("advertiser/", advertiser_home, name="advertiser_home"),
]
