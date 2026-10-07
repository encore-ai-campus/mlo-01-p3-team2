"""이미지 보유 관계의 마이그레이션: campaigns 0003(현재 이미지) + records 0003(교체된 과거 이미지 복구).

구 버전에서 만든 데이터로 확인한다: 결정 생성 → 이미지 교체 → 마이그레이션 → 과거 URL 이 열리고 보유량에 포함된다.
"""
import io
import uuid
from datetime import datetime, timezone

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings

from assets.api import store, validate_image
from tests import image_factory

OLD = [("campaigns", "0002_bid_id"), ("masters", "0002_bid_policy_id"), ("records", "0002_decision_bid_ids"), ("foundation", "0003_auditlog")]
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def stored(color):
    image = validate_image(io.BytesIO(image_factory.png_bytes(color=color)))
    store(image)
    return image.name, len(image.data)


class CreativeImageMigrationTests(TransactionTestCase):
    def migrate_to_latest(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_current_images_are_held_after_the_migration(self):
        executor = MigrationExecutor(connection)
        executor.migrate(OLD)
        old = executor.loader.project_state(OLD).apps
        owner = old.get_model("foundation", "User").objects.create(username="mig_img", password="x", nickname="n", class_label="1")
        campaign = old.get_model("campaigns", "Campaign").objects.create(owner=owner, name="c", starts_at=NOW, daily_budget=100)
        group = old.get_model("campaigns", "AdGroup").objects.create(campaign=campaign, name="g", pricing_unit="IMPRESSION")
        name, size = stored((1, 2, 3))
        creative = old.get_model("campaigns", "Creative").objects.create(
            ad_group=group, title="t", redirect_url="https://a.example", image_name=name, image_bytes=size,
        )
        self.migrate_to_latest()
        from campaigns import api
        from campaigns.models import CreativeImage

        held = CreativeImage.objects.get()
        self.assertEqual((held.creative_id, held.image_name, held.image_bytes), (creative.pk, name, size))
        self.assertTrue(api.is_asset_servable(name))

    def test_replaced_past_images_are_recovered_from_decisions_and_audit_logs(self):
        """결정 생성 → 이미지 교체(두 번) → 마이그레이션: 과거 이미지의 URL 이 열리고 보유 총량에 포함된다."""
        executor = MigrationExecutor(connection)
        executor.migrate(OLD)
        old = executor.loader.project_state(OLD).apps
        owner = old.get_model("foundation", "User").objects.create(username="mig_past", password="x", nickname="n", class_label="1")
        media = old.get_model("masters", "Media").objects.create(name="m")
        slot = old.get_model("masters", "Slot").objects.create(media=media, name="s", pricing_unit="IMPRESSION")
        campaign = old.get_model("campaigns", "Campaign").objects.create(owner=owner, name="c", starts_at=NOW, daily_budget=100)
        group = old.get_model("campaigns", "AdGroup").objects.create(campaign=campaign, name="g", pricing_unit="IMPRESSION")

        first, first_size = stored((10, 20, 30))  # 결정이 가리킨 이미지(이후 교체됨): 결정에서 복구
        second, second_size = stored((40, 50, 60))  # 교체 한 번 거친 이미지: 감사 로그에서 복구
        third, third_size = stored((70, 80, 90))  # 현재 이미지: campaigns 0003 이 채움
        lost = "f" * 64 + ".png"  # 감사 로그에는 있지만 파일이 없다 → 건너뜀
        creative = old.get_model("campaigns", "Creative").objects.create(
            ad_group=group, title="t", redirect_url="https://a.example", image_name=third, image_bytes=third_size,
        )
        Decision = old.get_model("records", "Decision")
        Decision.objects.create(
            media_id=media.pk, slot_id=slot.pk, decided_at=NOW, owner_id=owner.pk, campaign_id=campaign.pk, ad_group_id=group.pk,
            creative_id=creative.pk, pricing_unit="IMPRESSION", bid_amount=30, applied_amount=30, bid_version=1, policy_version=1,
            bid_id=uuid.uuid4(), bid_policy_id=uuid.uuid4(),
            snapshot={"title": "t", "redirect_url": "https://a.example", "image_name": first}, selection_policy="highest-bid/v1", candidate_count=1,
        )
        AuditLog = old.get_model("foundation", "AuditLog")
        for action, image in (("creative.image_replaced", second), ("creative.image_replaced", third), ("creative.image_replaced", lost)):
            AuditLog.objects.create(action=action, target_type="campaigns.creative", target_id=str(creative.pk), detail={"image": image}, created_at=NOW)
        AuditLog.objects.create(action="creative.image_replaced", target_type="campaigns.creative", target_id=str(uuid.uuid4()), detail={"image": first})  # 없는 소재

        self.migrate_to_latest()
        from campaigns import api
        from campaigns.models import CreativeImage

        held = dict(CreativeImage.objects.filter(creative_id=creative.pk).values_list("image_name", "image_bytes"))
        self.assertEqual(held, {first: first_size, second: second_size, third: third_size})  # 파일이 없는 것·없는 소재는 건너뜀
        self.assertTrue(all(api.is_asset_servable(n) for n in (first, second, third)))
        self.assertFalse(api.is_asset_servable(lost))
        with override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable"):
            client = Client()
            for name in (first, second, third):
                self.assertEqual(client.get(f"/assets/{name}").status_code, 200, name)  # 과거 결정의 URL 도 열린다
        # 복구된 파일은 보유량 쿼터에도 포함된다: 상한이 현재 + 과거 합계와 같으면 새 이미지는 더 못 올린다
        owner_row = old.get_model("foundation", "User").objects.get(pk=owner.pk)
        from foundation.models import User

        user = User.objects.get(pk=owner_row.pk)
        total = first_size + second_size + third_size
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=total):
            with self.assertRaises(api.LimitExceeded):
                api.replace_creative_image(user, creative.pk, io.BytesIO(image_factory.png_bytes(color=(5, 6, 7))))

    def test_recovery_is_idempotent_and_skips_when_nothing_to_recover(self):
        executor = MigrationExecutor(connection)
        executor.migrate(OLD)
        self.migrate_to_latest()
        from campaigns.models import CreativeImage

        self.assertEqual(CreativeImage.objects.count(), 0)  # 소재가 없는 DB 에서도 정상
