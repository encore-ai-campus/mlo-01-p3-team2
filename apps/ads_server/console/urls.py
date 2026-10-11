from django.contrib.auth.decorators import login_not_required
from django.urls import path

from .views.account import my_account, my_password
from .views.auth import ConsoleLoginView, ConsoleLogoutView, SignupView
from .views.home import advertiser_home, root

urlpatterns = [
    path("", root, name="root"),  # 역할의 첫 화면으로(익명은 로그인)
    path("accounts/signup/", login_not_required(SignupView.as_view()), name="signup"),
    path("accounts/login/", login_not_required(ConsoleLoginView.as_view()), name="login"),
    path("accounts/logout/", ConsoleLogoutView.as_view(), name="logout"),
    path("advertiser/", advertiser_home, name="advertiser_home"),
    path("advertiser/me/", my_account, name="my_account"),
    path("advertiser/me/password", my_password, name="my_password"),
]
