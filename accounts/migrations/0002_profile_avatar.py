from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="profile",
            name="avatar",
            field=models.CharField(
                choices=[("male-1", "민트 후드"), ("male-2", "보라색 재킷"), ("female-1", "보라색 후드"), ("female-2", "초록색 카디건")],
                default="male-1",
                max_length=8,
            ),
        ),
    ]
