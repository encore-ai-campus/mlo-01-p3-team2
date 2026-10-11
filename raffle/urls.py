from django.urls import path

from . import views

app_name = "raffle"
urlpatterns = [path("", views.state, name="state"), path("control/", views.control, name="control"),
               path("survey/connect/", views.connect_survey, name="connect-survey"),
               path("survey/script/", views.survey_script, name="survey-script")]
