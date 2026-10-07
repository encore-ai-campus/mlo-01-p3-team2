import io

from django.test import Client, TestCase, override_settings, tag
from django.urls import reverse

from assets.api import store, validate_image
from foundation.models import User
from tests import image_factory as f

PW = "Tr0ub4dor-horse-staple"


def make_asset(raw):
    image = validate_image(io.BytesIO(raw))
    return image, store(image)


@tag("security")
class ServingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.png, cls.png_name = make_asset(f.png_bytes(20, 20))
        cls.jpg, cls.jpg_name = make_asset(f.jpeg_bytes(20, 20))

    def url(self, name):
        return reverse("asset", kwargs={"name": name})

    def test_serves_with_fixed_content_type_and_nosniff(self):
        r = self.client.get(self.url(self.png_name))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(b"".join(r.streaming_content), self.png.data)
        self.assertEqual(self.client.get(self.url(self.jpg_name))["Content-Type"], "image/jpeg")

    def test_etag_and_304(self):
        etag = f'"{self.png.sha256}"'
        r = self.client.get(self.url(self.png_name))
        self.assertEqual(r["ETag"], etag)
        self.assertEqual(self.client.get(self.url(self.png_name), HTTP_IF_NONE_MATCH=etag).status_code, 304)
        self.assertEqual(self.client.get(self.url(self.png_name), HTTP_IF_NONE_MATCH="W/" + etag).status_code, 304)
        self.assertEqual(self.client.get(self.url(self.png_name), HTTP_IF_NONE_MATCH="*").status_code, 304)
        self.assertEqual(self.client.get(self.url(self.png_name), HTTP_IF_NONE_MATCH='"other"').status_code, 200)

    def test_cache_control_no_cache_on_200_and_304(self):
        etag = f'"{self.png.sha256}"'
        self.assertEqual(self.client.get(self.url(self.png_name))["Cache-Control"], "no-cache")
        r304 = self.client.get(self.url(self.png_name), HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(r304["Cache-Control"], "no-cache")

    def test_no_set_cookie_header(self):
        r = self.client.get(self.url(self.png_name))
        self.assertNotIn("Set-Cookie", r.headers)
        self.assertNotIn("Cookie", r.get("Vary", ""))
        User.objects.create_user("img_user", PW, nickname="i", class_label="1")
        self.client.post(reverse("login"), {"username": "img_user", "password": PW})  # 세션이 있는 클라이언트도
        r = self.client.get(self.url(self.png_name))
        self.assertNotIn("Set-Cookie", r.headers)

    def test_cross_origin_resource_policy_header(self):
        self.assertEqual(self.client.get(self.url(self.png_name))["Cross-Origin-Resource-Policy"], "cross-origin")

    def test_path_traversal_returns_404(self):
        absent = "a" * 64 + ".png"
        paths = [
            "/assets/../../etc/passwd", "/assets/..%2f..%2fetc%2fpasswd", "/assets/%2e%2e/%2e%2e/etc/passwd",
            "/assets/%2e%2e%2f%2e%2e%2fetc%2fpasswd", f"/assets/{absent}", f"/assets/{'A' * 64}.png",
            f"/assets/{self.png.sha256}.gif", f"/assets/{self.png.sha256}.PNG", f"/assets/{self.png.sha256}.png/",
            f"/assets/{self.png.sha256}.png%00.jpg", f"/assets/{self.png.sha256}", "/assets/", "/assets/x",
            f"/assets//{self.png.sha256}.png",
        ]
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_extension_must_match_stored_content_name(self):
        # 같은 해시에 다른 확장자를 붙여도 저장된 파일이 없으므로 404 (내용을 다른 형식으로 위장해 받을 수 없다)
        self.assertEqual(self.client.get(f"/assets/{self.png.sha256}.jpg").status_code, 404)

    @override_settings(ASSET_SERVABLE_CHECK="tests.support_app.checks.deny_all")
    def test_servable_check_false_returns_404(self):
        etag = f'"{self.png.sha256}"'
        self.assertEqual(self.client.get(self.url(self.png_name)).status_code, 404)
        self.assertEqual(self.client.get(self.url(self.png_name), HTTP_IF_NONE_MATCH=etag).status_code, 404)  # 304 로 새지 않는다

    @override_settings(ASSET_SERVABLE_CHECK="tests.support_app.checks.allow_all")
    def test_servable_check_true_serves(self):
        self.assertEqual(self.client.get(self.url(self.png_name)).status_code, 200)

    def test_not_found_responses_are_not_cacheable(self):
        r = self.client.get("/assets/" + "b" * 64 + ".png")
        self.assertEqual(r.status_code, 404)
        self.assertIn("no-store", r["Cache-Control"])

    def test_only_get_and_head(self):
        self.assertEqual(self.client.head(self.url(self.png_name)).status_code, 200)
        self.assertEqual(self.client.post(self.url(self.png_name)).status_code, 405)
        self.assertEqual(Client().delete(self.url(self.png_name)).status_code, 405)

    def test_public_without_login(self):
        self.assertEqual(Client().get(self.url(self.png_name)).status_code, 200)
