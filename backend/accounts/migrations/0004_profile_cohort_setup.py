from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_profile_last_position")]
    operations = [
        migrations.AddField(
            model_name="profile", name="cohort",
            field=models.CharField(blank=True, default="", max_length=6, choices=[
                ("mlo-1", "MLO 1기"), ("mlo-2", "MLO 2기"), ("mlo-3", "MLO 3기"),
                ("skn-34", "SKN 34기"), ("skn-36", "SKN 36기"),
            ]),
        ),
        migrations.AddField(
            model_name="profile", name="setup_complete", field=models.BooleanField(default=True),
        ),
    ]
