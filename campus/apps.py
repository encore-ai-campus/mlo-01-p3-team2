from django.apps import AppConfig
import os
import sys


class CampusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "campus"

    def ready(self):
        # Support ordinary runserver launches while keeping migrations, tests,
        # and the autoreload parent free of background work.
        if len(sys.argv) > 1 and sys.argv[1] == "runserver":
            if os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv[2:]:
                from .menu_updater import start_menu_updater
                start_menu_updater()
