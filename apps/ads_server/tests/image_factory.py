"""테스트용 이미지 생성 도우미."""
import io
import os
import struct
import zlib

from PIL import Image, PngImagePlugin


def icc_profile():
    from PIL import ImageCms

    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


SRGB_D50 = ((0.4360747, 0.2225045, 0.0139322), (0.3850649, 0.7168786, 0.0971045), (0.1430804, 0.0606169, 0.7141733))
DISPLAY_P3_D50 = ((0.51512, 0.24120, -0.00105), (0.29198, 0.69225, 0.04189), (0.15710, 0.06657, 0.78407))
D50 = (0.9642, 1.0, 0.8249)


def _s15(v):
    return struct.pack(">i", round(v * 65536))


def _xyz(x, y, z):
    return b"XYZ \0\0\0\0" + _s15(x) + _s15(y) + _s15(z)


def _curve(gamma):
    if gamma == 1.0:
        return b"curv\0\0\0\0" + struct.pack(">I", 0)  # 항등 곡선
    return b"curv\0\0\0\0" + struct.pack(">I", 1) + struct.pack(">H", round(gamma * 256)) + b"\0\0"


def _desc(text):
    s = text.encode("ascii") + b"\0"
    return b"desc\0\0\0\0" + struct.pack(">I", len(s)) + s + b"\0" * (4 + 4 + 2 + 1 + 67)


def make_icc(description, primaries=SRGB_D50, gamma=1.0, gray=False):
    """테스트용 ICC v2 프로필(행렬/곡선형 RGB 또는 그레이). 외부 파일 없이 색 변환을 검증하려고 직접 만든다."""
    tags = {b"desc": _desc(description), b"cprt": b"text\0\0\0\0test\0", b"wtpt": _xyz(*D50)}
    if gray:
        tags[b"kTRC"] = _curve(gamma)
    else:
        for sig, xyz in zip((b"rXYZ", b"gXYZ", b"bXYZ"), primaries):
            tags[sig] = _xyz(*xyz)
        for sig in (b"rTRC", b"gTRC", b"bTRC"):
            tags[sig] = _curve(gamma)
    table, body, offset = b"", b"", 128 + 4 + 12 * len(tags)
    for sig, data in tags.items():
        data += b"\0" * (-len(data) % 4)
        table += sig + struct.pack(">II", offset + len(body), len(data))
        body += data
    size = offset + len(body)
    header = struct.pack(">I4sI4s4s4s", size, b"lcms", 0x02100000, b"mntr", b"GRAY" if gray else b"RGB ", b"XYZ ")
    header += struct.pack(">6H", 2026, 1, 1, 0, 0, 0) + b"acsp" + b"APPL" + b"\0" * 4 + b"\0" * 8 + b"\0" * 8 + struct.pack(">I", 0)
    header += _s15(D50[0]) + _s15(D50[1]) + _s15(D50[2]) + b"\0" * 4 + b"\0" * 44
    return header + struct.pack(">I", len(tags)) + table + body


def srgb_encode(linear):
    v = min(max(linear, 0.0), 1.0)
    return round(255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055))


def png_chunk_types(data):
    """PNG 데이터에 든 청크 이름 목록(순서대로)."""
    types, pos = [], 8
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        types.append(data[pos + 4:pos + 8].decode("latin-1"))
        pos += 12 + length
    return types


def png_bytes(w=32, h=32, color=(200, 30, 30), mode="RGB", secret_text=None, icc=None, dpi=None, gamma=None, **save_kwargs):
    out = io.BytesIO()
    info = None
    if secret_text:
        info = PngImagePlugin.PngInfo()
        info.add_text("secret", secret_text)
    if icc:
        save_kwargs["icc_profile"] = icc
    if dpi:
        save_kwargs["dpi"] = dpi
    Image.new(mode, (w, h), color).save(out, format="PNG", pnginfo=info, **save_kwargs)
    return out.getvalue()


def jpeg_bytes(w=32, h=32, color=(30, 120, 200), quality=90, orientation=None, make=None, icc=None):
    exif = Image.Exif()
    if make:
        exif[0x010F] = make  # Make
    if orientation:
        exif[0x0112] = orientation
    out = io.BytesIO()
    kwargs = {"exif": exif} if (make or orientation) else {}
    if icc:
        kwargs["icc_profile"] = icc
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
