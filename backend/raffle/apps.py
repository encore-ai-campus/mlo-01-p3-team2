import os
import sys

from django.apps import AppConfig


class RaffleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "raffle"

    def ready(self):
        if len(sys.argv) > 1 and sys.argv[1] == "runserver":
            if os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv[2:]:
                from .scheduler import start_raffle_scheduler
                start_raffle_scheduler()
