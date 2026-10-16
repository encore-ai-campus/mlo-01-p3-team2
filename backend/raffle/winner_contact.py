"""Private prize-contact images, visible only to the winning account or managers."""
from io import BytesIO
from uuid import uuid4
import warnings

from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from .live import publish_change
from .models import Event, WinnerContact
from .service import RaffleError, retry_locked

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_SIDE = 2048


def configuration():
    return WinnerContact.objects.only('id', 'version', 'byte_count', 'updated_at').filter(pk=1).first()


def configured(config):
    return bool(config and config.byte_count > 0)


def personal_state(user):
    if not user or not user.is_authenticated:
        return None
    event = Event.objects.filter(status=Event.Status.DRAWN, winner_entry__user_id=user.pk).only(
        'id', 'title', 'winner_nickname', 'drawn_at').order_by('-drawn_at', '-created_at', '-id').first()
    if event is None:
        return None
    config = configuration()
    ready = configured(config)
    return {'eventId': str(event.pk), 'eventTitle': event.title, 'nickname': event.winner_nickname,
            'status': 'ready' if ready else 'pending',
            'qrUrl': f'/api/raffle/winner-contact/qr/{event.pk}/?v={config.version}' if ready else None}


def manager_state(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return None
    config = configuration()
    ready = configured(config)
    return {'configured': ready, 'updatedAt': config.updated_at.isoformat() if ready else None,
            'previewUrl': f'/api/raffle/winner-contact/qr/?v={config.version}' if ready else None}


def image_bytes():
    config = WinnerContact.objects.filter(pk=1, byte_count__gt=0).only('image_png').first()
    if config is None or not config.image_png:
        raise RaffleError('오픈채팅 QR 이미지를 준비 중입니다.', 404)
    return bytes(config.image_png)


def require_winner(user, event_id):
    if not Event.objects.filter(pk=event_id, status=Event.Status.DRAWN,
                                winner_entry__user_id=user.pk).exists():
        # An unavailable event and someone else's result produce the same response.
        raise RaffleError('당첨자 수령 안내를 찾을 수 없어요.', 404)


def normalize_image(upload):
    if upload is None or upload.size == 0:
        raise RaffleError('오픈채팅 QR 이미지를 선택해 주세요.', 400)
    if upload.size > MAX_IMAGE_BYTES:
        raise RaffleError('QR 이미지는 2MB 이하로 등록해 주세요.', 413)
    raw = upload.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise RaffleError('QR 이미지는 2MB 이하로 등록해 주세요.', 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP'} or getattr(image, 'is_animated', False):
                    raise ValueError
                if not (80 <= image.width <= MAX_IMAGE_SIDE and 80 <= image.height <= MAX_IMAGE_SIDE):
                    raise ValueError
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                image.load()
                image = ImageOps.exif_transpose(image).convert('RGBA')
                # Copy pixels onto a fresh image; uploaded metadata and filenames aren't stored.
                clean = Image.new('RGB', image.size, 'white')
                clean.paste(image, mask=image.getchannel('A'))
                output = BytesIO()
                clean.save(output, format='PNG', optimize=True)
        data = output.getvalue()
        if len(data) > MAX_IMAGE_BYTES:
            raise RaffleError('QR 부분이 선명한 2MB 이하 이미지를 선택해 주세요.', 413)
        return data
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise RaffleError('QR 부분이 선명한 PNG·JPG·WEBP 이미지를 선택해 주세요.', 400) from None


def save_image(upload):
    data = normalize_image(upload)
    _persist_image(data)


@retry_locked
def _persist_image(data):
    with transaction.atomic():
        from .service import locked_control
        locked_control()
        WinnerContact.objects.update_or_create(pk=1, defaults={
            'image_png': data, 'byte_count': len(data), 'version': uuid4()})
        transaction.on_commit(publish_change)
