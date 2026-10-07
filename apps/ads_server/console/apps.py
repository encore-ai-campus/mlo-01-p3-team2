from django.apps import AppConfig


class ConsoleConfig(AppConfig):
    name = "console"
    label = "console"  # 고정(설계 R3)
    default_auto_field = "django.db.models.BigAutoField"
