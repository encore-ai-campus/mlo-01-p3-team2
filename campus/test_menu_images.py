from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.apps import apps
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from . import menu_images as menus
from .menu_updater import updater_loop

PHOTO_URL = "https://k.kakaocdn.net/dn/menu/channel/photo/img_xl.jpg"
HTML = b'<meta property="og:image" content="https://k.kakaocdn.net/dn/menu/channel/photo/img_m.jpg">'
SEOUL = ZoneInfo("Asia/Seoul")
AT_TEN = datetime(2026, 10, 6, 10, 0, tzinfo=SEOUL)


def png(color="green", size=(2, 2)):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


class MenuStorageTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        config = override_settings(BOARD_MENU_STORAGE_ROOT=self.root,
                                   BOARD_MENU_UPDATE_TIME="10:00", BOARD_MENU_TIME_ZONE="Asia/Seoul")
        config.enable()
        self.addCleanup(config.disable)

    def save_photo(self, *, now=AT_TEN, color="green"):
        photo = png(color)
        with patch.object(menus, "download", side_effect=[HTML, photo]) as fetch:
            metadata = menus.refresh_menu(force=True, now=now)
        return photo, metadata, fetch

    def test_current_profile_resolves_to_full_photo_and_stores_original_bytes(self):
        photo, metadata, fetch = self.save_photo()
        self.assertEqual(fetch.call_args_list[1].args[0], PHOTO_URL)
        self.assertEqual(metadata["width"], 2)
        self.assertEqual(metadata["content_type"], "image/png")
        self.assertEqual((self.root / metadata["filename"]).read_bytes(), photo)
        self.assertEqual(menus.latest_menu(), metadata)
        self.assertFalse(list(self.root.glob("*.tmp")))
        self.assertFalse((self.root / "refresh.lock").exists())

    def test_ten_am_and_catch_up_follow_korean_time(self):
        yesterday = {"updated_at": datetime(2026, 10, 5, 10, 0, tzinfo=SEOUL).isoformat()}
        self.assertFalse(menus.refresh_due(AT_TEN.replace(hour=9, minute=59), yesterday))
        self.assertTrue(menus.refresh_due(AT_TEN, yesterday))
        self.assertTrue(menus.refresh_due(AT_TEN.replace(hour=14), yesterday))
        self.assertFalse(menus.refresh_due(AT_TEN, {"updated_at": AT_TEN.isoformat()}))
        self.assertTrue(menus.refresh_due(datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc), yesterday))

    def test_manual_refresh_before_ten_does_not_cancel_the_scheduled_refresh(self):
        self.save_photo(now=AT_TEN.replace(hour=9))
        self.assertTrue(menus.refresh_due(AT_TEN))
        with patch.object(menus, "download", side_effect=[HTML, png("blue")]):
            menus.refresh_menu(now=AT_TEN)
        with patch.object(menus, "download") as fetch:
            self.assertIsNone(menus.refresh_menu(now=AT_TEN.replace(hour=12)))
            fetch.assert_not_called()
        self.assertTrue(menus.refresh_due(AT_TEN.replace(day=7)))

    def test_failures_preserve_last_successful_photo_and_timestamp(self):
        _, previous, _ = self.save_photo()
        for responses in ([HTML, b"<html>Not a photo</html>"], [b"<html>No profile</html>"]):
            with patch.object(menus, "download", side_effect=responses):
                with self.assertRaises(menus.MenuImageError):
                    menus.refresh_menu(force=True, now=AT_TEN.replace(day=7))
            self.assertEqual(menus.latest_menu(), previous)
        with patch.object(menus, "download", side_effect=menus.MenuImageError("Network offline")):
            with self.assertRaises(menus.MenuImageError):
                menus.refresh_menu(force=True, now=AT_TEN.replace(day=7))
        self.assertEqual(menus.latest_menu(), previous)
        self.assertFalse((self.root / "refresh.lock").exists())

    def test_readers_keep_the_old_photo_until_the_new_manifest_is_published(self):
        _, previous, _ = self.save_photo()
        real_write = menus.atomic_write
        seen = []

        def delayed_publish(path, data):
            if path.name == "latest.json":
                seen.append(menus.latest_menu())
            real_write(path, data)

        with patch.object(menus, "download", side_effect=[HTML, png("blue")]), patch.object(menus, "atomic_write", side_effect=delayed_publish):
            current = menus.refresh_menu(force=True, now=AT_TEN.replace(day=7))
        self.assertEqual(seen, [previous])
        self.assertEqual(menus.latest_menu(), current)
        self.assertTrue((self.root / previous["filename"]).exists())

    def test_a_concurrent_refresh_is_skipped_and_crashed_lock_can_recover(self):
        with menus.refresh_lock() as acquired:
            self.assertTrue(acquired)
            with patch.object(menus, "download") as fetch:
                self.assertIsNone(menus.refresh_menu(force=True, now=AT_TEN))
                fetch.assert_not_called()
        lock = self.root / "refresh.lock"
        lock.write_text("old process", encoding="ascii")
        os.utime(lock, (time.time() - 301, time.time() - 301))
        self.save_photo()
        self.assertFalse(lock.exists())

    def test_downloads_and_redirects_are_limited_to_the_channel_and_cdn(self):
        for url in ("http://pf.kakao.com/_xfWxfCxj", "https://127.0.0.1/photo", "file:///photo",
                    "https://pf.kakao.com.example/photo", "https://user:secret@pf.kakao.com/photo"):
            with self.assertRaises(menus.MenuImageError):
                menus.validate_url(url)
        with self.assertRaises(menus.MenuImageError):
            menus.ChannelRedirects().redirect_request(None, None, 302, "Redirect", {}, "https://example.com/photo")
        with patch.object(menus, "build_opener") as opener:
            opener.return_value.open.return_value = BytesIO(b"abcd")
            with self.assertRaises(menus.MenuImageError):
                menus.download(PHOTO_URL, 3)

    def test_corrupt_oversized_or_non_raster_photos_are_rejected(self):
        for data in (b"", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', png()[:20]):
            with self.assertRaises(menus.MenuImageError):
                menus.inspect_image(data)
        with patch.object(menus, "MAX_IMAGE_PIXELS", 1):
            with self.assertRaises(menus.MenuImageError):
                menus.inspect_image(png(size=(2, 1)))

    def test_invalid_metadata_cannot_select_arbitrary_files(self):
        (self.root / "outside.txt").write_text("private", encoding="utf-8")
        for value in ({"filename": "outside.txt"}, {"filename": "../outside.txt"}, [], "not a mapping"):
            (self.root / "latest.json").write_text(json.dumps(value), encoding="utf-8")
            self.assertIsNone(menus.latest_menu())

    def test_updater_retries_after_failure_without_exiting(self):
        class StopAfterWait:
            stopped = False
            delay = None
            def is_set(self):
                return self.stopped
            def wait(self, delay):
                self.delay, self.stopped = delay, True

        stop = StopAfterWait()
        with patch("campus.menu_updater.refresh_due", return_value=True), patch("campus.menu_updater.refresh_menu", side_effect=menus.MenuImageError("Offline")), patch("campus.menu_updater.logger"):
            updater_loop(stop)
        self.assertEqual(stop.delay, 300)


class MenuPhotoViewsTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        config = override_settings(BOARD_MENU_STORAGE_ROOT=Path(temporary.name))
        config.enable()
        self.addCleanup(config.disable)
        self.user = get_user_model().objects.create_user(username="menu_reader", password="Menu!Test4912")
        self.client.force_login(self.user)
        self.photo = png()
        with patch.object(menus, "download", side_effect=[HTML, self.photo]):
            self.metadata = menus.refresh_menu(force=True, now=AT_TEN)
        self.image_url = reverse("campus:menu-image", args=[self.metadata["filename"]])

    def test_login_required_for_photo_details_and_image(self):
        anonymous = Client()
        for url in (reverse("campus:menu-photo"), self.image_url):
            self.assertEqual(anonymous.get(url).status_code, 302)

    def test_photo_metadata_and_original_image_are_served_without_stale_cache(self):
        response = self.client.get(reverse("campus:menu-photo"))
        self.assertEqual(response.json()["imageUrl"], self.image_url)
        self.assertEqual(response.json()["updatedAt"], AT_TEN.isoformat())
        self.assertIn("no-store", response["Cache-Control"])
        image = self.client.get(self.image_url)
        try:
            self.assertEqual(b"".join(image.streaming_content), self.photo)
            self.assertEqual(image["Content-Type"], "image/png")
            self.assertIn("no-store", image["Cache-Control"])
        finally:
            image.close()

    def test_unknown_files_and_write_requests_are_rejected(self):
        self.assertEqual(self.client.get(reverse("campus:menu-image", args=["latest.json"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("campus:menu-image", args=["0" * 64 + ".png"])).status_code, 404)
        self.assertEqual(self.client.post(reverse("campus:menu-photo")).status_code, 405)

    def test_missing_photo_has_a_clean_empty_state(self):
        (menus.storage_root() / "latest.json").unlink()
        self.assertEqual(self.client.get(reverse("campus:menu-photo")).json()["imageUrl"], None)


class MenuStartupTests(SimpleTestCase):
    def test_regular_runserver_child_starts_the_updater(self):
        with patch("sys.argv", ["manage.py", "runserver", "8002"]), patch.dict(os.environ, {"RUN_MAIN": "true"}), patch("campus.menu_updater.start_menu_updater") as start:
            apps.get_app_config("campus").ready()
            start.assert_called_once()

    def test_parent_migration_and_test_processes_do_not_start_an_updater(self):
        for args in (["manage.py", "runserver", "8002"], ["manage.py", "migrate"], ["manage.py", "test"]):
            with patch("sys.argv", args), patch.dict(os.environ, {}, clear=True), patch("campus.menu_updater.start_menu_updater") as start:
                apps.get_app_config("campus").ready()
                start.assert_not_called()

    def test_runserver_without_autoreload_also_starts_the_updater(self):
        with patch("sys.argv", ["manage.py", "runserver", "--noreload"]), patch.dict(os.environ, {}, clear=True), patch("campus.menu_updater.start_menu_updater") as start:
            apps.get_app_config("campus").ready()
            start.assert_called_once()
