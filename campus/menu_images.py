"""Read the cafeteria's public Kakao profile photo and keep a local copy."""
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import json
import os
from pathlib import Path
import re
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4
import warnings
from zoneinfo import ZoneInfo

from django.conf import settings
from PIL import Image, UnidentifiedImageError

IMAGE_TYPES = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
               "WEBP": ("webp", "image/webp"), "GIF": ("gif", "image/gif")}
FILE_NAME = re.compile(r"[0-9a-f]{64}\.(jpg|png|webp|gif)\Z")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
ALLOWED_HOSTS = {"pf.kakao.com", "k.kakaocdn.net"}


class MenuImageError(Exception):
    pass


def validate_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS
            or parts.username or parts.password or parts.port not in (None, 443)):
        raise MenuImageError("Unexpected cafeteria photo address")
    return url


class ChannelRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        validate_url(new_url)
        return super().redirect_request(request, fp, code, msg, headers, new_url)


def download(url, limit):
    validate_url(url)
    request = Request(url, headers={"User-Agent": "PLAYDATA-Campus-Menu/1.0",
                                    "Cache-Control": "no-cache"})
    try:
        with build_opener(ChannelRedirects()).open(request, timeout=15) as response:
            data = response.read(limit + 1)
    except (OSError, URLError) as exc:
        raise MenuImageError("Could not retrieve the cafeteria photo") from exc
    if not data or len(data) > limit:
        raise MenuImageError("The cafeteria response is empty or too large")
    return data


class ProfileMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.photo = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "meta" and attrs.get("property", "").lower() == "og:image":
            self.photo = attrs.get("content")


def profile_photo_url(html, channel_url):
    metadata = ProfileMetadata()
    metadata.feed(html)
    if not metadata.photo:
        raise MenuImageError("The channel profile photo is missing")
    photo = validate_url(urljoin(channel_url, metadata.photo))
    # The channel's profile-image viewer uses img_xl.jpg, rather than the
    # cropped img_m.jpg thumbnail published in the page's Open Graph metadata.
    if urlsplit(photo).path.endswith("/img_m.jpg"):
        photo = photo.replace("/img_m.jpg", "/img_xl.jpg", 1)
    return photo


def inspect_image(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=list(IMAGE_TYPES)) as photo:
                width, height = photo.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise MenuImageError("The cafeteria photo dimensions are too large")
                extension, content_type = IMAGE_TYPES[photo.format]
                photo.verify()
            with Image.open(BytesIO(data), formats=list(IMAGE_TYPES)) as photo:
                photo.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise MenuImageError("The cafeteria response is not a valid photo") from exc
    return {"width": width, "height": height, "extension": extension, "content_type": content_type}


def storage_root():
    return Path(settings.BOARD_MENU_STORAGE_ROOT)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def refresh_lock():
    """One download at a time, including manual refreshes in another process."""
    root = storage_root()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "refresh.lock"
    token = uuid4().hex
    try:
        # A crashed process may leave a lock; every request is bounded to 15 s.
        if lock.exists() and datetime.now().timestamp() - lock.stat().st_mtime > 300:
            lock.unlink(missing_ok=True)
        with lock.open("x", encoding="ascii") as handle:
            handle.write(token)
    except FileExistsError:
        yield False
        return
    try:
        yield True
    finally:
        if lock.exists() and lock.read_text(encoding="ascii") == token:
            lock.unlink(missing_ok=True)


def latest_menu():
    try:
        metadata = json.loads((storage_root() / "latest.json").read_text(encoding="utf-8"))
        filename = metadata["filename"]
        if not FILE_NAME.fullmatch(filename) or not (storage_root() / filename).is_file():
            return None
        updated = datetime.fromisoformat(metadata["updated_at"])
        if updated.tzinfo is None:
            return None
        if metadata["content_type"] != dict(IMAGE_TYPES.values()).get(filename.rsplit(".", 1)[1]):
            return None
        return metadata
    except (OSError, ValueError, KeyError, TypeError):
        return None


def local_now():
    return datetime.now(ZoneInfo(settings.BOARD_MENU_TIME_ZONE))


def refresh_due(now=None, metadata=None):
    now = (now or local_now()).astimezone(ZoneInfo(settings.BOARD_MENU_TIME_ZONE))
    hour, minute = map(int, settings.BOARD_MENU_UPDATE_TIME.split(":"))
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled:
        return False
    metadata = metadata if metadata is not None else latest_menu()
    if not metadata:
        return True
    return datetime.fromisoformat(metadata["updated_at"]) < scheduled


def refresh_menu(*, force=False, now=None):
    now = now or local_now()
    with refresh_lock() as acquired:
        if not acquired or (not force and not refresh_due(now)):
            return None
        html = download(settings.BOARD_MENU_SOURCE_URL, 2 * 1024 * 1024).decode("utf-8")
        photo_url = profile_photo_url(html, settings.BOARD_MENU_SOURCE_URL)
        data = download(photo_url, MAX_IMAGE_BYTES)
        details = inspect_image(data)
        filename = sha256(data).hexdigest() + "." + details["extension"]
        metadata = {**details, "filename": filename, "updated_at": now.isoformat(),
                    "source_url": settings.BOARD_MENU_SOURCE_URL, "photo_url": photo_url}
        # Publish the complete image before changing what readers see.
        atomic_write(storage_root() / filename, data)
        atomic_write(storage_root() / "latest.json", json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
        return metadata
