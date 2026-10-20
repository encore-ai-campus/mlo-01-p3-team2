"""Once-a-day expired-session cleanup for the local runserver process."""
from datetime import time
import json
import logging
from pathlib import Path
import threading

from django.conf import settings
from django.apps import apps
from django.core.management import call_command
from django.db import close_old_connections, connections
from django.utils import timezone

logger = logging.getLogger(__name__)
_worker = None


def cleanup_due(now, path):
    local = timezone.localtime(now)
    schedule = time.fromisoformat(settings.CAMPUS_SESSION_CLEANUP_TIME)
    try:
        day = json.loads(path.read_text(encoding="utf-8"))["completed_day"]
    except (OSError, ValueError, KeyError, TypeError):
        return True  # First boot also clears old sessions left by earlier versions.
    return day < local.date().isoformat() and local.time().replace(tzinfo=None) >= schedule


def run_due_cleanup(now=None, path=None):
    now = now or timezone.now()
    path = Path(path or settings.CAMPUS_SESSION_CLEANUP_STATE)
    if not cleanup_due(now, path):
        return False
    # Active sockets save their latest accepted positions before Django removes the rows.
    from .session_policy import check_session
    # Offline authenticated sessions also need an end event before their rows
    # disappear. This checks both the fixed lifetime and the activity deadline.
    from django.contrib.sessions.models import Session
    for key in Session.objects.order_by("session_key").values_list("session_key", flat=True).iterator(chunk_size=500):
        check_session(key, now=now.timestamp())
    call_command("clearsessions", verbosity=0)
    from eventing.models import ChatMessage
    removed_chat, _ = ChatMessage.objects.filter(expires_at__lte=now).delete()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"completed_day": timezone.localtime(now).date().isoformat(),
                                     "completed_at": now.isoformat()}), encoding="utf-8")
    temporary.replace(path)
    logger.info("Expired login sessions and %s expired chat rows cleared", removed_chat)
    return True


def cleanup_loop(stop):
    # The shared-server launcher starts workers just before Django finishes setup.
    while not apps.ready:
        if stop.wait(1):
            return
    while not stop.is_set():
        try:
            close_old_connections()
            run_due_cleanup()
        except Exception:
            logger.exception("Expired-session cleanup failed; retrying later")
        finally:
            connections.close_all()
        stop.wait(60)


def start_session_cleanup():
    global _worker
    if not settings.CAMPUS_SESSION_CLEANUP_ENABLED:
        return None
    if _worker is not None and _worker.is_alive():
        return _worker
    time.fromisoformat(settings.CAMPUS_SESSION_CLEANUP_TIME)
    _worker = threading.Thread(target=cleanup_loop, args=(threading.Event(),),
                               name="campus-session-cleanup", daemon=True)
    _worker.start()
    return _worker
