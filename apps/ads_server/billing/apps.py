from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = "billing"
    label = "billing"  # 고정(설계 R3)
    default_auto_field = "django.db.models.BigAutoField"
