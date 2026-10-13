from django.urls import path

from . import views

app_name = "eventing"
urlpatterns = [
    path("content/<slug:content_code>/open/", views.open_content, name="content-open"),
]