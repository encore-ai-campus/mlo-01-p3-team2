from django.urls import path, register_converter

from .views import serve_asset


class AssetNameConverter:
    """`<64자 hex>.jpg|png` 만 매칭한다. `..`·인코딩된 경로 조작은 라우팅 단계에서 404 가 된다."""

    regex = r"[0-9a-f]{64}\.(?:jpg|png)"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(AssetNameConverter, "asset_name")

urlpatterns = [
    path("assets/<asset_name:name>", serve_asset, name="asset"),
]
