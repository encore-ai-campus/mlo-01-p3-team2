"""입찰 정책에 반응 유형별 과금 비율(6-10b). **빈 DB 전제**(계획 §8.4.11 K1): 옛 정책 행을 옮기지 않는다 — 데이터가 있는 DB는 지우고 새로 만든다.
기본값 없는 NOT NULL 열이라 행이 있는 표에서는 비율 제약에서 멈춘다."""
import django.db.models.lookups
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("masters", "0004_media_deactivation")]

    operations = [
        migrations.AddField(model_name="bidpolicy", name="impression_share", field=models.PositiveSmallIntegerField()),
        migrations.AddField(model_name="bidpolicy", name="click_share", field=models.PositiveSmallIntegerField()),
        migrations.AddField(model_name="bidpolicy", name="conversion_share", field=models.PositiveSmallIntegerField()),
        migrations.AddConstraint(
            model_name="bidpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(impression_share__range=(1, 98), click_share__range=(1, 98), conversion_share__range=(1, 98)),
                name="masters_policy_share_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="bidpolicy",
            constraint=models.CheckConstraint(
                condition=django.db.models.lookups.Exact(
                    models.F("impression_share") + models.F("click_share") + models.F("conversion_share"), 100),
                name="masters_policy_shares_sum_100",
            ),
        ),
    ]
