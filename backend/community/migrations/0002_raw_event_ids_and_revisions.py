import uuid

from django.db import migrations, models


def populate_board_uuids(apps, schema_editor):
    for model_name, field_name in (("Post", "post_uuid"), ("Comment", "comment_uuid")):
        Model = apps.get_model("community", model_name)
        for row in Model.objects.filter(**{f"{field_name}__isnull": True}).only("pk").iterator():
            Model.objects.filter(pk=row.pk, **{f"{field_name}__isnull": True}).update(**{field_name: uuid.uuid4()})


class Migration(migrations.Migration):
    dependencies = [("community", "0001_initial")]

    operations = [
        migrations.AddField("post", "post_uuid", models.UUIDField(null=True, editable=False)),
        migrations.AddField("post", "revision", models.PositiveIntegerField(default=1)),
        migrations.AddField("post", "deleted_at", models.DateTimeField(null=True, blank=True)),
        migrations.AddField("comment", "comment_uuid", models.UUIDField(null=True, editable=False)),
        migrations.AddField("comment", "revision", models.PositiveIntegerField(default=1)),
        migrations.AddField("comment", "deleted_at", models.DateTimeField(null=True, blank=True)),
        migrations.RunPython(populate_board_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="post", name="post_uuid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="comment", name="comment_uuid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
