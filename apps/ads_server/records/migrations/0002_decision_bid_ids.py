"""결정이 선택한 입찰·정책 버전 행의 UUID 를 함께 기록한다(팀 DRD 의 `selected_bid_id`·`selected_bid_policy_id`, ads-server-drd §10 D-4).

이미 있는 결정은 자연 키((광고그룹, 입찰 버전), (슬롯, 정책 버전))로 해당 행을 찾아 채운다. 버전 행은 추가 전용이라 반드시 있다.
결정의 다른 값은 바꾸지 않는다(식별자만 더한다).
"""
from django.db import migrations, models
from django.db.models import Q


def fill(apps, schema_editor):
    Decision = apps.get_model("records", "Decision")
    Bid = apps.get_model("campaigns", "Bid")
    BidPolicy = apps.get_model("masters", "BidPolicy")
    for d in Decision.objects.filter(creative_id__isnull=False).only("pk", "ad_group_id", "bid_version", "slot_id", "policy_version"):
        bid_id = Bid.objects.get(ad_group_id=d.ad_group_id, bid_version=d.bid_version).bid_id
        policy_id = BidPolicy.objects.get(slot_id=d.slot_id, policy_version=d.policy_version).bid_policy_id
        Decision.objects.filter(pk=d.pk).update(bid_id=bid_id, bid_policy_id=policy_id)


CHOSEN = ("owner_id", "campaign_id", "ad_group_id", "creative_id", "pricing_unit", "bid_amount", "applied_amount",
          "bid_version", "policy_version", "bid_id", "bid_policy_id", "snapshot")


class Migration(migrations.Migration):
    dependencies = [
        ("records", "0001_initial"),
        ("campaigns", "0002_bid_id"),
        ("masters", "0002_bid_policy_id"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="decision", name="records_decision_chosen_all_or_none"),
        migrations.AddField(model_name="decision", name="bid_id", field=models.UUIDField(blank=True, null=True)),
        migrations.AddField(model_name="decision", name="bid_policy_id", field=models.UUIDField(blank=True, null=True)),
        migrations.RunPython(fill, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="decision",
            constraint=models.CheckConstraint(
                condition=Q(**{f"{c}__isnull": True for c in CHOSEN}) | Q(**{f"{c}__isnull": False for c in CHOSEN}),
                name="records_decision_chosen_all_or_none",
            ),
        ),
    ]
