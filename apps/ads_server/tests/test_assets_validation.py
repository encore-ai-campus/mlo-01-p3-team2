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

    def test_reencode_strips_png_icc_profile_and_other_ancillary_chunks(self):
        original = f.png_bytes(icc=f.icc_profile(), dpi=(300, 300), secret_text="hidden")
        self.assertIn("iCCP", f.png_chunk_types(original))
        out = run(original)
        self.assertNotIn(b"iCCP", out.data)
        self.assertNotIn("icc_profile", Image.open(io.BytesIO(out.data)).info)
        self.assertLessEqual(set(f.png_chunk_types(out.data)), {"IHDR", "PLTE", "tRNS", "IDAT", "IEND"})

    def test_reencode_strips_jpeg_icc_profile(self):
        original = f.jpeg_bytes(icc=f.icc_profile())
        self.assertIn(b"ICC_PROFILE", original)
        out = run(original)
        self.assertNotIn(b"ICC_PROFILE", out.data)
        self.assertNotIn("icc_profile", Image.open(io.BytesIO(out.data)).info)

    def test_png_alpha_is_preserved_after_cleaning(self):
        src = Image.new("RGBA", (8, 8), (255, 0, 0, 0))
        src.putpixel((1, 1), (0, 255, 0, 255))
        buf = io.BytesIO()
        src.save(buf, format="PNG", icc_profile=f.icc_profile())
        out = Image.open(io.BytesIO(run(buf.getvalue()).data)).convert("RGBA")
        self.assertEqual(out.getpixel((0, 0))[3], 0)
        self.assertEqual(out.getpixel((1, 1)), (0, 255, 0, 255))

    def test_png_palette_and_rgb_transparency_are_preserved_after_cleaning(self):
        pal = Image.new("P", (4, 4), 0)
        pal.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
        pal.putpixel((2, 2), 1)
        buf = io.BytesIO()
        pal.save(buf, format="PNG", transparency=0)
        out = Image.open(io.BytesIO(run(buf.getvalue()).data)).convert("RGBA")
        self.assertEqual(out.getpixel((0, 0))[3], 0)
        self.assertEqual(out.getpixel((2, 2))[3], 255)
        rgb = Image.new("RGB", (4, 4), (10, 20, 30))
        buf = io.BytesIO()
        rgb.save(buf, format="PNG", transparency=(10, 20, 30))  # tRNS: 이 색은 투명
        out = Image.open(io.BytesIO(run(buf.getvalue()).data)).convert("RGBA")
        self.assertEqual(out.getpixel((0, 0))[3], 0)

    def converted(self, mode, color, icc, size=(4, 4), fmt="PNG", **save_kwargs):
        buf = io.BytesIO()
        Image.new(mode, size, color).save(buf, format=fmt, icc_profile=icc, **save_kwargs)
        out = Image.open(io.BytesIO(run(buf.getvalue()).data))
        self.assertNotIn("icc_profile", out.info)  # 변환한 뒤에는 프로필을 남기지 않는다(결과는 sRGB)
        return out

    def test_wide_gamut_png_is_converted_to_srgb_not_just_stripped(self):
        """Display P3 의 (180,120,80) 은 sRGB 로 옮기면 다른 숫자가 된다. 프로필만 지우면 색이 바랜다."""
        m = ((3.1338561, -1.6168667, -0.4906146), (-0.9787684, 1.9161415, 0.0334540), (0.0719453, -0.2289914, 1.4052427))  # XYZ(D50) → 선형 sRGB
        rgb = (180, 120, 80)
        lin = [(c / 255) ** 2.2 for c in rgb]
        xyz = [sum(f.DISPLAY_P3_D50[i][k] * lin[i] for i in range(3)) for k in range(3)]
        expected = tuple(f.srgb_encode(sum(m[r][k] * xyz[k] for k in range(3))) for r in range(3))
        self.assertNotEqual(expected, rgb)
        out = self.converted("RGB", rgb, f.make_icc("Display P3 test", f.DISPLAY_P3_D50, 2.2)).getpixel((0, 0))
        for got, want in zip(out, expected):
            self.assertAlmostEqual(got, want, delta=3)

    def test_linear_profile_is_gamma_encoded_for_png_and_jpeg(self):
        icc = f.make_icc("Linear sRGB test", f.SRGB_D50, 1.0)
        want = f.srgb_encode(128 / 255)  # 선형 0.5 → sRGB 약 188
        self.assertGreater(want, 180)
        for fmt, tol in (("PNG", 2), ("JPEG", 4)):
            px = self.converted("RGB", (128, 128, 128), icc, fmt=fmt).getpixel((1, 1))
            for c in px:
                self.assertAlmostEqual(c, want, delta=tol, msg=fmt)

    def test_alpha_survives_color_conversion(self):
        out = self.converted("RGBA", (128, 128, 128, 77), f.make_icc("Linear sRGB test", f.SRGB_D50, 1.0)).convert("RGBA")
        r, g, b, a = out.getpixel((0, 0))
        self.assertEqual(a, 77)
        self.assertAlmostEqual(r, f.srgb_encode(128 / 255), delta=2)

    def test_gray_profile_converted_and_stays_gray(self):
        out = self.converted("L", 128, f.make_icc("Linear gray test", gray=True, gamma=1.0))
        self.assertEqual(out.mode, "L")
        self.assertAlmostEqual(out.getpixel((0, 0)), f.srgb_encode(128 / 255), delta=2)

    def test_srgb_profile_leaves_pixels_untouched(self):
        out = self.converted("RGB", (12, 200, 99), f.icc_profile())
        self.assertEqual(out.getpixel((0, 0)), (12, 200, 99))

    def test_unusable_profiles_are_treated_as_srgb_and_do_not_fail_the_upload(self):
        cases = {
            "garbage": b"this is not an icc profile",
            "truncated": f.icc_profile()[:100],
            "gray_profile_on_rgb_image": f.make_icc("gray", gray=True),
        }
        for name, icc in cases.items():
            out = self.converted("RGB", (12, 200, 99), icc)
            self.assertEqual(out.getpixel((0, 0)), (12, 200, 99), name)

    def test_oversized_icc_profile_is_not_parsed_and_upload_still_works(self):
        from assets.validation import MAX_ICC_BYTES

        huge = f.make_icc("Linear sRGB test", f.SRGB_D50, 1.0) + b"\0" * MAX_ICC_BYTES  # 유효해 보이지만 상한 초과
        out = self.converted("RGB", (12, 200, 99), huge, fmt="JPEG")
        self.assertEqual(out.mode, "RGB")  # 변환하지 않고(sRGB 로 간주) 통과, 프로필은 버려짐

    def test_png_icc_decompression_bomb_is_rejected_cleanly(self):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="PNG", icc_profile=b"\0" * (8 * 1024 * 1024))  # 파일은 수 KB, 풀면 8MB
        self.assertLess(len(buf.getvalue()), 100_000)
        self.assertRejected(buf.getvalue(), "corrupt")

    def test_cmyk_jpeg_without_profile_still_converts_to_rgb(self):
        buf = io.BytesIO()
        Image.new("CMYK", (8, 8), (0, 255, 255, 0)).save(buf, format="JPEG")
        out = Image.open(io.BytesIO(run(buf.getvalue()).data))
        self.assertEqual(out.mode, "RGB")

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
