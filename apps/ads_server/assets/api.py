"""assets 의 외부 공개 면. 다른 모듈은 이 파일만 import 한다(설계 R2). 다른 프로젝트 모듈을 import 하지 않는다."""
from django.conf import settings
from django.utils.module_loading import import_string

from .storage import NAME_RE
from .validation import ImageRejected, ValidatedImage, validate_image


def get_storage():
    return import_string(settings.ASSET_STORAGE)(settings.MEDIA_ROOT)


def store(image: ValidatedImage) -> str:
    """검증된 이미지를 저장하고 소재 이름(`<sha256>.<ext>`)을 돌려준다."""
    get_storage().put(image.name, image.data)
    return image.name


def asset_exists(name: str) -> bool:
    return get_storage().exists(name)


def open_asset(name: str):
    return get_storage().open(name)


def asset_url(name: str) -> str:
    """결정 응답의 `image_url`(C3). 광고 서버의 공개 주소를 설정에서 읽는다."""
    return f"{settings.ASSET_PUBLIC_BASE_URL.rstrip('/')}/assets/{name}"


__all__ = [
    "ImageRejected", "ValidatedImage", "validate_image", "store", "asset_exists", "open_asset", "asset_url",
    "get_storage", "NAME_RE",
]
