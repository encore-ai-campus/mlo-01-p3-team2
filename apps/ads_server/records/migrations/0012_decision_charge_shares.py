"""결정에 반응 유형별 과금 비율을 남기고 과금 단위 열을 지운다(6-10c, 설계 §10 "구성별 반응 비율 과금"). **빈 DB 전제**(계획 §8.4.11 K1): 옛 결정을 옮기지 않는다."""

import django.db.models.expressions
import django.db.models.lookups
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0011_hop_window_indexes'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='decision',
            name='records_decision_chosen_all_or_none',
        ),
        migrations.AddField(
            model_name='decision',
            name='click_share',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='decision',
            name='conversion_share',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='decision',
            name='impression_share',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='decision',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('ad_group_id__isnull', True), ('applied_amount__isnull', True), ('bid_amount__isnull', True), ('bid_id__isnull', True), ('bid_policy_id__isnull', True), ('bid_version__isnull', True), ('campaign_id__isnull', True), ('click_share__isnull', True), ('conversion_share__isnull', True), ('creative_id__isnull', True), ('impression_share__isnull', True), ('owner_id__isnull', True), ('policy_version__isnull', True), ('snapshot__isnull', True)), models.Q(('ad_group_id__isnull', False), ('applied_amount__isnull', False), ('bid_amount__isnull', False), ('bid_id__isnull', False), ('bid_policy_id__isnull', False), ('bid_version__isnull', False), ('campaign_id__isnull', False), ('click_share__isnull', False), ('conversion_share__isnull', False), ('creative_id__isnull', False), ('impression_share__isnull', False), ('owner_id__isnull', False), ('policy_version__isnull', False), ('snapshot__isnull', False)), _connector='OR'), name='records_decision_chosen_all_or_none'),
        ),
        migrations.AddConstraint(
            model_name='decision',
            constraint=models.CheckConstraint(condition=models.Q(('impression_share__isnull', True), models.Q(('click_share__range', (1, 98)), ('conversion_share__range', (1, 98)), ('impression_share__range', (1, 98))), _connector='OR'), name='records_decision_share_range'),
        ),
        migrations.AddConstraint(
            model_name='decision',
            constraint=models.CheckConstraint(condition=models.Q(('impression_share__isnull', True), django.db.models.lookups.Exact(django.db.models.expressions.CombinedExpression(django.db.models.expressions.CombinedExpression(models.F('impression_share'), '+', models.F('click_share')), '+', models.F('conversion_share')), 100), _connector='OR'), name='records_decision_shares_sum_100'),
        ),
        migrations.RemoveField(
            model_name='decision',
            name='pricing_unit',
        ),
    ]
