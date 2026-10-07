from django.contrib.auth.decorators import login_not_required
from django.urls import path

from .views.auth import ConsoleLoginView, ConsoleLogoutView, SignupView
from .views.home import advertiser_home

urlpatterns = [
    path("accounts/signup/", login_not_required(SignupView.as_view()), name="signup"),
    path("accounts/login/", login_not_required(ConsoleLoginView.as_view()), name="login"),
    path("accounts/logout/", ConsoleLogoutView.as_view(), name="logout"),
    path("advertiser/", advertiser_home, name="advertiser_home"),
]
