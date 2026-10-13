"""소재를 광고주 소유 목록으로(6-9c, 설계 §10 "소재 목록"). 기존 소재는 소유자 = 그 캠페인의 주인, 붙어 있던 광고그룹에 연결·선택으로 옮긴다."""
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def move_creatives(apps, schema_editor):
    Creative = apps.get_model("campaigns", "Creative")
    AdGroup = apps.get_model("campaigns", "AdGroup")
    AdGroupCreative = apps.get_model("campaigns", "AdGroupCreative")
    for creative in Creative.objects.select_related("ad_group__campaign").order_by("created_at"):
        group = creative.ad_group
        Creative.objects.filter(pk=creative.pk).update(owner_id=group.campaign.owner_id)
        AdGroupCreative.objects.create(ad_group_id=group.pk, creative_id=creative.pk, linked_at=creative.created_at)
        AdGroup.objects.filter(pk=group.pk, creative__isnull=True).update(creative_id=creative.pk)  # 먼저 만든 것을 선택(V1 은 하나뿐이었다)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('campaigns', '0006_creative_without_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='creative',
            name='owner',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='creatives', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='creative',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='AdGroupCreative',
            fields=[
                ('link_id', models.UUIDField(default=uuid.uuid7, editable=False, primary_key=True, serialize=False)),
                ('linked_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('ad_group', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='creative_links', to='campaigns.adgroup')),
                ('creative', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ad_group_links', to='campaigns.creative')),
            ],
            options={
                'db_table': 'campaigns_ad_group_creative',
                'constraints': [models.UniqueConstraint(fields=('ad_group', 'creative'), name='campaigns_ad_group_creative_unique')],
            },
        ),
        migrations.AddField(
            model_name='adgroup',
            name='creative',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='campaigns.creative'),
        ),
        migrations.AddField(
            model_name='adgroup',
            name='request_key',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddConstraint(
            model_name='adgroup',
            constraint=models.UniqueConstraint(fields=('request_key',), name='campaigns_ad_group_once_per_request'),
        ),
        migrations.RunPython(move_creatives, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='creative',
            name='owner',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='creatives', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RemoveField(
            model_name='creative',
            name='ad_group',
        ),
    ]
