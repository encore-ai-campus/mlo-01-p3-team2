import dataclasses
import threading
import uuid
from unittest import mock

from django.db import IntegrityError, connection
from django.db.models import Model
from django.test import TestCase, TransactionTestCase, tag

from foundation.errors import Conflict, Forbidden, InvalidRequest, NotFound, StaleVersion
from foundation.logging import request_id_var
from foundation.models import AuditLog
from masters import api
from masters.models import BidPolicy, Media, Slot
from tests.factories import make_admin, make_advertiser


def new_slot(admin, media=None, name="메인 배너", unit="IMPRESSION", floor=10, base=20, cap=50):
    media = media or api.create_media(admin, f"매체-{uuid.uuid4().hex[:6]}")
    return api.create_slot(admin, media.media_id, name, unit, floor, base, cap, "초기 설정")


def versions(slot_id):
    return list(BidPolicy.objects.filter(slot_id=slot_id).order_by("policy_version").values_list("policy_version", flat=True))


class PolicyServiceTests(TestCase):
    def setUp(self):
        self.admin = make_admin()

    def test_create_slot_creates_first_policy_atomically(self):
        slot = new_slot(self.admin, floor=10, base=20, cap=50)
        self.assertEqual((slot.policy.policy_version, slot.policy.floor, slot.policy.base, slot.policy.cap), (1, 10, 20, 50))
        self.assertEqual(slot.policy.changed_by, self.admin.pk)
        # 정책 저장이 실패하면 슬롯도 남지 않는다
        media = api.create_media(self.admin, "원자성 매체")
        with mock.patch.object(BidPolicy._default_manager, "create", side_effect=IntegrityError("boom")):
            with self.assertRaises(Conflict):
                api.create_slot(self.admin, media.media_id, "배너", "CLICK", 1, 2, 3, "사유")
        self.assertFalse(Slot.objects.filter(media_id=media.media_id).exists())

    def test_policy_service_rejects_zero_negative_and_order_violation(self):
        media = api.create_media(self.admin, "검증 매체")
        cases = [(0, 5, 9), (-1, 5, 9), (10, 5, 9), (1, 9, 5), (1, 2, 2**53), (1.5, 2, 3), (True, 2, 3), ("1", 2, 3), (None, 2, 3)]
        for floor, base, cap in cases:
            with self.assertRaises(InvalidRequest, msg=(floor, base, cap)):
                api.create_slot(self.admin, media.media_id, "배너", "CLICK", floor, base, cap, "사유")
        self.assertFalse(Slot.objects.exists())

    def test_create_slot_validates_name_unit_reason_and_media(self):
        media = api.create_media(self.admin, "입력 매체")
        for kwargs in (dict(name=""), dict(name="  "), dict(name="x" * 101), dict(name="zero​width"),
                       dict(unit="DAILY"), dict(reason=""), dict(reason=" ")):
            args = dict(name="배너", unit="CLICK", reason="사유")
            args.update(kwargs)
            with self.assertRaises(InvalidRequest, msg=kwargs):
                api.create_slot(self.admin, media.media_id, args["name"], args["unit"], 1, 2, 3, args["reason"])
        with self.assertRaises(NotFound):
            api.create_slot(self.admin, uuid.uuid4(), "배너", "CLICK", 1, 2, 3, "사유")

    def test_slot_name_unique_per_media_in_service(self):
        slot = new_slot(self.admin, name="상단")
        with self.assertRaises(Conflict):
            api.create_slot(self.admin, slot.media_id, "상단", "CLICK", 1, 2, 3, "사유")
        other = api.create_media(self.admin, "다른 매체")
        api.create_slot(self.admin, other.media_id, "상단", "CLICK", 1, 2, 3, "사유")  # 다른 매체는 가능

    def test_media_name_conflict(self):
        api.create_media(self.admin, "중복")
        with self.assertRaises(Conflict):
            api.create_media(self.admin, "중복")

    def test_add_policy_version_increments_per_slot(self):
        a, b = new_slot(self.admin), new_slot(self.admin)
        api.add_policy_version(self.admin, a.slot_id, 11, 21, 51, "인상", expected_version=1)
        p = api.add_policy_version(self.admin, a.slot_id, 12, 22, 52, "또 인상", expected_version=2)
        self.assertEqual(p.policy_version, 3)
        self.assertEqual(versions(a.slot_id), [1, 2, 3])
        self.assertEqual(versions(b.slot_id), [1])  # 슬롯끼리 영향 없음
        self.assertEqual(api.get_slot(a.slot_id).policy.cap, 52)  # 현재 값 = 최대 버전

    def test_policy_stale_expected_version_rejected(self):
        slot = new_slot(self.admin)
        api.add_policy_version(self.admin, slot.slot_id, 11, 21, 51, "A 관리자", expected_version=1)
        with self.assertRaises(StaleVersion):
            api.add_policy_version(self.admin, slot.slot_id, 99, 99, 99, "B 관리자(옛 화면)", expected_version=1)
        self.assertEqual(versions(slot.slot_id), [1, 2])  # B 의 변경은 저장되지 않았다
        self.assertEqual(api.get_slot(slot.slot_id).policy.floor, 11)

    def test_policy_invalid_values_not_saved_and_version_not_consumed(self):
        slot = new_slot(self.admin)
        with self.assertRaises(InvalidRequest):
            api.add_policy_version(self.admin, slot.slot_id, 30, 20, 50, "잘못", expected_version=1)
        self.assertEqual(versions(slot.slot_id), [1])
        api.add_policy_version(self.admin, slot.slot_id, 11, 21, 51, "정상", expected_version=1)
        self.assertEqual(versions(slot.slot_id), [1, 2])

    def test_unknown_slot_is_not_found(self):
        for bad in (uuid.uuid4(), "not-a-uuid"):
            with self.assertRaises(NotFound):
                api.add_policy_version(self.admin, bad, 1, 2, 3, "사유", expected_version=1)
            with self.assertRaises(NotFound):
                api.get_slot(bad)

    def test_bulk_policy_applies_per_slot_versions(self):
        a, b = new_slot(self.admin), new_slot(self.admin)
        api.add_policy_version(self.admin, b.slot_id, 11, 21, 51, "b 만 한 번 더", expected_version=1)
        out = api.add_policy_version_bulk(self.admin, {a.slot_id: 1, b.slot_id: 2}, 5, 6, 7, "일괄")
        self.assertEqual([p.policy_version for p in out], [2, 3])  # 슬롯마다 자기 버전이 쌓인다
        self.assertEqual((api.get_slot(a.slot_id).policy.cap, api.get_slot(b.slot_id).policy.cap), (7, 7))

    def test_bulk_policy_is_all_or_nothing(self):
        a, b = new_slot(self.admin), new_slot(self.admin)
        with self.assertRaises(StaleVersion):  # 두 번째 슬롯의 본 버전이 틀림
            api.add_policy_version_bulk(self.admin, {a.slot_id: 1, b.slot_id: 5}, 5, 6, 7, "일괄")
        self.assertEqual((versions(a.slot_id), versions(b.slot_id)), ([1], [1]))
        with self.assertRaises(NotFound):  # 없는 슬롯이 섞임
            api.add_policy_version_bulk(self.admin, {a.slot_id: 1, uuid.uuid4(): 1}, 5, 6, 7, "일괄")
        self.assertEqual(versions(a.slot_id), [1])
        with self.assertRaises(InvalidRequest):
            api.add_policy_version_bulk(self.admin, {}, 5, 6, 7, "빈 목록")

    def test_inactive_flags_hide_slots_from_default_listing(self):
        slot = new_slot(self.admin)
        other = new_slot(self.admin)
        self.assertEqual({s.slot_id for s in api.list_slots()}, {slot.slot_id, other.slot_id})
        api.set_slot_active(self.admin, slot.slot_id, False)
        self.assertEqual({s.slot_id for s in api.list_slots()}, {other.slot_id})
        self.assertEqual({s.slot_id for s in api.list_slots(active_only=False)}, {slot.slot_id, other.slot_id})
        api.set_media_active(self.admin, other.media_id, False)  # 매체가 꺼지면 그 슬롯도 빠진다
        self.assertEqual(api.list_slots(), [])
        self.assertFalse(api.get_slot(slot.slot_id).is_active)  # 개별 조회는 상태를 값으로 돌려준다
        with self.assertRaises(NotFound):
            api.set_slot_active(self.admin, uuid.uuid4(), True)
        with self.assertRaises(NotFound):
            api.set_media_active(self.admin, uuid.uuid4(), True)

    def test_list_slots_filters_by_media(self):
        a, b = new_slot(self.admin), new_slot(self.admin)
        self.assertEqual([s.slot_id for s in api.list_slots(media_id=a.media_id)], [a.slot_id])

    def test_get_slots_with_policy_single_query(self):
        slots = [new_slot(self.admin) for _ in range(3)]
        api.add_policy_version(self.admin, slots[0].slot_id, 11, 21, 51, "버전 2", expected_version=1)
        ids = [s.slot_id for s in slots] + [uuid.uuid4()]  # 없는 ID 는 결과에 없다
        with self.assertNumQueries(1):
            result = api.get_slots_with_policy(ids)
        self.assertEqual(set(result), {s.slot_id for s in slots})
        self.assertEqual(result[slots[0].slot_id].policy.policy_version, 2)  # 현재 = 최대 버전
        self.assertEqual(result[slots[1].slot_id].policy.policy_version, 1)

    def test_bulk_lookups_drop_ids_that_are_not_uuids(self):
        """여러 ID 를 한 번에 찾는 조회는 형식이 틀린 값을 오류 없이 버린다(없는 ID 와 같다). 대문자 표기도 같은 ID 다."""
        slot = new_slot(self.admin)
        ids = ["not-a-uuid", "", None, str(slot.slot_id).upper(), slot.slot_id]
        self.assertEqual(set(api.get_slots_with_policy(ids)), {slot.slot_id})
        self.assertEqual(api.slot_names(ids), {slot.slot_id: slot.name})

    def test_api_returns_frozen_values_not_models(self):
        slot = new_slot(self.admin)
        for value in (slot, slot.policy, api.get_slot(slot.slot_id), api.create_media(self.admin, "값 매체"), api.list_slots()[0]):
            self.assertFalse(isinstance(value, Model))
            self.assertTrue(dataclasses.is_dataclass(value))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            slot.name = "바꿈"


