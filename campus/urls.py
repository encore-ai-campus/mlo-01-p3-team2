from django.urls import path

from . import views

app_name = "campus"
urlpatterns = [
    path("", views.map_view, name="map"),
    path("api/board/menu/", views.menu_photo, name="menu-photo"),
    path("api/board/menu/images/<str:filename>/", views.menu_image, name="menu-image"),
]
