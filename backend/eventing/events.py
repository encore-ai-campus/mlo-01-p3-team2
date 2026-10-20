"""Event envelopes and the persistent Kafka outbox."""
import json
import logging
import math
import uuid
from datetime import timedelta
from datetime import timezone as datetime_timezone

from django.db import transaction
from django.conf import settings
from django.utils import timezone

from accounts.models import Profile
from .catalog import class_group_uuid
from .models import EventOutbox, PlatformSession

logger = logging.getLogger(__name__)
SESSION_KEY = "platform_session_uuid"

TOPIC_BY_TYPE = {
    "session_started": "raw.account",
    "session_ended": "raw.account",
    "chat_sent": "raw.chat",
    "post_created": "raw.board",
    "post_updated": "raw.board",
    "post_deleted": "raw.board",
    "post_read": "raw.board",
    "comment_created": "raw.comment",
    "comment_updated": "raw.comment",
    "comment_deleted": "raw.comment",
    "content_open_requested": "raw.content_usage",
    "quiz_answered": "raw.content_usage",
    "point_granted": "raw.points",
    "movement_observed": "raw.movement",
    "floor_transferred": "raw.movement",
}
EXTRA_FIELDS = {
    "session_started": {"session_uuid"},
    "session_ended": {"session_uuid", "end_reason"},
    "chat_sent": {"message_uuid", "channel_code", "floor_uuid"},
    "post_created": {"post_uuid", "revision", "zone_uuid"},
    "post_updated": {"post_uuid", "revision", "zone_uuid"},
    "post_deleted": {"post_uuid", "revision", "zone_uuid"},
    "post_read": {"post_uuid", "revision", "zone_uuid"},
    "comment_created": {"comment_uuid", "post_uuid", "parent_comment_uuid", "revision"},
    "comment_updated": {"comment_uuid", "post_uuid", "parent_comment_uuid", "revision"},
    "comment_deleted": {"comment_uuid", "post_uuid", "parent_comment_uuid", "revision"},
    "content_open_requested": {"content_uuid", "category_uuid", "domain", "content_kind", "zone_uuid", "action"},
    "quiz_answered": {"attempt_uuid", "question_uuid", "content_uuid", "question_type", "choice_uuid", "is_correct"},
    "point_granted": {"ledger_uuid", "attempt_uuid", "delta", "balance_after"},
    "movement_observed": {"floor_uuid", "zone_uuid", "x", "y", "input_kind"},
    "floor_transferred": {"from_floor_uuid", "to_floor_uuid", "zone_uuid"},
}
_BASE_FIELDS = {"user_uuid", "session_uuid", "class_group_uuid"}
SCHEMA_VERSION_BY_TYPE = {"quiz_answered": "1.1"}


def get_profile(user):
    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={"nickname": user.get_username()[:20]},
    )
    return profile


def raw_identity(user, session_uuid):
    profile = get_profile(user)
    return {
        "user_uuid": str(profile.user_uuid),
        "session_uuid": str(session_uuid),
        "class_group_uuid": str(class_group_uuid(profile.cohort)),
    }


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_raw_data(event_type, raw_data):
    """Reject extra fields and nested/free-text values without recording their contents."""
    valid = event_type in EXTRA_FIELDS and isinstance(raw_data, dict)
    if valid:
        valid = set(raw_data) == _BASE_FIELDS | EXTRA_FIELDS[event_type]
    nullable = {"zone_uuid", "parent_comment_uuid"}
    if event_type == "chat_sent":
        nullable.add("floor_uuid")
    if event_type == "quiz_answered" and isinstance(raw_data, dict) and raw_data.get("question_type") == "FILL_BLANK":
        nullable.add("choice_uuid")
    if valid:
        for key, value in raw_data.items():
            if key.endswith("_uuid"):
                if value is None and key in nullable:
                    continue
                try:
                    parsed = uuid.UUID(value) if isinstance(value, str) else None
                except ValueError:
                    parsed = None
                valid = parsed is not None and parsed.version == 4 and str(parsed) == value
            elif key == "revision":
                valid = type(value) is int and value >= 1
            elif key in {"delta", "balance_after"}:
                valid = type(value) is int and (0 < value < 2**63 if key == "delta" else 0 <= value < 2**63)
            elif key == "is_correct":
                valid = type(value) is bool
            elif key in {"x", "y"}:
                valid = type(value) in (int, float) and value >= 0
                if valid:
                    try:
                        valid = math.isfinite(value)
                    except OverflowError:
                        valid = False
            else:
                choices = {
                    "end_reason": {"LOGOUT", "SESSION_EXPIRED"},
                    "channel_code": {"GLOBAL"},
                    "domain": {"LEARNING", "REST"},
                    "content_kind": {"EXTERNAL_LINK", "QUIZ"},
                    "action": {"OPEN_REQUESTED"},
                    "input_kind": {"KEYBOARD"},
                    "question_type": {"MULTIPLE_CHOICE", "FILL_BLANK"},
                }
                valid = isinstance(value, str) and value in choices.get(key, set())
            if not valid:
                break
    if valid and event_type == "quiz_answered" and raw_data["question_type"] == "FILL_BLANK":
        valid = raw_data["choice_uuid"] is None
    if not valid:
        logger.error("Raw event rejected: fields or value types do not match the allowed contract")
        raise ValueError("Raw event fields or value types do not match the allowed contract")


