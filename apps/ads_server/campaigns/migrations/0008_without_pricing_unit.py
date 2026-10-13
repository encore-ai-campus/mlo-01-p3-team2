"""과금 단위 열을 지운다(6-10d, 설계 §10 "구성별 반응 비율 과금" ⑥ — 과금은 정책 버전의 반응 비율로 한다). 빈 DB 전제(계획 §8.4.11 K1)."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0007_creative_library'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='adgroup',
            name='pricing_unit',
        ),
    ]
