from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("community", "0002_raw_event_ids_and_revisions")]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="parent",
            field=models.ForeignKey(
                to="community.comment", to_field="comment_uuid",
                db_column="parent_comment_uuid", null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE, related_name="replies",
            ),
        ),
    ]
