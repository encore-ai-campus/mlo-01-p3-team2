import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="IssuedDecision",
            fields=[
                ("decision_id", models.UUIDField(primary_key=True, editable=False, serialize=False)),
                ("subject_id", models.UUIDField(editable=False)),
                ("slot_id", models.UUIDField(editable=False)),
                ("decided_at", models.DateTimeField(editable=False)),
                ("has_ad", models.BooleanField(editable=False)),
            ],
        ),
        migrations.CreateModel(
            name="Impression",
            fields=[
                ("reaction_id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("subject_id", models.UUIDField(editable=False)),
                ("occurred_at", models.CharField(max_length=64, editable=False)),
                ("delivery_state", models.CharField(max_length=16, default="SENDING")),
                ("status", models.CharField(max_length=16, null=True, default=None)),
                ("reason_code", models.TextField(null=True, default=None)),
                ("request_id", models.TextField(null=True, default=None)),
                ("decision", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="ad_bridge.issueddecision")),
            ],
        ),
    ]
