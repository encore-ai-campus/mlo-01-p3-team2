"""백엔드와 같은 경로·URL 이름(설계 §6.6 "6-15 분리"). 템플릿의 `{% url %}` 과 현재 메뉴 표시(`resolver_match`)가 프론트에서도 그대로 동작하게 한다.
**데이터만 둔다** — 백엔드 시험(`case_frontend_routes_match_the_backend`)이 이 파일을 읽어 백엔드의 경로와 같은지 본다. 모든 경로는 같은 뷰가 받는다(`ui.views.display`)."""

CONSOLE = [  # 백엔드 console/urls.py
    ("", "root"),
    ("accounts/signup/", "signup"),
    ("accounts/login/", "login"),
    ("accounts/logout/", "logout"),
    ("advertiser/", "advertiser_home"),
    ("advertiser/ads/new/", "ad_create"),
    ("advertiser/ad-groups/<str:ad_group_id>/", "ad_group_detail"),
    ("advertiser/ad-groups/<str:ad_group_id>/bid", "ad_group_bid"),
    ("advertiser/ad-groups/<str:ad_group_id>/name", "ad_group_name"),
    ("advertiser/ad-groups/<str:ad_group_id>/slots", "ad_group_slots"),
    ("advertiser/ad-groups/<str:ad_group_id>/enabled", "ad_group_enabled"),
    ("advertiser/ad-groups/<str:ad_group_id>/creatives", "ad_group_creative_upload"),
    ("advertiser/ad-groups/<str:ad_group_id>/creatives/select", "ad_group_creative_select"),
    ("advertiser/creatives/", "creative_list"),
    ("advertiser/creatives/<str:creative_id>/", "creative_detail"),
    ("advertiser/creatives/<str:creative_id>/archive", "creative_archive"),
    ("advertiser/creatives/<str:creative_id>/edit", "creative_edit"),
    ("advertiser/creatives/<str:creative_id>/image", "creative_image"),
    ("advertiser/creatives/<str:creative_id>/image-file", "creative_image_file"),
    ("advertiser/campaigns/", "campaign_list"),
    ("advertiser/campaigns/new/", "campaign_create"),
    ("advertiser/campaigns/<str:campaign_id>/", "campaign_detail"),
    ("advertiser/campaigns/<str:campaign_id>/status", "campaign_status"),
    ("advertiser/campaigns/<str:campaign_id>/end", "campaign_end"),
    ("advertiser/campaigns/<str:campaign_id>/review", "campaign_review"),
    ("advertiser/points/", "points"),
    ("advertiser/me/", "my_account"),
    ("advertiser/me/password", "my_password"),
]

OPERATOR = [  # 백엔드 console/operator/urls.py — 관리 사이트 경로 + "operator/" 아래, 이름공간 operator
    ("media/", "media_list"),
    ("media/<str:media_id>/", "media_detail"),
    ("media/<str:media_id>/active", "media_active"),
    ("media/<str:media_id>/slots", "slot_create"),
    ("media/<str:media_id>/keys/issue", "key_issue"),
    ("media/<str:media_id>/keys/rotate", "key_rotate"),
    ("slots/<str:slot_id>/active", "slot_active"),
    ("slots/<str:slot_id>/policy", "slot_policy"),
    ("policies/", "policy_bulk"),
    ("keys/<str:key_id>/revoke", "key_revoke"),
    ("campaigns/", "campaign_monitor"),
    ("campaigns/<str:campaign_id>/suspend", "campaign_suspend"),
    ("campaigns/<str:campaign_id>/release", "campaign_release"),
    ("reviews/", "review_queue"),
    ("reviews/<str:review_request_id>/reject", "review_reject"),
    ("advertisers/", "advertiser_list"),
    ("advertisers/<str:user_id>/", "advertiser_detail"),
    ("advertisers/<str:user_id>/active", "advertiser_active"),
    ("advertisers/<str:user_id>/adjust", "advertiser_adjust"),
    ("assets/<str:name>", "asset"),
]

ADMIN = [  # Django admin(관리 사이트 경로 아래, 이름공간 admin) 중 관리 템플릿과 운영 화면이 거는 것만. 화면은 백엔드가 그리고 프론트는 통과시킨다
    ("", "index"),
    ("logout/", "logout"),
    ("password_change/", "password_change"),
    ("foundation/user/<id>/password/", "auth_user_password_change"),  # 운영 화면 광고주 상세의 '비밀번호 초기화'(Django UserAdmin 이 모델과 상관없이 이 이름을 쓴다)
]
