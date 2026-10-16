from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_profile_guide_completed")]
    operations = [migrations.AlterField(
        model_name="profile", name="cohort",
        field=models.CharField(blank=True, default="", max_length=6, choices=[
            ("mlo-1", "MLO 1기"), ("mlo-2", "MLO 2기"), ("mlo-3", "MLO 3기"),
            ("skn-34", "SKN 34기"), ("skn-36", "SKN 36기"), ("aio-4", "AIO 4기"),
        ]),
    )]
