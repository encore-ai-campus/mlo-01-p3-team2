"""내부 소유자를 추가하고 기존 결정·반응의 전송 내용은 보존한다."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ad_bridge", "0002_impression_retry")]

    operations = [
        # 기존 subject_id만으로 원본 소유자를 확정할 수 없으므로 자동 채우기를 하지 않는다.
        migrations.AddField(
            model_name="issueddecision",
            name="owner_id",
            field=models.UUIDField(default=None, editable=False, null=True),
        ),
    ]
