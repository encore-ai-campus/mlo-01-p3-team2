"""개인 광고 기록을 보존하면서 공유 결정과 사용자별 노출을 지원한다."""

import django.db.models.deletion
from django.db import migrations, models


def copy_known_owners(apps, schema_editor):
    """이미 확인된 결정 소유자만 복사한다. 가명에서 원본 사용자를 추정하지 않는다."""
    alias = schema_editor.connection.alias
    Decision = apps.get_model("ad_bridge", "IssuedDecision")
    Impression = apps.get_model("ad_bridge", "Impression")
    owners = Decision.objects.using(alias).filter(
        decision_id=models.OuterRef("decision_id"),
    ).values("owner_id")[:1]
    Impression.objects.using(alias).update(owner_id=models.Subquery(owners))


class Migration(migrations.Migration):
    dependencies = [("ad_bridge", "0003_decision_owner")]

    operations = [
        migrations.AddField(
            model_name="issueddecision", name="audience",
            field=models.CharField(default="individual", editable=False, max_length=16),
        ),
        migrations.AlterField(
            model_name="issueddecision", name="subject_id",
            field=models.UUIDField(default=None, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="impression", name="owner_id",
            field=models.UUIDField(default=None, editable=False, null=True),
        ),
        migrations.RunPython(copy_known_owners, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="impression", name="decision",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="ad_bridge.issueddecision"),
        ),
        migrations.AddConstraint(
            model_name="issueddecision",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(audience="individual", subject_id__isnull=False)
                    | models.Q(audience="shared", owner_id__isnull=True, subject_id__isnull=True)
                ),
                name="ad_bridge_decision_audience",
            ),
        ),
        migrations.AddConstraint(
            model_name="impression",
            constraint=models.UniqueConstraint(fields=("decision", "owner_id"), name="ad_bridge_impression_owner"),
        ),
        migrations.AddConstraint(
            model_name="impression",
            constraint=models.UniqueConstraint(fields=("decision", "subject_id"), name="ad_bridge_impression_subject"),
        ),
    ]
