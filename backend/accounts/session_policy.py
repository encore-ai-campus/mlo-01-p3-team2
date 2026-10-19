"""Fixed login lifetime and real-activity timeout for database-backed sessions."""
from datetime import datetime, timedelta, timezone as datetime_timezone
from importlib import import_module
import logging
import math

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.db import transaction
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils import timezone

from campus import session_registry
from campus.positions import save_position
from eventing.events import SESSION_KEY as PLATFORM_SESSION_KEY, end_platform_session

STARTED = "_campus_login_started"
ACTIVITY = "_campus_last_activity"
logger = logging.getLogger(__name__)


def start_login(session, user=None):
    now = timezone.now()
    session[STARTED] = session[ACTIVITY] = now.timestamp()
    session.set_expiry(now + timedelta(seconds=settings.CAMPUS_LOGIN_MAX_AGE_SECONDS))
    if user is not None:
        from .single_login import replace_login
        replace_login(session, user, now)


def status(data, now, deadline=None):
    absolute = data[STARTED] + settings.CAMPUS_LOGIN_MAX_AGE_SECONDS
    if deadline is not None:
        absolute = min(absolute, deadline)
    idle = data[ACTIVITY] + settings.CAMPUS_LOGIN_IDLE_TIMEOUT_SECONDS
    reason = "maximum" if now >= absolute else "idle" if now >= idle else None
    return {"authenticated": reason is None, "reason": reason, "serverNow": now * 1000,
            "absoluteExpiresAt": absolute * 1000, "idleExpiresAt": idle * 1000,
            "expiresAt": min(absolute, idle) * 1000, "warningSeconds": settings.CAMPUS_LOGIN_WARNING_SECONDS}


def invalid_status(reason="signed_out"):
    return {"authenticated": False, "reason": reason, "serverNow": timezone.now().timestamp() * 1000}


def notify_expiry(key, reason):
    layer = get_channel_layer()
    if layer:
        async_to_sync(layer.group_send)(session_registry.session_group(key),
                                       {"type": "session.expired", "reason": reason})


def expire_record(record, data, reason, *, now=None, notify=True):
    """Save the newest accepted position, delete exactly this revision, then notify sockets."""
    snapshot = session_registry.latest(record.session_key, data.get(SESSION_KEY))
    if snapshot:
        user = get_user_model().objects.filter(pk=data[SESSION_KEY], is_active=True).first()
        if user:
            try:
                save_position(user, *snapshot, session_uuid=data.get(PLATFORM_SESSION_KEY))
            except DatabaseError:
                logger.exception("Could not save the final position before session expiry")
    deleted = 0
    with transaction.atomic():
        deleted, _ = Session.objects.filter(
            session_key=record.session_key, session_data=record.session_data
        ).delete()
        if deleted:
            user = get_user_model().objects.filter(pk=data[SESSION_KEY], is_active=True).first()
            if user:
                end_platform_session(user, data, "SESSION_EXPIRED", now=now)
    if not deleted:
        return False  # A second tab updated activity; re-read instead of deleting a fresh session.
    if notify:
        notify_expiry(record.session_key, reason)
    return True


def check_session(key, *, touch=False, force=False, now=None):
    if not key:
        return invalid_status()
    now = timezone.now().timestamp() if now is None else now
    store = import_module(settings.SESSION_ENGINE).SessionStore()
    for _ in range(5):
        record = Session.objects.filter(session_key=key).first()
        if record is None:
            return invalid_status()
        data = store.decode(record.session_data)
        if SESSION_KEY not in data:
            return invalid_status("anonymous")
        legacy = STARTED not in data and ACTIVITY not in data
        if legacy:
            data[STARTED] = data[ACTIVITY] = now
        valid = all(type(data.get(field)) in (int, float) and math.isfinite(data[field])
                    and data[field] <= now + 60 for field in (STARTED, ACTIVITY))
        state = status(data, now, record.expire_date.timestamp()) if valid else invalid_status("invalid")
        if state["authenticated"]:
            from .single_login import session_is_current
            if not session_is_current(key, data[SESSION_KEY]):
                state = invalid_status("replaced")
        if not state["authenticated"]:
            if expire_record(record, data, state["reason"], now=datetime.fromtimestamp(now, datetime_timezone.utc)):
                return state
            continue
        changed = legacy
        if touch and (force or now - data[ACTIVITY] >= settings.CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS):
            data[ACTIVITY] = max(data[ACTIVITY], now)
            changed = True
        if changed:
            deadline = min(record.expire_date, datetime.fromtimestamp(
                data[STARTED] + settings.CAMPUS_LOGIN_MAX_AGE_SECONDS, datetime_timezone.utc))
            data["_session_expiry"] = deadline.isoformat()
            updated = Session.objects.filter(session_key=key, session_data=record.session_data).update(
                session_data=store.encode(data), expire_date=deadline)
            if not updated:
                continue
        return status(data, now, record.expire_date.timestamp())
    # A busy session can retry; never revive a deleted key or expire from an obsolete revision.
    return invalid_status("retry")


class CampusSessionPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = request.session.session_key
        request.campus_session_status = check_session(key)
        if key and not request.campus_session_status["authenticated"] and request.campus_session_status["reason"] not in {"retry", "anonymous"}:
            request.session.flush()
        response = self.get_response(request)
        # Status polls, socket pings, failed/CSRF-rejected requests and logout never extend activity.
        excluded = ("/accounts/session/", "/accounts/login/", "/accounts/signup/", "/accounts/logout/", "/static/")
        user_request = request.method not in {"GET", "HEAD", "OPTIONS"} or request.path in {"/", "/accounts/setup/", "/accounts/nickname/"}
        if (key and response.status_code < 400 and request.user.is_authenticated
                and user_request and not request.path.startswith(excluded)):
            check_session(key, touch=True)
        return response


def session_context(request):
    session = getattr(request, "session", None)
    if session is None or not request.user.is_authenticated:
        return {}
    return {"session_policy_config": {
        "statusUrl": reverse("accounts:session-status"), "activityUrl": reverse("accounts:session-activity"),
        "logoutUrl": reverse("accounts:logout"), "loginUrl": reverse("accounts:login"),
        "csrfToken": get_token(request),
        "activityIntervalSeconds": settings.CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS,
        "status": getattr(request, "campus_session_status", None) or check_session(session.session_key),  # 미들웨어가 이 요청에서 구한 상태(계획 4e)
    }}
