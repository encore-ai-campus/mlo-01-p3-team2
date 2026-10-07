import hashlib
import os
import stat
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadhandler import StopUpload
from django.test import SimpleTestCase, override_settings, tag

from assets.api import asset_url, store, validate_image
from assets.storage import LocalFileStorage
from assets.uploads import OVERHEAD, MaxUploadSizeHandler
from tests import image_factory as f

GOOD = "ab" + "c" * 62 + ".png"


@tag("security")
class StorageTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.storage = LocalFileStorage(self.root)

    def test_name_is_content_hash_and_independent_of_upload_name(self):
        raw = f.png_bytes()
        image = validate_image(__import__("io").BytesIO(raw))
        name = store(image)
        stored = Path(__import__("django.conf", fromlist=["settings"]).settings.MEDIA_ROOT) / name[:2] / name
        self.assertEqual(name, hashlib.sha256(stored.read_bytes()).hexdigest() + ".png")

    def test_same_content_same_file(self):
        self.storage.put(GOOD, b"data")
        path = self.root / "ab" / GOOD
        mtime = path.stat().st_mtime_ns
        self.storage.put(GOOD, b"data")
        self.assertEqual(path.stat().st_mtime_ns, mtime)  # 다시 쓰지 않는다
        self.assertEqual(len(list((self.root / "ab").iterdir())), 1)

    def test_sharded_directory_and_permissions(self):
        self.storage.put(GOOD, b"data")
        path = self.root / GOOD[:2] / GOOD
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_atomic_write_leaves_no_partial_file(self):
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.storage.put(GOOD, b"data")
        shard = self.root / GOOD[:2]
        self.assertFalse((shard / GOOD).exists())
        self.assertEqual(list(shard.iterdir()), [])  # 임시 파일도 남지 않는다
        self.assertFalse(self.storage.exists(GOOD))

    def test_invalid_names_are_rejected(self):
        bad = ["../x.png", "abc.png", GOOD.upper(), GOOD[:-4] + ".gif", GOOD + ".png", "", "a/b.png",
               GOOD.replace("a", "g", 1), "..%2f" + GOOD, GOOD + "\x00"]
        for name in bad:
            with self.assertRaises(ValueError, msg=name):
                self.storage.put(name, b"x")
            with self.assertRaises(ValueError, msg=name):
                self.storage.open(name)
            self.assertFalse(self.storage.exists(name), name)

    def test_open_returns_stored_bytes(self):
        self.storage.put(GOOD, b"payload")
        with self.storage.open(GOOD) as fh:
            self.assertEqual(fh.read(), b"payload")

    def test_asset_url_uses_public_base_url(self):
        self.assertEqual(asset_url(GOOD), f"http://testserver/assets/{GOOD}")
        with override_settings(ASSET_PUBLIC_BASE_URL="https://ads.example.com/"):
            self.assertEqual(asset_url(GOOD), f"https://ads.example.com/assets/{GOOD}")


@tag("security")
class UploadGuardTests(SimpleTestCase):
    def test_handler_is_first_in_chain(self):
        from django.conf import settings

        self.assertEqual(settings.FILE_UPLOAD_HANDLERS[0], "assets.uploads.MaxUploadSizeHandler")

    @override_settings(ASSET_MAX_BYTES=1000)
    def test_oversized_upload_is_stopped_before_spooling_to_disk(self):
        handler = MaxUploadSizeHandler(None)
        self.assertIsNone(handler.handle_raw_input(None, {}, 1000 + OVERHEAD, b"x"))  # 한도 이내
        with self.assertRaises(StopUpload):
            handler.handle_raw_input(None, {}, 1000 + OVERHEAD + 1, b"x")
        self.assertIsNone(handler.handle_raw_input(None, {}, None, b"x"))  # 길이를 모르면 통과(검증 단계가 막는다)
