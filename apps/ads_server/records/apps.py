from django.apps import AppConfig


class RecordsConfig(AppConfig):
    name = "records"
    label = "records"  # 고정(설계 R3)
    default_auto_field = "django.db.models.BigAutoField"
