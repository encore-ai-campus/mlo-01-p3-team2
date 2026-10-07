import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase, tag

from campaigns.models import AdGroup, Bid, Campaign, ReviewRequest
from foundation.models import AppendOnlyError
from tests.factories import DAY, NOW, make_advertiser

USER_ID = uuid.uuid4()


def campaign(owner, **kw):
    values = dict(owner=owner, name="c", starts_at=NOW, ends_at=NOW + DAY, daily_budget=1000)
    values.update(kw)
    return Campaign.objects.create(**values)


class CampaignConstraintTests(TestCase):
    def setUp(self):
        self.owner = make_advertiser()

    def test_budget_and_period_constraints_in_db(self):
        for kw in (dict(daily_budget=0), dict(daily_budget=2**53), dict(ends_at=NOW - timedelta(seconds=1))):
            with self.assertRaises(IntegrityError, msg=kw), transaction.atomic():
                campaign(self.owner, **kw)
        campaign(self.owner, ends_at=None)
        campaign(self.owner, ends_at=NOW)  # 시작과 같은 종료(시작 전 조기 종료)는 허용

    def test_only_one_open_review_request_per_campaign(self):
        c = campaign(self.owner)
        ReviewRequest.objects.create(campaign=c)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewRequest.objects.create(campaign=c)
        ReviewRequest.objects.filter(campaign=c).update(status="REJECTED")
        ReviewRequest.objects.create(campaign=c)  # 닫힌 뒤에는 다시 열 수 있다
        ReviewRequest.objects.create(campaign=campaign(self.owner))  # 다른 캠페인은 영향 없음


@tag("security")
class BidAndAdGroupModelTests(TestCase):
    def setUp(self):
        self.group = AdGroup.objects.create(campaign=campaign(make_advertiser()), name="g", pricing_unit="IMPRESSION")

    def bid(self, **kw):
        values = dict(ad_group=self.group, bid_version=1, amount=30, created_by=USER_ID)
        values.update(kw)
        return Bid(**values)

    def test_bid_constraints_in_db(self):
        for kw in (dict(amount=0), dict(amount=2**53)):
            with self.assertRaises(IntegrityError, msg=kw), transaction.atomic():
                self.bid(**kw).save()
        self.bid(amount=1).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.bid(amount=2).save()  # 같은 (광고그룹, 버전)

    def test_bid_is_append_only_and_cannot_be_overwritten(self):
        self.bid().save()
        row = Bid.objects.get(ad_group=self.group, bid_version=1)
        row.amount = 99
        with self.assertRaises(AppendOnlyError):
            row.save()
        with self.assertRaises(AppendOnlyError):
            row.delete()
        with self.assertRaises(AppendOnlyError):
            Bid.objects.filter(ad_group=self.group).update(amount=99)
        with self.assertRaises((IntegrityError, AppendOnlyError)), transaction.atomic():
            self.bid(pk=row.pk, amount=999).save()
        with self.assertRaises(AppendOnlyError):
            Bid.objects.bulk_create([self.bid(pk=row.pk, amount=999)], update_conflicts=True, update_fields=["amount"], unique_fields=["id"])
        self.assertEqual(Bid.objects.get(pk=row.pk).amount, 30)

    def test_ad_group_pricing_unit_immutable(self):
        self.group.pricing_unit = "CLICK"
        with self.assertRaises(ValueError):
            self.group.save()
        group = AdGroup.objects.get(pk=self.group.pk)
        group.enabled = False
        group.save()  # 다른 필드는 바꿀 수 있다
        self.assertEqual(AdGroup.objects.get(pk=group.pk).pricing_unit, "IMPRESSION")
