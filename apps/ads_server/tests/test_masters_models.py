import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase, tag

from foundation.models import AppendOnlyError
from masters.models import BidPolicy, Media, Slot

USER_ID = uuid.uuid4()


def make_slot(media=None, name="메인 배너", unit="IMPRESSION"):
    media = media or Media.objects.create(name=f"매체-{uuid.uuid4().hex[:6]}")
    slot = Slot.objects.create(media=media, name=name, pricing_unit=unit, audience="individual")
    BidPolicy.objects.create(slot=slot, policy_version=1, floor_amount=10, base_amount=20, cap_amount=50, changed_by=USER_ID, reason="초기")
    return slot


def policy(slot, **kw):
    values = dict(slot=slot, policy_version=2, floor_amount=10, base_amount=20, cap_amount=50, changed_by=USER_ID, reason="변경")
    values.update(kw)
    return BidPolicy(**values)


@tag("security")
class PolicyConstraintTests(TestCase):
    def test_policy_check_constraint_in_db(self):
        """서비스를 우회해 직접 저장해도 DB 가 순서·범위 위반을 거부한다(설계 §4.4-7)."""
        slot = make_slot()
        bad = [
            dict(floor_amount=30, base_amount=20, cap_amount=50),  # floor > base
            dict(floor_amount=10, base_amount=60, cap_amount=50),  # base > cap
            dict(floor_amount=0, base_amount=20, cap_amount=50),  # floor 는 0 초과
            dict(floor_amount=10, base_amount=20, cap_amount=2**53),  # 표현 가능한 최대값 초과
        ]
        for values in bad:
            with self.assertRaises(IntegrityError, msg=values), transaction.atomic():
                policy(slot, **values).save()
        self.assertEqual(BidPolicy.objects.filter(slot=slot).count(), 1)

    def test_boundary_values_are_accepted(self):
        slot = make_slot()
        policy(slot, floor_amount=5, base_amount=5, cap_amount=5).save()  # 모두 같아도 됨
        policy(slot, policy_version=3, floor_amount=1, base_amount=2, cap_amount=2**53 - 1).save()

    def test_version_unique_per_slot(self):
        slot, other = make_slot(), make_slot()
        policy(slot).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            policy(slot).save()
        policy(other).save()  # 다른 슬롯은 같은 버전 번호 가능

    def test_policy_is_append_only(self):
        slot = make_slot()
        row = BidPolicy.objects.get(slot=slot, policy_version=1)
        row.cap_amount = 99
        with self.assertRaises(AppendOnlyError):
            row.save()
        with self.assertRaises(AppendOnlyError):
            row.delete()
        with self.assertRaises(AppendOnlyError):
            BidPolicy.objects.filter(slot=slot).update(cap_amount=99)
        with self.assertRaises(AppendOnlyError):
            BidPolicy.objects.filter(slot=slot).delete()
        self.assertEqual(BidPolicy.objects.get(pk=row.pk).cap_amount, 50)


@tag("security")
class SlotModelTests(TestCase):
    def test_slot_pricing_unit_immutable(self):
        slot = make_slot(unit="IMPRESSION")
        slot.pricing_unit = "CLICK"
        with self.assertRaises(ValueError):
            slot.save()
        self.assertEqual(Slot.objects.get(pk=slot.pk).pricing_unit, "IMPRESSION")
        slot = Slot.objects.get(pk=slot.pk)
        slot.is_active = False  # 다른 필드는 바꿀 수 있다
        slot.save()

    def test_slot_name_unique_per_media_only(self):
        media_a, media_b = Media.objects.create(name="A 매체"), Media.objects.create(name="B 매체")
        make_slot(media_a, "상단")
        make_slot(media_b, "상단")  # 다른 매체에서는 같은 이름 가능
        with self.assertRaises(IntegrityError), transaction.atomic():
            Slot.objects.create(media=media_a, name="상단", pricing_unit="CLICK", audience="individual")

    def test_media_name_unique(self):
        Media.objects.create(name="같은 이름")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Media.objects.create(name="같은 이름")
