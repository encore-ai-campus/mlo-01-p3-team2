from django.urls import path

from .views import CampusLoginView, CampusLogoutView, SignUpView, nickname_view, profile_setup_view

app_name = "accounts"
urlpatterns = [
    path("login/", CampusLoginView.as_view(), name="login"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("setup/", profile_setup_view, name="setup"),
    path("nickname/", nickname_view, name="nickname"),
    path("logout/", CampusLogoutView.as_view(), name="logout"),
]
