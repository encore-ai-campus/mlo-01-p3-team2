"""Optional event times live in the DB; no recurring time is hardcoded."""
import logging
import threading

from django.apps import apps
from django.conf import settings
from django.db import close_old_connections, connections

logger = logging.getLogger(__name__)
_worker = None


def scheduler_loop(stop):
    while not apps.ready:
        if stop.wait(1):
            return
    from config.connections import keep_thread_connection
    from .service import advance_due
    from .survey import poll_due
    keep_thread_connection()  # 1초마다 살피되 연결은 이어 쓴다(예전: 살필 때마다 새 연결, 계획 4d)
    while not stop.is_set():
        try:
            close_old_connections()  # 오래됐거나 오류가 난 연결만 닫는다
            poll_due()
            advance_due()
        except Exception:
            connections.close_all()
            logger.exception("Rooftop event scheduling failed; retrying")
        stop.wait(settings.CAMPUS_RAFFLE_POLL_SECONDS)


def start_raffle_scheduler():
    global _worker
    if not settings.CAMPUS_RAFFLE_SCHEDULER_ENABLED:
        return None
    if _worker is not None and _worker.is_alive():
        return _worker
    _worker = threading.Thread(target=scheduler_loop, args=(threading.Event(),), name="campus-raffle", daemon=True)
    _worker.start()
    return _worker
