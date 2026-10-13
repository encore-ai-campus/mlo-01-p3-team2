"""입찰 정책의 하한 최소 100(6-10c, 설계 §10 "구성별 반응 비율 과금"). 빈 DB 전제(계획 §8.4.11 K1)."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("masters", "0005_bid_policy_shares")]

    operations = [
        migrations.AddConstraint(
            model_name="bidpolicy", constraint=models.CheckConstraint(condition=models.Q(floor_amount__gte=100), name="masters_policy_floor_min"),
        ),
    ]
