import dataclasses
import uuid
from unittest import mock

from django.db import IntegrityError
from django.db.models import Model
from django.test import TestCase, TransactionTestCase, tag
from django.utils import timezone

from foundation.errors import Conflict, Forbidden, InvalidRequest, NotFound, StaleVersion
from foundation.logging import request_id_var
from foundation.models import AuditLog
from masters import api
from masters.models import BidPolicy, Media, MediaDeactivation, Slot
from tests.support.concurrency import run_together
from tests.support.factories import SHARES, make_admin, make_advertiser
from tests.support.cases import Cases


def new_slot(admin, media=None, name="메인 배너", floor=100, base=200, cap=500):
    media = media or api.create_media(admin, f"매체-{uuid.uuid4().hex[:6]}")
    return api.create_slot(admin, media.media_id, name, floor, base, cap, "초기 설정", audience="individual", **SHARES)


def versions(slot_id):
    return list(BidPolicy.objects.filter(slot_id=slot_id).order_by("policy_version").values_list("policy_version", flat=True))


class PolicyServiceTests(Cases, TestCase):
    def setUp(self):
        self.admin = make_admin()

    def case_create_slot_creates_first_policy_atomically(self):
        slot = new_slot(self.admin, floor=100, base=200, cap=500)
        self.assertEqual((slot.policy.policy_version, slot.policy.floor, slot.policy.base, slot.policy.cap), (1, 100, 200, 500))
        self.assertEqual(slot.policy.changed_by, self.admin.pk)
        # 정책 저장이 실패하면 슬롯도 남지 않는다
        media = api.create_media(self.admin, "원자성 매체")
        with mock.patch.object(BidPolicy._default_manager, "create", side_effect=IntegrityError("boom")):
            with self.assertRaises(Conflict):
                api.create_slot(self.admin, media.media_id, "배너", 100, 200, 300, "사유", audience="individual", **SHARES)
        self.assertFalse(Slot.objects.filter(media_id=media.media_id).exists())

    def case_policy_service_rejects_zero_negative_and_order_violation(self):
        media = api.create_media(self.admin, "검증 매체")
        cases = [(0, 500, 900), (-1, 500, 900), (99, 200, 300), (1000, 500, 900), (100, 900, 500), (100, 200, 2**53), (100.5, 200, 300), (True, 200, 300),
                 ("100", 200, 300), (None, 200, 300)]  # 99: 하한 최소 100 미만(6-10c)
        for floor, base, cap in cases:
            with self.assertRaises(InvalidRequest, msg=(floor, base, cap)):
                api.create_slot(self.admin, media.media_id, "배너", floor, base, cap, "사유", audience="individual", **SHARES)
        self.assertFalse(Slot.objects.exists())

    def case_the_floor_is_at_least_100_in_all_three_places(self):
        """하한 최소 100(설계 §10 "구성별 반응 비율 과금", 6-10c): 비율 ≥ 1% 와 함께 반응 하나의 과금(내림)이 0 이 되지 않게 한다. 세 곳이 같은 검사를 쓴다."""
        slot = new_slot(self.admin)
        media = api.create_media(self.admin, "하한 매체")
        places = {
            "만들기": lambda floor: api.create_slot(self.admin, media.media_id, f"배너{floor}", floor, 200, 300, "사유", audience="individual", **SHARES).policy,
            "정책 변경": lambda floor: api.add_policy_version(self.admin, slot.slot_id, floor, 200, 300, "사유", expected_version=versions(slot.slot_id)[-1], **SHARES),
            "일괄 변경": lambda floor: api.add_policy_version_bulk(self.admin, {slot.slot_id: versions(slot.slot_id)[-1]}, floor, 200, 300, "사유", **SHARES)[0],
        }
        for place, call in places.items():
            before = BidPolicy.objects.count()
            with self.assertRaises(InvalidRequest, msg=place) as caught:
                call(99)
            self.assertEqual(caught.exception.errors, [{"pointer": "/floor", "message": "100 이상 9007199254740991 이하의 정수여야 합니다."}], place)
            self.assertEqual(BidPolicy.objects.count(), before, place)
            self.assertEqual(call(100).floor, 100, place)

    def case_charge_shares_are_checked_the_same_way_in_all_three_places(self):
        """반응 유형별 과금 비율(설계 §10 "구성별 반응 비율 과금", 6-10b): 각각 정수 1~98, 합 100. 만들기·정책 변경·일괄 변경이 같은 검사를 쓰고, 거절하면 아무것도 남지 않는다."""
        slot = new_slot(self.admin)
        media = api.create_media(self.admin, "비율 매체")
        bad = [(0, 2, 98), (2, 0, 98), (2, 98, 0), (99, 1, 0), (97, 1, 1), (98, 2, 1), (50.0, 25, 25), (True, 1, 98), ("98", 1, 1), (None, 1, 99)]
        good = [(1, 1, 98), (1, 98, 1), (98, 1, 1), (34, 33, 33)]
        places = {
            "만들기": lambda i, s: api.create_slot(self.admin, media.media_id, f"배너{i}", 100, 200, 300, "사유", audience="individual", **s).policy,
            "정책 변경": lambda i, s: api.add_policy_version(self.admin, slot.slot_id, 100, 200, 300, "사유", expected_version=versions(slot.slot_id)[-1], **s),
            "일괄 변경": lambda i, s: api.add_policy_version_bulk(self.admin, {slot.slot_id: versions(slot.slot_id)[-1]}, 100, 200, 300, "사유", **s)[0],
        }
        for place, call in places.items():
            for i, values in enumerate(bad):
                before = (Slot.objects.count(), BidPolicy.objects.count())
                with self.assertRaises(InvalidRequest, msg=(place, values)):
                    call(i, dict(zip(("impression_share", "click_share", "conversion_share"), values)))
                self.assertEqual((Slot.objects.count(), BidPolicy.objects.count()), before, (place, values))
            for i, values in enumerate(good):
                policy = call(f"ok{i}", dict(zip(("impression_share", "click_share", "conversion_share"), values)))
                self.assertEqual((policy.impression_share, policy.click_share, policy.conversion_share), values, place)
        with self.assertRaises(InvalidRequest) as caught:
            api.create_slot(self.admin, media.media_id, "합", 100, 200, 300, "사유", audience="individual", impression_share=97, click_share=1, conversion_share=1)
        self.assertEqual(caught.exception.errors, [{"pointer": "/shares", "message": "노출·클릭·전환 비율의 합은 100이어야 합니다(지금 99)."}])

    def case_create_slot_validates_name_reason_and_media(self):
        media = api.create_media(self.admin, "입력 매체")
        for kwargs in (dict(name=""), dict(name="  "), dict(name="x" * 101), dict(name="zero​width"),
                       dict(reason="x" * 201), dict(reason="zero​width")):
            args = dict(name="배너", reason="사유")
            args.update(kwargs)
            with self.assertRaises(InvalidRequest, msg=kwargs):
                api.create_slot(self.admin, media.media_id, args["name"], 100, 200, 300, args["reason"], audience="individual", **SHARES)
        with self.assertRaises(NotFound):
            api.create_slot(self.admin, uuid.uuid4(), "배너", 100, 200, 300, "사유", audience="individual", **SHARES)

    def case_a_slot_may_be_created_without_a_reason_but_a_policy_change_may_not(self):
        """만들 때만 빈 사유를 "없음"으로 채운다(6-8c). 가격을 바꾸는 정책 변경·일괄 변경은 사유가 필수다."""
        media = api.create_media(self.admin, "사유 매체")
        for i, blank in enumerate(("", "   ", None)):
            slot = api.create_slot(self.admin, media.media_id, f"배너{i}", 100, 200, 300, blank, audience="individual", **SHARES)
            self.assertEqual(slot.policy.reason, "없음")
        for blank in ("", "   ", None):
            with self.assertRaises(InvalidRequest, msg=blank):
                api.add_policy_version(self.admin, slot.slot_id, 100, 200, 300, blank, expected_version=1, **SHARES)
            with self.assertRaises(InvalidRequest, msg=blank):
                api.add_policy_version_bulk(self.admin, {slot.slot_id: 1}, 100, 200, 300, blank, **SHARES)

    def case_slot_name_unique_per_media_in_service(self):
        slot = new_slot(self.admin, name="상단")
        with self.assertRaises(Conflict):
            api.create_slot(self.admin, slot.media_id, "상단", 100, 200, 300, "사유", audience="individual", **SHARES)
        other = api.create_media(self.admin, "다른 매체")
        api.create_slot(self.admin, other.media_id, "상단", 100, 200, 300, "사유", audience="individual", **SHARES)  # 다른 매체는 가능

    def case_media_name_conflict(self):
        api.create_media(self.admin, "중복")
        with self.assertRaises(Conflict):
            api.create_media(self.admin, "중복")

    def case_add_policy_version_increments_per_slot(self):
        a, b = new_slot(self.admin), new_slot(self.admin)
        api.add_policy_version(self.admin, a.slot_id, 110, 210, 510, "인상", expected_version=1, **SHARES)
        p = api.add_policy_version(self.admin, a.slot_id, 120, 220, 520, "또 인상", expected_version=2, **SHARES)
        self.assertEqual(p.policy_version, 3)
        self.assertEqual(versions(a.slot_id), [1, 2, 3])
        self.assertEqual(versions(b.slot_id), [1])  # 슬롯끼리 영향 없음
        self.assertEqual(api.get_slot(a.slot_id).policy.cap, 520)  # 현재 값 = 최대 버전

    def case_policy_stale_expected_version_rejected(self):
        slot = new_slot(self.admin)
        api.add_policy_version(self.admin, slot.slot_id, 110, 210, 510, "A 관리자", expected_version=1, **SHARES)
        with self.assertRaises(StaleVersion):
            api.add_policy_version(self.admin, slot.slot_id, 990, 990, 990, "B 관리자(옛 화면)", expected_version=1, **SHARES)
        self.assertEqual(versions(slot.slot_id), [1, 2])  # B 의 변경은 저장되지 않았다
        self.assertEqual(api.get_slot(slot.slot_id).policy.floor, 110)

    def case_policy_invalid_values_not_saved_and_version_not_consumed(self):
        slot = new_slot(self.admin)
        with self.assertRaises(InvalidRequest):
            api.add_policy_version(self.admin, slot.slot_id, 300, 200, 500, "잘못", expected_version=1, **SHARES)
        self.assertEqual(versions(slot.slot_id), [1])
        api.add_policy_version(self.admin, slot.slot_id, 110, 210, 510, "정상", expected_version=1, **SHARES)
        self.assertEqual(versions(slot.slot_id), [1, 2])

    def case_unknown_slot_is_not_found(self):
        for bad in (uuid.uuid4(), "not-a-uuid"):
            with self.assertRaises(NotFound):
                api.add_policy_version(self.admin, bad, 100, 200, 300, "사유", expected_version=1, **SHARES)
            with self.assertRaises(NotFound):
                api.get_slot(bad)

    def case_bulk_policy_applies_per_slot_versions(self):
        a, b = new_slot(self.admin), new_slot(self.admin)
        api.add_policy_version(self.admin, b.slot_id, 110, 210, 510, "b 만 한 번 더", expected_version=1, **SHARES)
        out = api.add_policy_version_bulk(self.admin, {a.slot_id: 1, b.slot_id: 2}, 500, 600, 700, "일괄", **SHARES)
        self.assertEqual([p.policy_version for p in out], [2, 3])  # 슬롯마다 자기 버전이 쌓인다
        self.assertEqual((api.get_slot(a.slot_id).policy.cap, api.get_slot(b.slot_id).policy.cap), (700, 700))

    def case_bulk_policy_is_all_or_nothing(self):
        a, b = new_slot(self.admin), new_slot(self.admin)
        with self.assertRaises(StaleVersion):  # 두 번째 슬롯의 본 버전이 틀림
            api.add_policy_version_bulk(self.admin, {a.slot_id: 1, b.slot_id: 5}, 500, 600, 700, "일괄", **SHARES)
        self.assertEqual((versions(a.slot_id), versions(b.slot_id)), ([1], [1]))
        with self.assertRaises(NotFound):  # 없는 슬롯이 섞임
            api.add_policy_version_bulk(self.admin, {a.slot_id: 1, uuid.uuid4(): 1}, 500, 600, 700, "일괄", **SHARES)
        self.assertEqual(versions(a.slot_id), [1])
        with self.assertRaises(InvalidRequest):
            api.add_policy_version_bulk(self.admin, {}, 500, 600, 700, "빈 목록", **SHARES)

    def case_inactive_flags_hide_slots_from_default_listing(self):
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

    def case_only_turning_an_active_media_off_records_a_deactivation(self):
        """6-1a: 켜져 있던 매체를 실제로 끌 때만 기록한다(이미 꺼진 매체를 다시 끄거나 켜면 없음). 반응 판정은 이 기록에서 (결정 시각, 접수 시각] 안의 가장 이른 비활성화를 찾는다."""
        media = api.create_media(self.admin, "끄는 매체")
        before = timezone.now()
        api.set_media_active(self.admin, media.media_id, False)
        api.set_media_active(self.admin, media.media_id, False)  # 이미 꺼져 있다
        api.set_media_active(self.admin, media.media_id, True)
        first = MediaDeactivation.objects.get(media_id=media.media_id).deactivated_at
        api.set_media_active(self.admin, media.media_id, False)
        self.assertEqual(MediaDeactivation.objects.filter(media_id=media.media_id).count(), 2)
        self.assertEqual(api.first_deactivation(media.media_id, before, timezone.now()), first)  # 가장 이른 것
        self.assertEqual(api.first_deactivation(media.media_id, before, first), first)  # 끝(접수 시각)은 포함
        self.assertIsNone(api.first_deactivation(media.media_id, first, first))  # 시작(결정 시각)은 제외
        self.assertIsNone(api.first_deactivation(uuid.uuid4(), before, timezone.now()))

    def case_list_and_get_media_for_the_operator_screens(self):
        a, _ = api.create_media(self.admin, "나 매체"), api.create_media(self.admin, "가 매체")
        api.set_media_active(self.admin, a.media_id, False)
        self.assertEqual([m.name for m in api.list_media(self.admin)], ["가 매체", "나 매체"])  # 이름순, 비활성 포함
        self.assertEqual(api.get_media(self.admin, a.media_id), dataclasses.replace(a, is_active=False))
        for missing in (uuid.uuid4(), "not-a-uuid"):
            with self.assertRaises(NotFound):
                api.get_media(self.admin, missing)

    def case_policy_history_newest_first(self):
        slot = new_slot(self.admin)
        api.add_policy_version(self.admin, slot.slot_id, 110, 210, 510, "버전 2", expected_version=1, **SHARES)
        history = api.list_policy_versions(self.admin, slot.slot_id)
        self.assertEqual([(p.policy_version, p.floor, p.reason) for p in history], [(2, 110, "버전 2"), (1, 100, "초기 설정")])
        with self.assertRaises(NotFound):
            api.list_policy_versions(self.admin, uuid.uuid4())

    def case_a_stale_bulk_change_names_the_slot(self):
        """일괄 변경이 충돌로 전부 취소될 때 어느 게재 위치 때문인지 알 수 있다."""
        a, b = new_slot(self.admin, name="첫 배너"), new_slot(self.admin, name="둘째 배너")
        with self.assertRaises(StaleVersion) as e:
            api.add_policy_version_bulk(self.admin, {a.slot_id: 1, b.slot_id: 5}, 500, 600, 700, "일괄", **SHARES)
        self.assertIn("둘째 배너", str(e.exception.detail))

    def case_list_slots_filters_by_media(self):
        a, _ = new_slot(self.admin), new_slot(self.admin)
        self.assertEqual([s.slot_id for s in api.list_slots(media_id=a.media_id)], [a.slot_id])

    def case_get_slots_with_policy_single_query(self):
        slots = [new_slot(self.admin) for _ in range(3)]
        api.add_policy_version(self.admin, slots[0].slot_id, 110, 210, 510, "버전 2", expected_version=1, **SHARES)
        ids = [s.slot_id for s in slots] + [uuid.uuid4()]  # 없는 ID 는 결과에 없다
        with self.assertNumQueries(1):
            result = api.get_slots_with_policy(ids)
        self.assertEqual(set(result), {s.slot_id for s in slots})
        self.assertEqual(result[slots[0].slot_id].policy.policy_version, 2)  # 현재 = 최대 버전
        self.assertEqual(result[slots[1].slot_id].policy.policy_version, 1)

    def case_bulk_lookups_drop_ids_that_are_not_uuids(self):
        """여러 ID 를 한 번에 찾는 조회는 형식이 틀린 값을 오류 없이 버린다(없는 ID 와 같다). 대문자 표기도 같은 ID 다."""
        slot = new_slot(self.admin)
        ids = ["not-a-uuid", "", None, str(slot.slot_id).upper(), slot.slot_id]
        self.assertEqual(set(api.get_slots_with_policy(ids)), {slot.slot_id})
        self.assertEqual(api.slot_names(ids), {slot.slot_id: slot.name})

    def case_api_returns_frozen_values_not_models(self):
        slot = new_slot(self.admin)
        for value in (slot, slot.policy, api.get_slot(slot.slot_id), api.create_media(self.admin, "값 매체"), api.list_slots()[0]):
            self.assertFalse(isinstance(value, Model))
            self.assertTrue(dataclasses.is_dataclass(value))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            slot.name = "바꿈"

    def test_policy_service(self):
        self.run_cases()


