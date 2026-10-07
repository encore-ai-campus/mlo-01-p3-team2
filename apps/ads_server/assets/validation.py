"""이미지 검증·재인코딩 (설계 §8 0-5, 위협 T15~T18).

원칙: **확장자·Content-Type 은 신뢰하지 않는다.** 내용으로 형식을 판별하고(JPEG·PNG 만),
용량·픽셀 수 상한을 넘거나 애니메이션·손상 파일은 거부하며, **색을 sRGB 로 바꾼 뒤 다시 인코딩**해서 메타데이터(ICC·EXIF·XMP·텍스트)를 없앤다.
"""
import hashlib
import io
import warnings
from dataclasses import dataclass

from django.conf import settings
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = ("JPEG", "PNG")
FORMAT_INFO = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png")}
JPEG_QUALITIES = (90, 85, 80, 70, 60, 50)  # 재인코딩 결과가 상한을 넘으면 품질을 낮춰 본다
SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")  # PNG, JPEG 서명. 형식 안내(손상 vs 미지원)에만 쓰고 판정에는 쓰지 않는다


SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
PROFILE_SPACE_TO_MODE = {"RGB": "RGB", "GRAY": "L", "CMYK": "CMYK"}  # ICC 색 공간 → 변환할 수 있는 이미지 모드
MAX_ICC_BYTES = 1024 * 1024  # 이보다 큰 프로필은 lcms 에 넘기지 않는다(공격면 축소). 실제 인쇄용 CMYK 프로필도 보통 이 안이다.


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


def _icc_to_srgb(img, icc):
    """내장 ICC 로 sRGB 변환. 프로필이 없거나 쓸 수 없으면 `None`(호출한 쪽이 sRGB 로 간주한다).

    신뢰할 수 없는 입력이므로 프로필을 열 수 없거나(깨짐·잘림), 이미지 모드와 색 공간이 맞지 않으면 변환하지 않고 **업로드를 거부하지도 않는다**
    (흔한 일이고, 거부하면 정상 사용자만 불편하다). 이미 sRGB 인 프로필은 건드리지 않는다(불필요한 반올림 방지).
    """
    if not icc or len(icc) > MAX_ICC_BYTES:
        return None
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        space = src.profile.xcolor_space.strip()
        if PROFILE_SPACE_TO_MODE.get(space) != img.mode:
            return None
        if space == "RGB" and (src.profile.profile_description or "").strip().lower().startswith("srgb"):
            return None  # "sRGB IEC61966-2.1" 등. 이름만 보는 가벼운 판별이라, 이름을 속인 프로필은 변환이 생략될 뿐 해가 없다
        transform = ImageCms.buildTransform(
            src, SRGB, img.mode, "RGB",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        )
        out = ImageCms.applyTransform(img, transform)
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        return None
    return out.convert("L") if space == "GRAY" else out  # 그레이는 중성이라 변환 후 다시 L 로


def _srgb_pixels(img, icc):
    """픽셀을 sRGB 값으로. 알파는 변환에서 분리했다가 되돌린다. CMYK 는 프로필이 없을 때만 단순 변환.

    PNG 의 투명 색(tRNS)은 `img.info` 에 있어 변환·복사 과정에서 사라지므로 먼저 알파 채널로 바꿔 둔다.
    """
    if img.info.get("transparency") is not None and img.mode in ("L", "RGB"):
        img = img.convert("LA" if img.mode == "L" else "RGBA")
    alpha = img.getchannel("A") if img.mode in ("RGBA", "LA") else None
    base = img.convert(img.mode.rstrip("A")) if alpha is not None else img
    out = _icc_to_srgb(base, icc)
    if out is None:
        out = base if base.mode in ("RGB", "L") else base.convert("RGB")
    if alpha is not None:
        out = out.copy()
        out.putalpha(alpha)
    return out


def _bare_copy(img):
    """픽셀만 새 이미지로 옮긴다. `img.info`(ICC·EXIF·텍스트·dpi·gamma 등)를 인코더가 되살리지 못하게 한다.

    Pillow 의 PNG 인코더는 옵션을 생략하면 `info` 의 ICC 프로필을 다시 쓴다(`icc_profile=None` 으로 막을 수는 있지만 다른 항목도 같은 위험이다).
    """
    return Image.frombytes(img.mode, img.size, img.tobytes())


def _reencode(img, fmt, max_bytes):
    icc = img.info.get("icc_profile")  # 변환에 쓴 뒤 버린다(결과는 sRGB 로 간주되는 프로필 없는 이미지)
    if fmt == "JPEG":
        img = ImageOps.exif_transpose(img)  # 회전 정보를 픽셀에 반영한 뒤 EXIF 를 버린다
        img = _bare_copy(_srgb_pixels(img, icc))
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
    img = _bare_copy(_srgb_pixels(img, icc))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)  # 부가 정보가 없는 새 이미지라 ICC·텍스트 청크가 남지 않는다
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
