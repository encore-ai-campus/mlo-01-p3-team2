"""이미지 검증·재인코딩 (설계 §8 0-5, 위협 T15~T18).

원칙: **확장자·Content-Type 은 신뢰하지 않는다.** 내용으로 형식을 판별하고(JPEG·PNG 만),
용량·픽셀 수 상한을 넘거나 애니메이션·손상 파일은 거부하며, **다시 인코딩**해서 메타데이터(EXIF 등)를 없앤다.
"""
import hashlib
import io
import warnings
from dataclasses import dataclass

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = ("JPEG", "PNG")
FORMAT_INFO = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png")}
JPEG_QUALITIES = (90, 85, 80, 70, 60, 50)  # 재인코딩 결과가 상한을 넘으면 품질을 낮춰 본다
SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")  # PNG, JPEG 서명. 형식 안내(손상 vs 미지원)에만 쓰고 판정에는 쓰지 않는다


class ImageRejected(ValueError):
    """reason: unsupported_format, too_large, too_many_pixels, animated, corrupt (계약의 `invalid_image` 상세 값)."""

    def __init__(self, reason, message=""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes  # 재인코딩된 바이트. 이것만 저장한다(원본은 저장하지 않는다)
    content_type: str
    ext: str
    width: int
    height: int
    sha256: str

    @property
    def name(self):
        return f"{self.sha256}.{self.ext}"


def _reencode(img, fmt, max_bytes):
    if fmt == "JPEG":
        img = ImageOps.exif_transpose(img)  # 회전 정보를 픽셀에 반영한 뒤 EXIF 를 버린다
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        for quality in JPEG_QUALITIES:
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)  # exif·icc 를 넘기지 않아 제거된다
            if out.tell() <= max_bytes:
                return img, out.getvalue()
        raise ImageRejected("too_large", "재인코딩한 결과가 용량 상한을 넘습니다.")
    if img.mode == "P":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    elif img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)  # 텍스트 청크·메타데이터를 넘기지 않아 제거된다
    if out.tell() > max_bytes:
        raise ImageRejected("too_large", "재인코딩한 결과가 용량 상한을 넘습니다.")
    return img, out.getvalue()


def validate_image(fileobj):
    max_bytes = settings.ASSET_MAX_BYTES
    max_pixels = settings.ASSET_MAX_PIXELS

    raw = fileobj.read(max_bytes + 1)  # 한도 + 1 바이트까지만 읽는다(초과분을 끝까지 읽지 않는다)
    if len(raw) > max_bytes:
        raise ImageRejected("too_large", f"파일은 최대 {max_bytes} 바이트입니다.")
    if not raw:
        raise ImageRejected("corrupt", "빈 파일입니다.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)  # 경고도 거부로 취급
            img = Image.open(io.BytesIO(raw), formats=ALLOWED_FORMATS)  # 형식은 내용으로 판별, JPEG·PNG 만
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected("too_many_pixels", "이미지 해상도가 너무 큽니다.")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        if raw.startswith(SIGNATURES):  # JPEG·PNG 로 보이는데 열 수 없다: 잘렸거나 손상된 파일
            raise ImageRejected("corrupt", "이미지가 손상되었습니다.")
        raise ImageRejected("unsupported_format", "JPEG 또는 PNG 이미지만 올릴 수 있습니다.")

    width, height = img.size  # 헤더만 읽은 상태: 디코딩 전에 픽셀 수를 먼저 검사한다
    if width * height > max_pixels:
        raise ImageRejected("too_many_pixels", "이미지 해상도가 너무 큽니다.")
    if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1:
        raise ImageRejected("animated", "움직이는 이미지는 올릴 수 없습니다.")
    fmt = img.format
    if fmt not in FORMAT_INFO:  # formats= 로 걸러지지만 방어적으로 한 번 더
        raise ImageRejected("unsupported_format")

    try:
        img.load()  # 실제 디코딩. 잘린 파일·손상 파일은 여기서 드러난다
    except Image.DecompressionBombError:
        raise ImageRejected("too_many_pixels", "이미지 해상도가 너무 큽니다.")
    except (OSError, ValueError, SyntaxError, EOFError, MemoryError):
        raise ImageRejected("corrupt", "이미지가 손상되었습니다.")

    try:
        img, data = _reencode(img, fmt, max_bytes)
    except ImageRejected:
        raise
    except (OSError, ValueError):
        raise ImageRejected("corrupt", "이미지를 처리할 수 없습니다.")

    content_type, ext = FORMAT_INFO[fmt]
    return ValidatedImage(
        data=data, content_type=content_type, ext=ext, width=img.size[0], height=img.size[1],
        sha256=hashlib.sha256(data).hexdigest(),
    )
