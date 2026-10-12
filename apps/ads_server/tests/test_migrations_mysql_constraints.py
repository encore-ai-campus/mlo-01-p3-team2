"""billing 0003·campaigns 0003(조건부 유일 제약 → MySQL용): 새 제약을 어기는 **기존 데이터**가 있어도 DDL 이 반쯤 적용된 채 멈추지 않는다.

MySQL 의 DDL 은 되돌릴 수 없고, DB-1a 의 MySQL 에는 조건부 유일 제약이 없었으므로 중복 데이터가 실제로 있을 수 있다. 검사를 모든 DDL 보다 앞에 두어
멈추더라도 스키마가 그대로이고, 운영자가 데이터를 정리한 뒤 **같은 DB 에서** 다시 실행할 수 있음을 확인한다. 금융 이력은 자동으로 지우거나 고치지 않는다.
"""
import uuid
from datetime import UTC, datetime, timedelta

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, tag

WHEN = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


class MigrationCase(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())  # 다른 시험을 위해 최신으로

    def columns(self, table):
        with connection.cursor() as cur:
            return {c.name for c in connection.introspection.get_table_description(cur, table)}

    def user(self, apps):
        return apps.get_model("foundation", "User").objects.create(username=f"u{uuid.uuid4().hex[:8]}", role="ADVERTISER", nickname="닉", class_label="1반", password="x")


@tag("security")
class BillingConstraintMigrationTests(MigrationCase):
    BEFORE = [("billing", "0002_initial")]
    AFTER = [("billing", "0003_mysql_constraints")]

    def entry(self, apps, wallet, seq, **kw):
        values = dict(entry_id=uuid.uuid4(), wallet=wallet, seq=seq, entry_type="CHARGE", amount=-30, balance_after=100, created_at=WHEN)
        values.update(kw)
        return apps.get_model("billing", "LedgerEntry").objects.create(**values)

    def wallet(self, apps):
        return apps.get_model("billing", "Wallet").objects.create(owner=self.user(apps), balance=100)

    def test_a_double_charge_stops_the_migration_before_any_schema_change_and_can_be_retried_after_cleanup(self):
        apps = self.migrate(self.BEFORE)
        wallet = self.wallet(apps)
        self.entry(apps, wallet, 1, reaction_ref="m:r1")
        twin = self.entry(apps, wallet, 2, reaction_ref="m:r1")  # DB-1a 의 MySQL 에서는 가능했던 이중 과금 줄
        with self.assertRaisesRegex(RuntimeError, "같은 반응 키.*이중 과금 의심"):
            self.migrate(self.AFTER)
        self.assertNotIn("signup_grant_wallet", self.columns("billing_ledger_entry"))  # 스키마는 그대로다
        apps = self.migrate(self.BEFORE)  # 같은 DB — 여전히 0002 상태이고 데이터도 그대로다
        LedgerEntry = apps.get_model("billing", "LedgerEntry")
        self.assertEqual(LedgerEntry.objects.filter(reaction_ref="m:r1").count(), 2)  # 자동으로 지우지 않았다
        LedgerEntry.objects.filter(pk=twin.pk).update(reaction_ref=None)  # 운영자가 확인해 정리했다고 하자
        apps = self.migrate(self.AFTER)
        self.assertIn("signup_grant_wallet", self.columns("billing_ledger_entry"))
        LedgerEntry = apps.get_model("billing", "LedgerEntry")
        with self.assertRaises(IntegrityError), transaction.atomic():  # 이제 제약이 있다
            self.entry(apps, apps.get_model("billing", "Wallet").objects.get(), 3, reaction_ref="m:r1")
        self.assertEqual(LedgerEntry.objects.count(), 2)

    def test_a_second_signup_grant_stops_the_migration_before_any_schema_change(self):
        apps = self.migrate(self.BEFORE)
        wallet = self.wallet(apps)
        self.entry(apps, wallet, 1, entry_type="SIGNUP_GRANT", amount=100)
        second = self.entry(apps, wallet, 2, entry_type="SIGNUP_GRANT", amount=100)
        with self.assertRaisesRegex(RuntimeError, "가입 지급이 둘 이상인 지갑 1개"):
            self.migrate(self.AFTER)
        self.assertNotIn("signup_grant_wallet", self.columns("billing_ledger_entry"))
        apps = self.migrate(self.BEFORE)
        apps.get_model("billing", "LedgerEntry").objects.filter(pk=second.pk).update(entry_type="TOPUP")  # 정리
        self.migrate(self.AFTER)
        self.assertIn("signup_grant_wallet", self.columns("billing_ledger_entry"))

    def test_clean_data_migrates_and_other_wallets_may_each_have_their_own_grant(self):
        apps = self.migrate(self.BEFORE)
        for _ in range(2):
            self.entry(apps, self.wallet(apps), 1, entry_type="SIGNUP_GRANT", amount=100)
        self.entry(apps, apps.get_model("billing", "Wallet").objects.first(), 2, reaction_ref=None, entry_type="ADMIN_ADJUST", amount=5)  # NULL 키는 몇 개든 된다
        self.migrate(self.AFTER)


@tag("security")
class CampaignConstraintMigrationTests(MigrationCase):
    BEFORE = [("campaigns", "0002_initial")]
    AFTER = [("campaigns", "0003_mysql_constraints")]

    def test_two_open_review_requests_stop_the_migration_before_any_schema_change(self):
        apps = self.migrate(self.BEFORE)
        campaign = apps.get_model("campaigns", "Campaign").objects.create(
            owner=self.user(apps), name="c", starts_at=WHEN, ends_at=WHEN + timedelta(days=1), daily_budget=100, status="SUSPENDED",
        )
        Review = apps.get_model("campaigns", "ReviewRequest")
        Review.objects.create(campaign=campaign, status="OPEN", created_at=WHEN)
        twin = Review.objects.create(campaign=campaign, status="OPEN", created_at=WHEN)  # DB-1a 의 MySQL 에서는 동시 요청으로 가능했다
        with self.assertRaisesRegex(RuntimeError, "열린 재검토 요청이 둘 이상인 캠페인 1개"):
            self.migrate(self.AFTER)
        self.assertNotIn("open_campaign", self.columns("campaigns_review_request"))
        apps = self.migrate(self.BEFORE)
        Review = apps.get_model("campaigns", "ReviewRequest")
        self.assertEqual(Review.objects.filter(status="OPEN").count(), 2)  # 자동으로 닫지 않았다
        Review.objects.filter(pk=twin.pk).update(status="REJECTED", closed_at=WHEN)  # 운영자가 정리
        apps = self.migrate(self.AFTER)
        self.assertIn("open_campaign", self.columns("campaigns_review_request"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            apps.get_model("campaigns", "ReviewRequest").objects.create(campaign_id=campaign.pk, status="OPEN", created_at=WHEN)
