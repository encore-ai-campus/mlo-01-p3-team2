from django.urls import path

from . import views

app_name = "raffle"
urlpatterns = [path("", views.state, name="state"), path("control/", views.control, name="control")]
