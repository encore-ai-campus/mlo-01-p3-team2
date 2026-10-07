"""C3(`GET /assets/{asset_name}`) provider 계약 테스트: **실제 서버 응답**을 계약에 대조한다(상태·헤더·미디어 타입)."""
import io

from django.test import Client, TestCase, override_settings, tag

from assets.api import store, validate_image
from tests import image_factory
from tests.contract_support import Contract, ProviderContractMixin

PATH = "/assets/{asset_name}"


@tag("security")
class AssetProviderContractTests(ProviderContractMixin, TestCase):
    contract = Contract("serving")

    def setUp(self):
        for fmt, maker in (("png", image_factory.png_bytes), ("jpg", image_factory.jpeg_bytes)):
            image = validate_image(io.BytesIO(maker()))
            store(image)
            setattr(self, fmt, image)

    def test_png_and_jpeg_responses_match_the_contract(self):
        for image in (self.png, self.jpg):
            response = Client().get(f"/assets/{image.name}")
            self.assertEqual(response.status_code, 200)
            self.assertContract(self.contract, PATH, "get", response)
            self.assertEqual(response["Content-Type"], image.content_type)
            self.assertEqual(response["ETag"].strip('"'), image.sha256)  # ETag = 내용 해시

    def test_conditional_request_gets_304_with_cache_headers(self):
        first = Client().get(f"/assets/{self.png.name}")
        second = Client().get(f"/assets/{self.png.name}", HTTP_IF_NONE_MATCH=first["ETag"])
        self.assertEqual(second.status_code, 304)
        self.assertContract(self.contract, PATH, "get", second)

    def test_unknown_or_unservable_name_is_404_as_documented(self):
        missing = "0" * 64 + ".png"
        response = Client().get(f"/assets/{missing}")
        self.assertEqual(response.status_code, 404)
        self.assertContract(self.contract, PATH, "get", response)
        with override_settings(ASSET_SERVABLE_CHECK="tests.test_contract_provider_assets.never"):
            blocked = Client().get(f"/assets/{self.png.name}")
        self.assertEqual(blocked.status_code, 404)
        self.assertContract(self.contract, PATH, "get", blocked)

    def test_no_cookie_is_set_and_no_auth_is_required(self):
        response = Client().get(f"/assets/{self.png.name}")
        self.assertNotIn("Set-Cookie", response.headers)  # 세션·CSRF 쿠키를 만들지 않는다


def never(name):
    return False
