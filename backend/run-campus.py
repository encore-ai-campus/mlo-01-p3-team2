"""Start the shared local campus and display addresses for classmates."""
import argparse
import os
from pathlib import Path
import sys

from config.network import local_lan_addresses


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int, default=9003)
    parser.add_argument("--bind", default="127.0.0.1")
    options, server_args = parser.parse_known_args()
    if not 1 <= options.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    port = options.port
    root = Path(__file__).resolve().parent
    os.chdir(root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if os.environ.get("RUN_MAIN") != "true":
        print(f"Backend: http://{options.bind}:{port}/", flush=True)
        print("Keep this window open. Press Ctrl+C to stop.", flush=True)
    from django.core.management import execute_from_command_line
    # Only the serving child owns the updater; the autoreload parent never does.
    if os.environ.get("RUN_MAIN") == "true" or "--noreload" in server_args:
        from campus.menu_updater import start_menu_updater
        start_menu_updater()
        from accounts.session_cleanup import start_session_cleanup
        start_session_cleanup()
        from raffle.scheduler import start_raffle_scheduler
        start_raffle_scheduler()
    execute_from_command_line([str(root / "manage.py"), "runserver", f"{options.bind}:{port}", *server_args])
