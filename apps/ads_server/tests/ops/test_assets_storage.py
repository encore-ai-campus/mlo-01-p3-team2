import hashlib
import os
import stat
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings, tag
from django.urls import reverse

from assets.api import asset_url, store, validate_image
from assets.storage import LocalFileStorage
from foundation.middleware import REQUEST_BODY_OVERHEAD
from tests.support import image_factory as f
from tests.support.cases import Cases

GOOD = "ab" + "c" * 62 + ".png"


@tag("security")
class StorageTests(Cases, SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.storage = LocalFileStorage(self.root)

    def case_name_is_content_hash_and_independent_of_upload_name(self):
        raw = f.png_bytes()
        image = validate_image(__import__("io").BytesIO(raw))
        name = store(image)
        stored = Path(__import__("django.conf", fromlist=["settings"]).settings.MEDIA_ROOT) / name[:2] / name
        self.assertEqual(name, hashlib.sha256(stored.read_bytes()).hexdigest() + ".png")

    def case_same_content_same_file(self):
        self.storage.put(GOOD, b"data")
        path = self.root / "ab" / GOOD
        mtime = path.stat().st_mtime_ns
        self.storage.put(GOOD, b"data")
        self.assertEqual(path.stat().st_mtime_ns, mtime)  # 다시 쓰지 않는다
        self.assertEqual(len(list((self.root / "ab").iterdir())), 1)

    def case_sharded_directory_and_permissions(self):
        self.storage.put(GOOD, b"data")
        path = self.root / GOOD[:2] / GOOD
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def case_atomic_write_leaves_no_partial_file(self):
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.storage.put(GOOD, b"data")
        shard = self.root / GOOD[:2]
        self.assertFalse((shard / GOOD).exists())
        self.assertEqual(list(shard.iterdir()), [])  # 임시 파일도 남지 않는다
        self.assertFalse(self.storage.exists(GOOD))

    def case_invalid_names_are_rejected(self):
        bad = ["../x.png", "abc.png", GOOD.upper(), GOOD[:-4] + ".gif", GOOD + ".png", "", "a/b.png",
               GOOD.replace("a", "g", 1), "..%2f" + GOOD, GOOD + "\x00"]
        for name in bad:
            with self.assertRaises(ValueError, msg=name):
                self.storage.put(name, b"x")
            with self.assertRaises(ValueError, msg=name):
                self.storage.open(name)
            self.assertFalse(self.storage.exists(name), name)

    def case_open_returns_stored_bytes(self):
        self.storage.put(GOOD, b"payload")
        with self.storage.open(GOOD) as fh:
            self.assertEqual(fh.read(), b"payload")

    def case_asset_url_uses_public_base_url(self):
        self.assertEqual(asset_url(GOOD), f"http://testserver/assets/{GOOD}")
        with override_settings(ASSET_PUBLIC_BASE_URL="https://ads.example.com/"):
            self.assertEqual(asset_url(GOOD), f"https://ads.example.com/assets/{GOOD}")

    def test_storage(self):
        self.run_cases()


@tag("security")
class UploadGuardTests(Cases, TestCase):
    """업로드 전체 크기 가드(위협 T16). CSRF 가 본문을 읽기 전에 413 으로 끊고, 임시 파일을 만들지 않는다."""

    LIMIT = 1000

    def post_multipart(self, size, enforce_csrf, path=None):
        client = Client(enforce_csrf_checks=enforce_csrf)
        upload = SimpleUploadedFile("big.png", b"\x89PNG" + b"x" * size, content_type="image/png")
        return client.post(path or reverse("signup"), {"username": "a", "image": upload})

    def case_oversized_multipart_is_413_with_and_without_csrf_and_leaves_no_temp_files(self):
        """화면 경로는 읽을 수 있는 HTML 오류 화면(Step 3-2c — 광고 만들기의 큰 이미지), API 경로는 problem+json(다른 오류 응답과 같은 규약)."""
        with tempfile.TemporaryDirectory() as tmp, override_settings(ASSET_MAX_BYTES=self.LIMIT, FILE_UPLOAD_TEMP_DIR=tmp):
            for enforce_csrf in (True, False):
                response = self.post_multipart(self.LIMIT + REQUEST_BODY_OVERHEAD + 100, enforce_csrf)
                self.assertEqual(response.status_code, 413, enforce_csrf)
                self.assertIn("text/html", response["Content-Type"])
                self.assertIn("X-Request-ID", response)
                response = self.post_multipart(self.LIMIT + REQUEST_BODY_OVERHEAD + 100, enforce_csrf, path="/api/media/v1/decisions")
                self.assertEqual(response.status_code, 413, enforce_csrf)
                self.assertEqual(response["Content-Type"], "application/problem+json")
                self.assertEqual(response.json()["code"], "payload_too_large")
                self.assertIn("X-Request-ID", response)
            self.assertEqual(os.listdir(tmp), [])

    def case_declared_content_length_over_limit_is_413_without_reading_the_body(self):
        with override_settings(ASSET_MAX_BYTES=self.LIMIT):
            response = Client().post(
                reverse("signup"), data=b"tiny", content_type="multipart/form-data; boundary=x",
                CONTENT_LENGTH=str(self.LIMIT + REQUEST_BODY_OVERHEAD + 1),
            )
        self.assertEqual(response.status_code, 413)

    def case_body_within_limit_reaches_the_view(self):
        with override_settings(ASSET_MAX_BYTES=self.LIMIT):
            response = self.post_multipart(10, enforce_csrf=False)
        self.assertNotEqual(response.status_code, 413)
        self.assertLess(response.status_code, 500)

    def case_guard_runs_before_the_csrf_middleware(self):
        from django.conf import settings

        names = settings.MIDDLEWARE
        self.assertLess(
            names.index("foundation.middleware.RequestBodyLimitMiddleware"), names.index("django.middleware.csrf.CsrfViewMiddleware")
        )

    def test_upload_guard(self):
        self.run_cases()
