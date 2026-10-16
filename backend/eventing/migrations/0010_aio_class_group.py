from django.db import migrations
from uuid import UUID


AIO_ID = UUID("c25cbb3b-c4df-4234-a0e6-f1385ea7fb94")


def add_aio(apps, schema_editor):
    Group = apps.get_model("eventing", "ClassGroup")
    Group.objects.using(schema_editor.connection.alias).get_or_create(
        code="aio-4", defaults={"class_group_uuid": AIO_ID, "name": "AIO 4기", "status": "ACTIVE"},
    )


class Migration(migrations.Migration):
    dependencies = [("eventing", "0009_preserve_json_precision")]
    operations = [migrations.RunPython(add_aio, migrations.RunPython.noop)]
