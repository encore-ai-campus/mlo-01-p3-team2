from django.urls import path, register_converter
from django.urls.converters import StringConverter

from .storage import NAME_RE
from .views import serve_asset


class AssetNameConverter(StringConverter):
    """`<64자 hex>.jpg|png` 만 매칭한다. `..`·인코딩된 경로 조작은 라우팅 단계에서 404 가 된다."""

    regex = NAME_RE.pattern  # 저장소와 같은 이름 규칙


register_converter(AssetNameConverter, "asset_name")

urlpatterns = [
    path("assets/<asset_name:name>", serve_asset, name="asset"),
]
