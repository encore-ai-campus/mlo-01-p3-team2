"""게임 DB에 광고 발급·노출 기록을 보관하는 선택적 Django 앱."""

from django.apps import AppConfig


class AdBridgeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ad_bridge"
    verbose_name = "광고 연동 기록"
