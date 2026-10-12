from django.apps import AppConfig


class AssetsConfig(AppConfig):
    name = "assets"
    label = "assets"  # 고정(설계 R3). 모델이 없다: 파일은 디스크에, 메타데이터는 소유 모듈(campaigns)이 가진다.
