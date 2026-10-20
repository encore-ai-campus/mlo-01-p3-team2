"""Classify games as leisure while preserving their category identities."""
from django.db import migrations


def move_games_to_rest(apps, schema_editor):
    Category = apps.get_model("eventing", "ContentCategory")
    alias = schema_editor.connection.alias if schema_editor is not None else "default"
    Category.objects.using(alias).filter(code="game").update(domain="REST")


def restore_previous_domain(apps, schema_editor):
    Category = apps.get_model("eventing", "ContentCategory")
    alias = schema_editor.connection.alias if schema_editor is not None else "default"
    Category.objects.using(alias).filter(code="game").update(domain="LEARNING")


class Migration(migrations.Migration):
    dependencies = [("eventing", "0003_catalog_uuid4")]
    operations = [migrations.RunPython(move_games_to_rest, restore_previous_domain)]
