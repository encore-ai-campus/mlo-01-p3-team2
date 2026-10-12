from django.db import migrations, models
from django.utils import timezone


def recover_pending(apps, schema_editor):
    """이전 버전의 미확인 기록도 같은 반응 ID로 다시 처리할 수 있게 만든다."""
    Impression = apps.get_model("ad_bridge", "Impression")
    rows = Impression.objects.using(schema_editor.connection.alias)
    now = timezone.now()
    rows.filter(delivery_state="UNCONFIRMED").update(
        attempts=1, last_error="legacy_unconfirmed", next_attempt_at=now,
    )
    rows.filter(delivery_state="SENDING").update(
        attempts=1, last_error="legacy_unconfirmed", lease_expires_at=now,
    )


class Migration(migrations.Migration):
    dependencies = [("ad_bridge", "0001_initial")]
    operations = [
        migrations.AddField(model_name="impression", name="attempts", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="impression", name="next_attempt_at", field=models.DateTimeField(null=True, default=None)),
        migrations.AddField(model_name="impression", name="last_error", field=models.CharField(max_length=64, null=True, default=None)),
        migrations.AddField(model_name="impression", name="last_http_status", field=models.PositiveSmallIntegerField(null=True, default=None)),
        migrations.AddField(model_name="impression", name="lease_token", field=models.UUIDField(null=True, default=None, editable=False)),
        migrations.AddField(model_name="impression", name="lease_expires_at", field=models.DateTimeField(null=True, default=None)),
        migrations.AddIndex(model_name="impression", index=models.Index(fields=["delivery_state", "next_attempt_at"], name="ad_bridge_retry_due")),
        migrations.AddIndex(model_name="impression", index=models.Index(fields=["delivery_state", "lease_expires_at"], name="ad_bridge_lease_due")),
        migrations.RunPython(recover_pending, migrations.RunPython.noop),
    ]
