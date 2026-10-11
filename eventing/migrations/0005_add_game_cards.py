"""Register additional leisure games without changing existing identities."""
from uuid import UUID

from django.db import migrations


GAMES = (
    ("dad-and-me", "b6c5ea3c-cd02-4537-b764-9a2b3bc0e325", "아빠와 나", "https://vidkidz.tistory.com/605#waflashContainer"),
    ("minesweeper", "26fa843f-7b89-46ed-9d6d-ff9aecf2cca2", "지뢰찾기", "https://minesweeper.one/%EC%A7%80%EB%A2%B0%EC%B0%BE%EA%B8%B0/"),
)


def add_games(apps, schema_editor):
    alias = schema_editor.connection.alias if schema_editor is not None else "default"
    Category = apps.get_model("eventing", "ContentCategory")
    Zone = apps.get_model("eventing", "MapZone")
    Content = apps.get_model("eventing", "ContentItem")
    category = Category.objects.using(alias).get(code="game")
    zone = Zone.objects.using(alias).get(code="game-booth")
    for code, identity, title, url in GAMES:
        Content.objects.using(alias).get_or_create(code=code, defaults={
            "content_uuid": UUID(identity), "category_id": category.pk, "zone_id": zone.pk,
            "title": title, "content_kind": "EXTERNAL_LINK", "external_url": url,
            "status": "ACTIVE", "published_at": None,
        })


class Migration(migrations.Migration):
    dependencies = [("eventing", "0004_game_category_rest")]
    # Keep catalog rows on rollback so previously emitted UUID references survive.
    operations = [migrations.RunPython(add_games, migrations.RunPython.noop)]
