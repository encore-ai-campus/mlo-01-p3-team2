from django.apps import AppConfig


class CampaignsConfig(AppConfig):
    name = "campaigns"
    label = "campaigns"  # 고정(설계 R3)
    default_auto_field = "django.db.models.BigAutoField"
