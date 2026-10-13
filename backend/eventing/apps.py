from django.apps import AppConfig


class EventingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "eventing"
    verbose_name = "Raw event pipeline"