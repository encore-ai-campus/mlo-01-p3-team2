from django.contrib.auth.decorators import login_not_required
from django.urls import path

from .views.account import my_account, my_password
from .views.auth import ConsoleLoginView, ConsoleLogoutView, SignupView
from .views.ad_groups import (
    ad_group_bid, ad_group_creative_link, ad_group_creative_select, ad_group_creative_upload, ad_group_detail, ad_group_enabled, ad_group_name, ad_group_slots,
)
from .views.ads import ad_create
from .views.campaigns import campaign_create, campaign_detail, campaign_end, campaign_list, campaign_review, campaign_status
from .views.creatives import creative_archive, creative_detail, creative_edit, creative_image, creative_image_file, creative_list
from .views.dashboard import advertiser_home
from .views.points import points
from .views.home import root

urlpatterns = [
    path("", root, name="root"),  # 역할의 첫 화면으로(익명은 로그인)
    path("accounts/signup/", login_not_required(SignupView.as_view()), name="signup"),
    path("accounts/login/", login_not_required(ConsoleLoginView.as_view()), name="login"),
    path("accounts/logout/", ConsoleLogoutView.as_view(), name="logout"),
    path("advertiser/", advertiser_home, name="advertiser_home"),
    path("advertiser/ads/new/", ad_create, name="ad_create"),
    path("advertiser/ad-groups/<str:ad_group_id>/", ad_group_detail, name="ad_group_detail"),
    path("advertiser/ad-groups/<str:ad_group_id>/bid", ad_group_bid, name="ad_group_bid"),
    path("advertiser/ad-groups/<str:ad_group_id>/name", ad_group_name, name="ad_group_name"),
    path("advertiser/ad-groups/<str:ad_group_id>/slots", ad_group_slots, name="ad_group_slots"),
    path("advertiser/ad-groups/<str:ad_group_id>/enabled", ad_group_enabled, name="ad_group_enabled"),
    path("advertiser/ad-groups/<str:ad_group_id>/creatives", ad_group_creative_upload, name="ad_group_creative_upload"),
    path("advertiser/ad-groups/<str:ad_group_id>/creatives/link", ad_group_creative_link, name="ad_group_creative_link"),
    path("advertiser/ad-groups/<str:ad_group_id>/creatives/select", ad_group_creative_select, name="ad_group_creative_select"),
    path("advertiser/creatives/", creative_list, name="creative_list"),
    path("advertiser/creatives/<str:creative_id>/", creative_detail, name="creative_detail"),
    path("advertiser/creatives/<str:creative_id>/archive", creative_archive, name="creative_archive"),
    path("advertiser/creatives/<str:creative_id>/edit", creative_edit, name="creative_edit"),
    path("advertiser/creatives/<str:creative_id>/image", creative_image, name="creative_image"),
    path("advertiser/creatives/<str:creative_id>/image-file", creative_image_file, name="creative_image_file"),
    path("advertiser/campaigns/", campaign_list, name="campaign_list"),
    path("advertiser/campaigns/new/", campaign_create, name="campaign_create"),  # 아래 <campaign_id> 보다 먼저
    path("advertiser/campaigns/<str:campaign_id>/", campaign_detail, name="campaign_detail"),
    path("advertiser/campaigns/<str:campaign_id>/status", campaign_status, name="campaign_status"),
    path("advertiser/campaigns/<str:campaign_id>/end", campaign_end, name="campaign_end"),
    path("advertiser/campaigns/<str:campaign_id>/review", campaign_review, name="campaign_review"),
    path("advertiser/points/", points, name="points"),
    path("advertiser/me/", my_account, name="my_account"),
    path("advertiser/me/password", my_password, name="my_password"),
]
