from django.contrib.auth.decorators import login_not_required
from django.urls import path

from .views.account import my_account, my_password
from .views.auth import ConsoleLoginView, ConsoleLogoutView, SignupView
from .views.ads import ad_create
from .views.campaigns import campaign_detail, campaign_end, campaign_list, campaign_review, campaign_status
from .views.dashboard import advertiser_home
from .views.home import root

urlpatterns = [
    path("", root, name="root"),  # 역할의 첫 화면으로(익명은 로그인)
    path("accounts/signup/", login_not_required(SignupView.as_view()), name="signup"),
    path("accounts/login/", login_not_required(ConsoleLoginView.as_view()), name="login"),
    path("accounts/logout/", ConsoleLogoutView.as_view(), name="logout"),
    path("advertiser/", advertiser_home, name="advertiser_home"),
    path("advertiser/ads/new/", ad_create, name="ad_create"),
    path("advertiser/campaigns/", campaign_list, name="campaign_list"),
    path("advertiser/campaigns/<str:campaign_id>/", campaign_detail, name="campaign_detail"),
    path("advertiser/campaigns/<str:campaign_id>/status", campaign_status, name="campaign_status"),
    path("advertiser/campaigns/<str:campaign_id>/end", campaign_end, name="campaign_end"),
    path("advertiser/campaigns/<str:campaign_id>/review", campaign_review, name="campaign_review"),
    path("advertiser/me/", my_account, name="my_account"),
    path("advertiser/me/password", my_password, name="my_password"),
]
