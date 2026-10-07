import io

from django.test import SimpleTestCase, override_settings, tag
from PIL import Image, features

from assets.api import ImageRejected, validate_image
from tests import image_factory as f


class CountingBytesIO(io.BytesIO):
    total = 0

    def read(self, n=-1):
        data = super().read(n)
        self.total += len(data)
        return data


def run(data):
    return validate_image(io.BytesIO(data))


@tag("security")
class ValidationTests(SimpleTestCase):
    def assertRejected(self, data, reason):
        with self.assertRaises(ImageRejected) as cm:
            run(data)
        self.assertEqual(cm.exception.reason, reason)

    def test_accepts_valid_png_and_jpeg(self):
        png = run(f.png_bytes(40, 30))
        self.assertEqual((png.content_type, png.ext, png.width, png.height), ("image/png", "png", 40, 30))
        jpg = run(f.jpeg_bytes(50, 20))
        self.assertEqual((jpg.content_type, jpg.ext, jpg.width, jpg.height), ("image/jpeg", "jpg", 50, 20))
        self.assertEqual(Image.open(io.BytesIO(png.data)).format, "PNG")
        self.assertEqual(Image.open(io.BytesIO(jpg.data)).format, "JPEG")

    def test_accepts_png_with_alpha_and_palette(self):
        self.assertEqual(run(f.png_bytes(mode="RGBA", color=(1, 2, 3, 128))).ext, "png")
        self.assertEqual(run(f.png_bytes(mode="L", color=100)).ext, "png")

    def test_format_decided_by_content_not_extension(self):
        # PNG 내용을 .jpg 이름·image/jpeg 로 올려도 PNG 로 저장된다(업로드 이름은 검증 함수에 전달되지도 않는다)
        self.assertEqual(run(f.png_bytes()).ext, "png")
        self.assertEqual(run(f.jpeg_bytes()).ext, "jpg")

    def test_rejects_svg_gif_webp_bmp(self):
        self.assertRejected(f.SVG_WITH_SCRIPT, "unsupported_format")
        for fmt in ("GIF", "BMP", "TIFF", "ICO"):
            self.assertRejected(f.other_format_bytes(fmt), "unsupported_format")
        if features.check("webp"):
            self.assertRejected(f.other_format_bytes("WEBP"), "unsupported_format")

    def test_rejects_text_file_renamed_to_png(self):
        self.assertRejected(b"hello world, definitely not an image", "unsupported_format")
        self.assertRejected(b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, "corrupt")  # 서명만 PNG

    def test_rejects_html_and_executable_disguised(self):
        self.assertRejected(b"<html><script>alert(1)</script></html>", "unsupported_format")
        self.assertRejected(b"MZ\x90\x00" + b"\x00" * 100, "unsupported_format")  # 실행 파일 서명

    @override_settings(ASSET_MAX_BYTES=1000)
    def test_rejects_over_size_without_reading_all(self):
        data = CountingBytesIO(f.png_bytes(300, 300, color=(1, 2, 3)) + b"\x00" * 200_000)
        with self.assertRaises(ImageRejected) as cm:
            validate_image(data)
        self.assertEqual(cm.exception.reason, "too_large")
        self.assertEqual(data.total, 1001)  # 한도 + 1 바이트까지만 읽었다

    def test_rejects_decompression_bomb(self):
        self.assertRejected(f.crafted_png_header(5000, 5000), "too_many_pixels")  # 25M > 16M
        self.assertRejected(f.crafted_png_header(40000, 40000), "too_many_pixels")  # Pillow 자체 한도도 넘는다

    @override_settings(ASSET_MAX_PIXELS=1000)
    def test_pixel_limit_is_configurable(self):
        self.assertRejected(f.png_bytes(40, 40), "too_many_pixels")
        self.assertEqual(run(f.png_bytes(30, 30)).width, 30)

    def test_rejects_animated_images(self):
        self.assertRejected(f.apng_bytes(), "animated")
        self.assertRejected(f.other_format_bytes("GIF"), "unsupported_format")

    def test_rejects_truncated_or_corrupt_image(self):
        png = f.png_bytes(64, 64)
        self.assertRejected(png[: len(png) // 2], "corrupt")
        jpg = f.jpeg_bytes(64, 64)
        self.assertRejected(jpg[: len(jpg) // 2], "corrupt")
        self.assertRejected(b"", "corrupt")

    def test_reencode_strips_exif(self):
        original = f.jpeg_bytes(make="SecretCamera 9000")
        self.assertIn(b"SecretCamera", original)
        out = run(original)
        self.assertNotIn(b"SecretCamera", out.data)
        self.assertEqual(len(Image.open(io.BytesIO(out.data)).getexif()), 0)

    def test_reencode_strips_png_text_chunks(self):
        original = f.png_bytes(secret_text="hidden-gps-data")
        self.assertIn(b"hidden-gps-data", original)
        out = run(original)
        self.assertNotIn(b"hidden-gps-data", out.data)
        self.assertNotIn("secret", Image.open(io.BytesIO(out.data)).info)

    def test_exif_orientation_is_applied_before_stripping(self):
        out = run(f.jpeg_bytes(40, 20, orientation=6))  # 90도 회전 표시가 있는 40x20
        self.assertEqual((out.width, out.height), (20, 40))
        self.assertEqual(len(Image.open(io.BytesIO(out.data)).getexif()), 0)

    def test_name_is_sha256_of_stored_bytes(self):
        import hashlib

        out = run(f.png_bytes())
        self.assertEqual(out.sha256, hashlib.sha256(out.data).hexdigest())
        self.assertEqual(out.name, f"{out.sha256}.png")

    def test_reencode_lowers_jpeg_quality_to_fit_limit(self):
        decoded = Image.open(io.BytesIO(f.jpeg_of(f.noise_image(), 20))).convert("RGB")
        sizes = {q: len(f.jpeg_of(decoded, q)) for q in (90, 85, 80, 70, 60, 50)}
        upload = f.jpeg_of(f.noise_image(), 20)
        limit = max(sizes[80] + 10, len(upload))
        with override_settings(ASSET_MAX_BYTES=limit):
            out = run(upload)
        self.assertLessEqual(len(out.data), limit)

    def test_rejects_when_reencoded_result_exceeds_limit(self):
        upload = f.jpeg_of(f.noise_image(), 10)
        with override_settings(ASSET_MAX_BYTES=len(upload) + 1):
            self.assertRejected(upload, "too_large")
