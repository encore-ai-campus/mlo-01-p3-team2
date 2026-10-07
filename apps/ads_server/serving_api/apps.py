from django.apps import AppConfig


class ServingApiConfig(AppConfig):
    name = "serving_api"
    label = "serving_api"  # 고정(설계 R3). 모델이 없다: 데이터는 아래 층이 소유한다
    default_auto_field = "django.db.models.BigAutoField"
