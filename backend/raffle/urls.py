from django.urls import path

from . import views

app_name = "raffle"
urlpatterns = [path("winner-contact/", views.update_winner_contact, name="winner-contact-update"),
               path("winner-contact/qr/", views.winner_contact_preview, name="winner-contact-preview"),
               path("winner-contact/qr/<uuid:event_id>/", views.winner_contact_qr, name="winner-contact-qr"),
               path("", views.state, name="state"), path("control/", views.control, name="control"),
               path("survey/connect/", views.connect_survey, name="connect-survey"),
               path("survey/script/", views.survey_script, name="survey-script")]