@tag("security")
class MastersAuthorizationAndAuditTests(Cases, TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.slot = new_slot(self.admin)

    def calls(self, actor):
        s = self.slot
        return [
            lambda: api.create_media(actor, "새 매체"),
            lambda: api.set_media_active(actor, s.media_id, False),
            lambda: api.create_slot(actor, s.media_id, "다른 배너", 100, 200, 300, "사유", audience="individual", **SHARES),
            lambda: api.add_policy_version(actor, s.slot_id, 100, 200, 300, "사유", expected_version=1, **SHARES),
            lambda: api.add_policy_version_bulk(actor, {s.slot_id: 1}, 100, 200, 300, "사유", **SHARES),
            lambda: api.set_slot_active(actor, s.slot_id, False),
            lambda: api.list_media(actor),
            lambda: api.list_policy_versions(actor, s.slot_id),
            lambda: api.get_media(actor, s.media_id),
        ]

    def case_non_admin_actor_rejected(self):
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

    def case_admin_actions_are_audited_with_request_id(self):
        AuditLog.objects.all()  # 시작 상태 기준: setUp 의 슬롯 생성 기록은 이미 있다
        token = request_id_var.set("11111111-2222-3333-4444-555555555555")
        try:
            api.add_policy_version(self.admin, self.slot.slot_id, 120, 220, 520, "정책 상향", expected_version=1, impression_share=1, click_share=98, conversion_share=1)
            api.set_slot_active(self.admin, self.slot.slot_id, False)
        finally:
            request_id_var.reset(token)
        entry = AuditLog.objects.get(action="masters.policy_added")
        self.assertEqual((entry.actor_id, entry.target_type, entry.target_id), (self.admin.pk, "masters.slot", str(self.slot.slot_id)))
        self.assertEqual(entry.request_id, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(entry.detail["version"], 2)
        self.assertEqual({k: entry.detail[k] for k in ("impression_share", "click_share", "conversion_share")},
                         {"impression_share": 1, "click_share": 98, "conversion_share": 1})  # 바꾼 비율과 이전 비율이 감사 기록에 남는다(6-10b)
        self.assertEqual(entry.detail["previous"], {"floor": 100, "base": 200, "cap": 500, **SHARES})
        self.assertEqual(entry.detail["reason"], "정책 상향")
        created = AuditLog.objects.get(action="masters.slot_created", target_id=str(self.slot.slot_id))
        self.assertEqual({k: created.detail[k] for k in SHARES}, SHARES)  # 처음 비율도 감사 기록에 남는다
        self.assertTrue(AuditLog.objects.filter(action="masters.slot_active_changed", target_id=str(self.slot.slot_id)).exists())
        self.assertTrue(AuditLog.objects.filter(action__in=["masters.media_created", "masters.slot_created"]).count() >= 2)

    def case_audit_without_request_context_has_empty_request_id(self):
        entry = AuditLog.objects.get(action="masters.slot_created")
        self.assertEqual(entry.request_id, "")

    def test_masters_authorization_and_audit(self):
        self.run_cases()


class ConcurrentPolicyTests(TransactionTestCase):
    def test_concurrent_policy_saves_only_one_wins(self):
        """같은 `expected_version` 으로 동시에 저장하면 정확히 한쪽만 성공한다."""
        admin_a, admin_b = make_admin(), make_admin()
        slot = new_slot(admin_a)
        results, errors = run_together([lambda a=a, cap=cap: api.add_policy_version(a, slot.slot_id, 110, 210, cap, "동시 변경", expected_version=1, **SHARES)
                                        for a, cap in ((admin_a, 600), (admin_b, 700))])
        self.assertEqual(([type(e).__name__ for e in errors], sum(r is not None for r in results)), (["StaleVersion"], 1), errors)  # 진 쪽은 충돌 안내여야 한다(교착·잠금 초과 같은 DB 오류가 아니다)
        self.assertEqual(versions(slot.slot_id), [1, 2])  # 두 번째 버전이 정확히 하나
        self.assertIn(api.get_slot(slot.slot_id).policy.cap, (600, 700))
