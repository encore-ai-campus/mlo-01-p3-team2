"""campaigns 0003: 이미 있는 소재의 현재 이미지를 보유 관계(CreativeImage)에 채운다."""
from datetime import datetime, timezone

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

OLD = [("campaigns", "0002_bid_id"), ("masters", "0002_bid_policy_id"), ("records", "0002_decision_bid_ids")]
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


class CreativeImageBackfillTests(TransactionTestCase):
    def test_existing_creatives_get_their_current_image_as_held(self):
        executor = MigrationExecutor(connection)
        executor.migrate(OLD)
        old = executor.loader.project_state(OLD).apps
        User = old.get_model("foundation", "User")
        owner = User.objects.create(username="mig_img", password="x", nickname="n", class_label="1")
        campaign = old.get_model("campaigns", "Campaign").objects.create(owner=owner, name="c", starts_at=NOW, daily_budget=100)
        group = old.get_model("campaigns", "AdGroup").objects.create(campaign=campaign, name="g", pricing_unit="IMPRESSION")
        creative = old.get_model("campaigns", "Creative").objects.create(
            ad_group=group, title="t", redirect_url="https://a.example", image_name="a" * 64 + ".png", image_bytes=123,
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

        from campaigns.models import CreativeImage

        held = CreativeImage.objects.get()
        self.assertEqual((held.creative_id, held.image_name, held.image_bytes), (creative.pk, "a" * 64 + ".png", 123))
        from campaigns import api

        self.assertTrue(api.is_asset_servable("a" * 64 + ".png"))  # 기존 소재의 이미지는 마이그레이션 뒤에도 서빙된다
