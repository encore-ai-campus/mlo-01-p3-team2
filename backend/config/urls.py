from django.urls import include, path
from learning.views import learning_page

urlpatterns = [
    path("api/messages/", include("direct_messages.urls")),
    path("api/ads/", include("ad_bridge.game.urls")),
    path("api/accounts/", include("accounts.urls", namespace="accounts-api")),
    path("api/learning/", include("learning.urls")),
    path("learning/", learning_page, name="learning-home"),
    path("accounts/", include("accounts.urls")),
    path("api/community/", include("community.urls")),
    path("", include("eventing.urls")),
    path("api/raffle/", include("raffle.urls")),
    path("", include("campus.urls")),
]
