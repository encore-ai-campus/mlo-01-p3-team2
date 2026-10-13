from django.core.management.base import BaseCommand, CommandError

from campus.menu_images import MenuImageError, refresh_menu


class Command(BaseCommand):
    help = "Save the public cafeteria channel's current profile photo."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Refresh immediately, even before the daily time.")

    def handle(self, *args, **options):
        try:
            result = refresh_menu(force=options["force"])
        except (MenuImageError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if result:
            self.stdout.write(self.style.SUCCESS(f"Cafeteria photo saved: {result['updated_at']} ({result['width']}x{result['height']})"))
        else:
            self.stdout.write("Not due, already refreshed, or another refresh is running.")
