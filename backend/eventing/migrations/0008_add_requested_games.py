"""Add eight requested arcade games while preserving published identities."""
from uuid import UUID

from django.db import migrations


GAMES = (
    ("tetris", "44a6195f-898f-4200-98e0-380749e1985c", "테트리스", "https://vidkidz.tistory.com/4015"),
    ("worlds-hardest-game", "11a19b7a-adee-48a0-b5f1-89b3de8fda6d", "세상에서 가장 어려운 게임", "https://vidkidz.tistory.com/12"),
    ("bamboo-master", "95535f67-fc1f-43cc-8d25-557ca4afbce1", "죽림고수", "https://vidkidz.tistory.com/107"),
    ("sword-upgrade", "4e69fdc3-7004-43ff-a4b8-38c58867d8fe", "검 강화하기", "https://vidkidz.tistory.com/5291"),
    ("walk-the-stork", "93d9872c-75ce-4669-ba8b-6b6603e19ffe", "황새와 오래 걷기", "https://vidkidz.tistory.com/2825"),
    ("isaac", "f23c08cd-c9d4-49be-b8ca-a639f60cc080", "아이작", "https://vidkidz.tistory.com/6014"),
    ("paladog", "2a473609-51c6-4c90-b899-769767bf0287", "팔라독", "https://vidkidz.tistory.com/5298"),
    ("solitaire", "daaa0e91-113a-4b88-a1e6-653446aba1b8", "솔리테어", "https://thesolitaire.com/ko"),
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
    dependencies = [("eventing", "0007_learning_catalog")]
    # Retain rows on rollback so emitted content UUIDs remain resolvable.
    operations = [migrations.RunPython(add_games, migrations.RunPython.noop)]
