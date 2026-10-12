import uuid

from django.db import migrations, models


def populate_user_uuids(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    for profile in Profile.objects.filter(user_uuid__isnull=True).only("pk").iterator():
        Profile.objects.filter(pk=profile.pk, user_uuid__isnull=True).update(user_uuid=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_profile_cohort_setup")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="user_uuid",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(populate_user_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="profile",
            name="user_uuid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
