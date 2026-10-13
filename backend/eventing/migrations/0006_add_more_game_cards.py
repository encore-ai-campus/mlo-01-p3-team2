"""Register four more leisure games without changing existing identities."""
from uuid import UUID

from django.db import migrations


GAMES = (
    ("fruit-box", "6151bdea-7ee1-4009-b01b-400e585c2a53", "사과게임", "https://www.gamesaien.com/game/fruit_box_a/"),
    ("bubble-shooter", "e03b368a-2daf-48d3-b6ee-f456ec416763", "버블슈터", "https://vidkidz.tistory.com/1514#waflashContainer"),
    ("suika", "c03bb858-4962-460a-93e2-4e70d4db0485", "수박게임", "https://playsuikagame.com/ko"),
    ("flashman", "c44c5181-3756-4871-8f65-3f6a849e0075", "후레시맨", "https://vidkidz.tistory.com/54#waflashContainer"),
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
    dependencies = [("eventing", "0005_add_game_cards")]
    # Keep catalog rows on rollback so previously emitted UUID references survive.
    operations = [migrations.RunPython(add_games, migrations.RunPython.noop)]
