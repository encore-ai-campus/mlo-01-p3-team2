from django.urls import path

from .views import CampusLoginView, CampusLogoutView, SignUpView, nickname_view, profile_setup_view
from . import session_views, guide_views

app_name = "accounts"
urlpatterns = [
    path("guide/complete/", guide_views.complete_guide, name="guide-complete"),
    path("session/status/", session_views.session_status, name="session-status"),
    path("session/activity/", session_views.session_activity, name="session-activity"),
    path("login/", CampusLoginView.as_view(), name="login"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("setup/", profile_setup_view, name="setup"),
    path("nickname/", nickname_view, name="nickname"),
    path("logout/", CampusLogoutView.as_view(), name="logout"),
]
