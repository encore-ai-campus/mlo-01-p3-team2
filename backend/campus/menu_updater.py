"""Daily cafeteria refresh for the single-process local campus server."""
import logging
import threading

from django.conf import settings

from .menu_images import refresh_due, refresh_menu

logger = logging.getLogger(__name__)
_worker = None


def updater_loop(stop):
    while not stop.is_set():
        delay = 30
        try:
            if refresh_due():
                refresh_menu()
        except Exception:
            # Keep the last successfully fetched photo and retry in five minutes.
            logger.exception("Cafeteria photo refresh failed; keeping the previous photo")
            delay = 300
        stop.wait(delay)


def start_menu_updater():
    global _worker
    if _worker is not None and _worker.is_alive():
        return _worker
    # Load settings on the main thread before the worker's first access.
    update_time = settings.BOARD_MENU_UPDATE_TIME
    _worker = threading.Thread(target=updater_loop, args=(threading.Event(),),
                               name="campus-menu-updater", daemon=True)
    _worker.start()
    print(f"Cafeteria photo: daily {update_time} ({settings.BOARD_MENU_TIME_ZONE})", flush=True)
    return _worker