@tag("security")
class MastersAuthorizationAndAuditTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.slot = new_slot(self.admin)

    def calls(self, actor):
        s = self.slot
        return [
            lambda: api.create_media(actor, "새 매체"),
            lambda: api.set_media_active(actor, s.media_id, False),
            lambda: api.create_slot(actor, s.media_id, "다른 배너", "CLICK", 1, 2, 3, "사유"),
            lambda: api.add_policy_version(actor, s.slot_id, 1, 2, 3, "사유", expected_version=1),
            lambda: api.add_policy_version_bulk(actor, {s.slot_id: 1}, 1, 2, 3, "사유"),
            lambda: api.set_slot_active(actor, s.slot_id, False),
        ]

    def test_non_admin_actor_rejected(self):
        inactive_admin = make_admin()
        inactive_admin.is_active = False
        inactive_admin.save()
        from django.contrib.auth.models import AnonymousUser

        before = (AuditLog.objects.count(), versions(self.slot.slot_id))
        for actor in (make_advertiser(), inactive_admin, AnonymousUser(), None):
            for call in self.calls(actor):
                with self.assertRaises(Forbidden):
                    call()
        self.assertEqual((AuditLog.objects.count(), versions(self.slot.slot_id)), before)
        self.assertEqual(Media.objects.count(), 1)

    def test_admin_actions_are_audited_with_request_id(self):
        AuditLog.objects.all()  # 시작 상태 기준: setUp 의 슬롯 생성 기록은 이미 있다
        token = request_id_var.set("11111111-2222-3333-4444-555555555555")
        try:
            api.add_policy_version(self.admin, self.slot.slot_id, 12, 22, 52, "정책 상향", expected_version=1)
            api.set_slot_active(self.admin, self.slot.slot_id, False)
        finally:
            request_id_var.reset(token)
        entry = AuditLog.objects.get(action="masters.policy_added")
        self.assertEqual((entry.actor_id, entry.target_type, entry.target_id), (self.admin.pk, "masters.slot", str(self.slot.slot_id)))
        self.assertEqual(entry.request_id, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(entry.detail["version"], 2)
        self.assertEqual(entry.detail["previous"], {"floor": 10, "base": 20, "cap": 50})
        self.assertEqual(entry.detail["reason"], "정책 상향")
        self.assertTrue(AuditLog.objects.filter(action="masters.slot_active_changed", target_id=str(self.slot.slot_id)).exists())
        self.assertTrue(AuditLog.objects.filter(action__in=["masters.media_created", "masters.slot_created"]).count() >= 2)

    def test_audit_without_request_context_has_empty_request_id(self):
        entry = AuditLog.objects.get(action="masters.slot_created")
        self.assertEqual(entry.request_id, "")


class ConcurrentPolicyTests(TransactionTestCase):
    def test_concurrent_policy_saves_only_one_wins(self):
        """같은 `expected_version` 으로 동시에 저장하면 정확히 한쪽만 성공한다."""
        admin_a, admin_b = make_admin(), make_admin()
        slot = new_slot(admin_a)
        barrier, results = threading.Barrier(2), []

        def worker(admin, cap):
            try:
                barrier.wait(timeout=5)
                api.add_policy_version(admin, slot.slot_id, 11, 21, cap, "동시 변경", expected_version=1)
                results.append("ok")
            except Exception as e:  # noqa: BLE001  (결과 종류만 기록)
                results.append(type(e).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(a, cap)) for a, cap in ((admin_a, 60), (admin_b, 70))]
        [t.start() for t in threads]
        [t.join(timeout=15) for t in threads]
        self.assertEqual(sorted(results), ["StaleVersion", "ok"], results)  # 진 쪽은 충돌 안내여야 한다(교착·잠금 초과 같은 DB 오류가 아니다)
        self.assertEqual(versions(slot.slot_id), [1, 2])  # 두 번째 버전이 정확히 하나
        self.assertIn(api.get_slot(slot.slot_id).policy.cap, (60, 70))
