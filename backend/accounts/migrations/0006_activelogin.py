from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_profile_user_uuid"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ActiveLogin",
            fields=[
                ("user", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, primary_key=True,
                    related_name="active_campus_login", serialize=False,
                    to=settings.AUTH_USER_MODEL,
                )),
                ("session_key", models.CharField(max_length=40, unique=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
