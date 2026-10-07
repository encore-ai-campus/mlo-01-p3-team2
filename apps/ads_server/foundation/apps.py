from django.apps import AppConfig


class FoundationConfig(AppConfig):
    name = "foundation"
    label = "foundation"  # 고정: 폴더·패키지를 옮겨도 마이그레이션과 FK 가 깨지지 않게(설계 R3)
    default_auto_field = "django.db.models.BigAutoField"
