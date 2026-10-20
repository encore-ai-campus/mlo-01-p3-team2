from django.urls import path

from . import views, lunch

app_name = "campus"
urlpatterns = [
    path("api/campus/lunch/spin/", lunch.spin, name="lunch-spin"),
    path("", views.map_view, name="map"),
    path("api/board/menu/", views.menu_photo, name="menu-photo"),
    path("api/board/menu/images/<str:filename>/", views.menu_image, name="menu-image"),
]
