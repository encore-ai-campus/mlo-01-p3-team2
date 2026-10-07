"""버전 행 UUID 보강 마이그레이션(masters 0002, campaigns 0002, records 0002)이 이미 있는 데이터를 올바르게 채우는지.

추가 전용 기록을 건드리는 일회성 작업이라 실제 데이터 모양으로 확인한다: 이전 스키마에서 행을 만들고 → 마이그레이션 → 값 확인.
"""
import uuid
from datetime import datetime, timezone

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

OLD = [("masters", "0001_initial"), ("campaigns", "0001_initial"), ("records", "0001_initial")]
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


class UuidBackfillMigrationTests(TransactionTestCase):
    def test_existing_rows_get_unique_uuids_and_decisions_point_to_the_exact_versions(self):
        executor = MigrationExecutor(connection)
        executor.migrate(OLD)
        old = executor.loader.project_state(OLD).apps

        User = old.get_model("foundation", "User")
        owner = User.objects.create(username="mig_owner", password="x", nickname="n", class_label="1")
        media = old.get_model("masters", "Media").objects.create(name="m")
        slot = old.get_model("masters", "Slot").objects.create(media=media, name="s", pricing_unit="IMPRESSION")
        Policy = old.get_model("masters", "BidPolicy")
        for version, cap in ((1, 50), (2, 60)):
            Policy.objects.create(slot=slot, policy_version=version, floor_amount=10, base_amount=20, cap_amount=cap, changed_by=owner.pk, reason="r")
        campaign = old.get_model("campaigns", "Campaign").objects.create(owner=owner, name="c", starts_at=NOW, daily_budget=100)
        group = old.get_model("campaigns", "AdGroup").objects.create(campaign=campaign, name="g", pricing_unit="IMPRESSION")
        Bid = old.get_model("campaigns", "Bid")
        for version, amount in ((1, 30), (2, 35)):
            Bid.objects.create(ad_group=group, bid_version=version, amount=amount, created_by=owner.pk)
        Decision = old.get_model("records", "Decision")
        chosen = Decision.objects.create(
            media_id=media.pk, slot_id=slot.pk, decided_at=NOW, owner_id=owner.pk, campaign_id=campaign.pk, ad_group_id=group.pk,
            creative_id=uuid.uuid4(), pricing_unit="IMPRESSION", bid_amount=35, applied_amount=35, bid_version=2, policy_version=1,
            snapshot={"title": "t", "redirect_url": "https://a.example", "image_name": "x"}, selection_policy="highest-bid/v1", candidate_count=1,
        )
        empty = Decision.objects.create(media_id=media.pk, slot_id=slot.pk, decided_at=NOW, selection_policy="highest-bid/v1", candidate_count=0)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

        from campaigns.models import Bid as NewBid
        from masters.models import BidPolicy as NewPolicy
        from records.models import Decision as NewDecision

        policy_ids = list(NewPolicy.objects.values_list("bid_policy_id", flat=True))
        bid_ids = list(NewBid.objects.values_list("bid_id", flat=True))
        self.assertEqual((len(set(policy_ids)), len(set(bid_ids))), (2, 2))  # 행마다 서로 다른 UUID
        self.assertTrue(all(isinstance(v, uuid.UUID) for v in policy_ids + bid_ids))
        d = NewDecision.objects.get(pk=chosen.pk)
        self.assertEqual(d.bid_id, NewBid.objects.get(ad_group_id=group.pk, bid_version=2).bid_id)  # 판정에 쓴 바로 그 버전
        self.assertEqual(d.bid_policy_id, NewPolicy.objects.get(slot_id=slot.pk, policy_version=1).bid_policy_id)
        self.assertEqual((d.applied_amount, d.bid_version, d.policy_version), (35, 2, 1))  # 다른 값은 그대로
        e = NewDecision.objects.get(pk=empty.pk)
        self.assertEqual((e.bid_id, e.bid_policy_id), (None, None))  # 광고 없음은 그대로 비어 있다
