from django.urls import include, path

urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("api/community/", include("community.urls")),
    path("", include("eventing.urls")),
    path("api/raffle/", include("raffle.urls")),
    path("", include("campus.urls")),
]
