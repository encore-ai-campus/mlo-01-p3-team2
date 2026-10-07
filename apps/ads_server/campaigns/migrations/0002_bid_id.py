"""버전 행에 UUID 식별자를 붙인다(팀 DRD 의 `ad_bid.bid_id` 와 정합, ads-server-drd §10 D-4 결정 ②).

이미 있는 행은 행마다 새 UUID 로 채운다. 추가 전용 모델이지만 이 일회성 스키마 보강은 과거 행의 **값을 바꾸지 않고 식별자만 더한다**.
(마이그레이션의 과거 모델은 일반 매니저를 쓰므로 update 가 허용된다.)
"""
import uuid

from django.db import migrations, models


def fill(apps, schema_editor):
    Model = apps.get_model("campaigns", "Bid")
    for pk in Model.objects.filter(bid_id__isnull=True).values_list("pk", flat=True):
        Model.objects.filter(pk=pk).update(bid_id=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("campaigns", "0001_initial")]

    operations = [
        migrations.AddField(model_name="bid", name="bid_id", field=models.UUIDField(editable=False, null=True)),
        migrations.RunPython(fill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="bid", name="bid_id", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
        ),
    ]