def build_envelope(event_uuid, event_type, occurred_at, raw_data):
    validate_raw_data(event_type, raw_data)
    try:
        parsed_event_uuid = uuid.UUID(str(event_uuid))
    except (ValueError, TypeError, AttributeError):
        parsed_event_uuid = None
    if parsed_event_uuid is None or parsed_event_uuid.version != 4:
        logger.error("Raw event rejected: event identity is not UUIDv4")
        raise ValueError("Raw event identity must be UUIDv4")
    try:
        import xxhash
    except ImportError:
        return None
    occurred_at = occurred_at.astimezone(datetime_timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    fingerprint = xxhash.xxh3_64(canonical_json(raw_data).encode("utf-8")).hexdigest().lower()
    return {
        "event_uuid": str(parsed_event_uuid),
        "raw_manifest": {
            "schema_version": SCHEMA_VERSION_BY_TYPE.get(event_type, "1.0"),
            "event_type": event_type,
            "occurred_at": occurred_at,
            "source": settings.CAMPUS_RAW_SOURCE,
            "fingerprint_algorithm": "xxh3_64",
            "fingerprint": fingerprint,
        },
        "raw_data": raw_data,
    }


def enqueue_event(event_type, user, session_uuid, attributes, *, occurred_at=None):
    """Validate the strict DRD whitelist and persist one immutable outbox record."""
    if event_type not in TOPIC_BY_TYPE or not isinstance(attributes, dict) or set(attributes) != EXTRA_FIELDS[event_type]:
        logger.error("Raw event rejected: attributes do not match the allowed contract")
        raise ValueError("Raw event attributes do not match the allowed contract")
    raw_data = raw_identity(user, session_uuid)
    raw_data.update(attributes)
    validate_raw_data(event_type, raw_data)
    event_uuid = uuid.uuid4()
    occurred_at = occurred_at or timezone.now()
    payload = build_envelope(event_uuid, event_type, occurred_at, raw_data)
    row = EventOutbox.objects.create(
        event_uuid=event_uuid,
        event_type=event_type,
        topic=TOPIC_BY_TYPE[event_type],
        message_key=raw_data["user_uuid"],
        raw_data=raw_data,
        occurred_at=occurred_at,
        payload_json=payload,
    )
    from .publisher import notify_outbox_ready
    transaction.on_commit(notify_outbox_ready, robust=True)
    return row


def start_platform_session(user, session, *, now=None):
    now = now or timezone.now()
    session_uuid = uuid.uuid4()
    with transaction.atomic():
        PlatformSession.objects.create(session_uuid=session_uuid, user=user, started_at=now, last_seen_at=now)
        session[SESSION_KEY] = str(session_uuid)
        enqueue_event(
            "session_started", user, session_uuid, {"session_uuid": str(session_uuid)}, occurred_at=now,
        )
    return str(session_uuid)


def ensure_platform_session(user, session, *, now=None, touch=True):
    """Attach a DRD session UUID to a legacy authenticated Django session if needed."""
    now = now or timezone.now()
    raw_session_uuid = session.get(SESSION_KEY)
    try:
        session_uuid = uuid.UUID(str(raw_session_uuid))
    except (ValueError, TypeError, AttributeError):
        session_uuid = None
    if session_uuid is not None:
        record = PlatformSession.objects.filter(session_uuid=session_uuid, user=user).first()
        if record and record.ended_at is None:
            if touch and (now - record.last_seen_at).total_seconds() >= 15:
                PlatformSession.objects.filter(
                    session_uuid=session_uuid, ended_at__isnull=True, last_seen_at=record.last_seen_at
                ).update(last_seen_at=now)
            return str(session_uuid)
    with transaction.atomic():
        session_uuid = start_platform_session(user, session, now=now)
        if session.session_key:
            session.save()
    return session_uuid


def end_platform_session(user, session_data, end_reason, *, now=None):
    now = now or timezone.now()
    raw_session_uuid = session_data.get(SESSION_KEY) if hasattr(session_data, "get") else None
    try:
        session_uuid = uuid.UUID(str(raw_session_uuid))
    except (ValueError, TypeError, AttributeError):
        return False
    with transaction.atomic():
        record = PlatformSession.objects.select_for_update().filter(
            session_uuid=session_uuid, user=user, ended_at__isnull=True
        ).first()
        if record is None:
            return False
        record.ended_at = now
        record.end_reason = end_reason
        record.save(update_fields=["ended_at", "end_reason"])
        enqueue_event(
            "session_ended", user, session_uuid,
            {"session_uuid": str(session_uuid), "end_reason": end_reason},
            occurred_at=now,
        )
    return True


def touch_platform_session(session_uuid, *, now=None):
    now = now or timezone.now()
    try:
        session_uuid = uuid.UUID(str(session_uuid))
    except (ValueError, TypeError, AttributeError):
        return False
    return bool(PlatformSession.objects.filter(
        session_uuid=session_uuid, ended_at__isnull=True, last_seen_at__lt=now - timedelta(seconds=15)
    ).update(last_seen_at=now))


def record_chat(user, session_uuid, text, floor_code):
    from datetime import timedelta

    from .catalog import floor_uuid
    from .models import ChatMessage, MapFloor

    now = timezone.now()
    with transaction.atomic():
        try:
            floor = MapFloor.objects.get(floor_uuid=floor_uuid(floor_code))
        except MapFloor.DoesNotExist:
            floor = None
        message = ChatMessage.objects.create(
            message_uuid=uuid.uuid4(),
            user=user,
            channel_code="GLOBAL",
            body=text,
            floor=floor,
            sent_at=now,
            expires_at=now + timedelta(days=30),
        )
        enqueue_event(
            "chat_sent", user, session_uuid,
            {"message_uuid": str(message.message_uuid), "channel_code": "GLOBAL",
             "floor_uuid": str(floor.floor_uuid) if floor else None},
            occurred_at=now,
        )
    return str(message.message_uuid)


def record_floor_transfer(user, session_uuid, from_floor_code, to_floor_code, position, observed_at=None):
    from campus.positions import FLOOR_BOUNDS, save_position
    from .catalog import floor_uuid

    now = observed_at or timezone.now()
    if (from_floor_code not in FLOOR_BOUNDS or to_floor_code not in FLOOR_BOUNDS
            or from_floor_code == to_floor_code or not isinstance(position, dict)
            or position.get("floor") != to_floor_code):
        return False
    with transaction.atomic():
        if not save_position(user, position, now, session_uuid=session_uuid):
            return False
        enqueue_event(
            "floor_transferred", user, session_uuid,
            {"from_floor_uuid": str(floor_uuid(from_floor_code)),
             "to_floor_uuid": str(floor_uuid(to_floor_code)), "zone_uuid": None},
            occurred_at=now,
        )
    return True


def record_post_event(event_type, user, session_uuid, post):
    return enqueue_event(
        event_type, user, session_uuid,
        {"post_uuid": str(post.post_uuid), "revision": post.revision, "zone_uuid": None},
    )


def record_comment_event(event_type, user, session_uuid, comment):
    return enqueue_event(
        event_type, user, session_uuid,
        {"comment_uuid": str(comment.comment_uuid), "post_uuid": str(comment.post.post_uuid),
         "parent_comment_uuid": str(comment.parent_id) if comment.parent_id else None,
         "revision": comment.revision},
    )


def record_content_open(user, session_uuid, content):
    return enqueue_event(
        "content_open_requested", user, session_uuid,
        {"content_uuid": str(content.content_uuid), "category_uuid": str(content.category.category_uuid),
         "domain": content.category.domain, "content_kind": content.content_kind,
         "zone_uuid": str(content.zone.zone_uuid), "action": "OPEN_REQUESTED"},
    )
