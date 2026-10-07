"""테스트용 이미지 생성 도우미."""
import io
import os
import struct
import zlib

from PIL import Image, PngImagePlugin


def png_bytes(w=32, h=32, color=(200, 30, 30), mode="RGB", secret_text=None):
    out = io.BytesIO()
    info = None
    if secret_text:
        info = PngImagePlugin.PngInfo()
        info.add_text("secret", secret_text)
    Image.new(mode, (w, h), color).save(out, format="PNG", pnginfo=info)
    return out.getvalue()


def jpeg_bytes(w=32, h=32, color=(30, 120, 200), quality=90, orientation=None, make=None):
    exif = Image.Exif()
    if make:
        exif[0x010F] = make  # Make
    if orientation:
        exif[0x0112] = orientation
    out = io.BytesIO()
    kwargs = {"exif": exif} if (make or orientation) else {}
    Image.new("RGB", (w, h), color).save(out, format="JPEG", quality=quality, **kwargs)
    return out.getvalue()


def noise_image(w=200, h=200):
    return Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))


def jpeg_of(img, quality):
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def other_format_bytes(fmt):
    out = io.BytesIO()
    Image.new("RGB", (16, 16), (1, 2, 3)).save(out, format=fmt)
    return out.getvalue()


def apng_bytes():
    frames = [Image.new("RGB", (16, 16), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    out = io.BytesIO()
    frames[0].save(out, format="PNG", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return out.getvalue()


def crafted_png_header(width, height):
    """헤더에는 큰 해상도를 적고 데이터는 아주 작은 PNG(압축 폭탄 모사). 디코딩하면 거대한 메모리가 필요하다."""

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b""))


SVG_WITH_SCRIPT = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
