"""2-7 슬롯 성격(`audience`: individual·shared) — 모델·서비스·결정 서비스·결정 API를 한 곳에서 시험한다.

규칙의 원본은 설계 §10 "일괄 슬롯"과 계약 C1 v1.1이다: 성격은 만든 뒤 바뀌지 않고, 개인 슬롯의 결정에는 사람이 있고 일괄 슬롯의 결정에는 없다.
"""
import uuid
from random import Random

from django.db import IntegrityError, transaction
from django.test import TestCase, tag

from foundation.errors import Forbidden, InvalidRequest, NotFound
from foundation.models import AuditLog
from masters import api as masters
from masters.models import Media, Slot
from records import api as records
from records.models import Decision
from tests.support.factories import NOW, SHARES, SUBJECT, World, make_admin
from tests.ops.test_serving_decisions import DecisionApiMixin
from tests.support.cases import Cases


def shared_slot(admin):
    media = masters.create_media(admin, f"일괄 매체-{uuid.uuid4().hex[:6]}")
    return masters.create_slot(admin, media.media_id, "전광판", 100, 200, 500, "초기", audience="shared", **SHARES)


@tag("security")
class SlotModelTests(TestCase):
    def raw(self, **kw):
        media = Media.objects.create(name=f"m-{uuid.uuid4().hex[:6]}")
        return Slot.objects.create(media=media, name="s", **kw)

    def test_db_accepts_only_known_audiences_and_has_no_default(self):
        self.raw(audience="individual")
        self.raw(audience="shared")
        for bad in (dict(audience="everyone"), dict(audience="")):  # 모르는 성격, 기본값 없음 — 만드는 쪽이 정한다
            with self.subTest(bad), self.assertRaises(IntegrityError), transaction.atomic():
                self.raw(**bad)


@tag("security")
class SlotServiceTests(Cases, TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.media = masters.create_media(self.admin, "매체")

    def create(self, name="슬롯", **kw):
        return masters.create_slot(self.admin, self.media.media_id, name, 100, 200, 500, "초기", **kw, **SHARES)

    def case_the_creator_always_chooses_the_audience(self):
        """R18(6-13f): 성격에는 기본값이 없다(모델·서비스 모두) — 만드는 쪽(운영 폼·시험)이 늘 정한다."""
        with self.assertRaises(TypeError):
            masters.create_slot(self.admin, self.media.media_id, "슬롯", 100, 200, 500, "초기", **SHARES)
        slot = self.create(audience="individual")
        self.assertEqual(slot.audience, "individual")
        self.assertEqual(Slot.objects.get(pk=slot.slot_id).audience, "individual")

    def case_shared_slot_is_exposed_through_every_read(self):
        slot = self.create("전광판", audience="shared")
        self.assertEqual(slot.audience, "shared")
        self.assertEqual(masters.get_slot(slot.slot_id).audience, "shared")
        self.assertEqual({s.slot_id: s.audience for s in masters.list_slots(media_id=self.media.media_id)}, {slot.slot_id: "shared"})
        self.assertEqual(masters.get_slots_with_policy([slot.slot_id])[slot.slot_id].audience, "shared")

    def case_unknown_audience_is_400_and_nothing_is_saved(self):
        for bad in ("everyone", "", None, 1):
            with self.subTest(bad), self.assertRaises(InvalidRequest) as caught:
                self.create(audience=bad)
            self.assertEqual(caught.exception.errors[0]["pointer"], "/audience")
        self.assertFalse(Slot.objects.exists())

    def case_creation_is_audited_with_the_audience(self):
        slot = self.create(audience="shared")
        entry = AuditLog.objects.filter(action="masters.slot_created", target_id=str(slot.slot_id)).get()
        self.assertEqual(entry.detail["audience"], "shared")

    def test_slot_service(self):
        self.run_cases()


@tag("security")
class DecisionByAudienceTests(Cases, TestCase):
    def setUp(self):
        self.w = World()

    def decide(self, slot, **kw):
        return records.decide(slot.media_id, slot.slot_id, now=NOW, rng=Random(1), **kw)

    def case_individual_slot_requires_a_subject(self):
        with self.assertRaises(InvalidRequest) as caught:
            self.decide(self.w.slot)
        self.assertEqual(caught.exception.errors[0]["pointer"], "/subject_id")
        self.assertFalse(Decision.objects.exists())
        decision = self.decide(self.w.slot, subject_id=SUBJECT)
        self.assertEqual((decision.audience, decision.subject_id), ("individual", SUBJECT))

    def case_shared_slot_rejects_a_subject_and_stores_none(self):
        slot = shared_slot(self.w.admin)
        with self.assertRaises(InvalidRequest) as caught:
            self.decide(slot, subject_id=SUBJECT)
        self.assertEqual(caught.exception.errors[0]["pointer"], "/subject_id")
        self.assertFalse(Decision.objects.exists())
        decision = self.decide(slot)
        self.assertEqual((decision.audience, decision.subject_id), ("shared", None))
        stored = Decision.objects.get(pk=decision.decision_id)
        self.assertEqual((stored.audience, stored.subject_id), ("shared", None))
        self.assertEqual(records.get_decision(slot.media_id, decision.decision_id).audience, "shared")

    def case_missing_slot_and_inactive_media_come_before_the_subject_check(self):
        """없는·남의 슬롯(404)과 비활성 매체(403)가 먼저다 — subject_id 가 틀려도 슬롯의 존재 여부를 이 오류로 알 수 없다."""
        other = shared_slot(self.w.admin)
        with self.assertRaises(NotFound):
            records.decide(self.w.slot.media_id, other.slot_id, subject_id=SUBJECT, now=NOW)  # 남의 일괄 슬롯 + 사람 → 400 이 아니라 404
        with self.assertRaises(NotFound):
            records.decide(self.w.slot.media_id, uuid.uuid4(), now=NOW)  # 없는 슬롯 + 사람 없음 → 404
        masters.set_media_active(self.w.admin, self.w.slot.media_id, False)
        with self.assertRaises(Forbidden):
            self.decide(self.w.slot)  # 개인 슬롯 + 사람 없음 → 400 이 아니라 403

    def case_inactive_slot_still_checks_the_subject(self):
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        with self.assertRaises(InvalidRequest):
            self.decide(self.w.slot)  # 광고 없음으로 기록되는 경우에도 요청 형식은 같다
        self.assertIsNone(self.decide(self.w.slot, subject_id=SUBJECT).chosen)

    def case_shared_slot_decides_like_any_other_slot(self):
        """일괄 슬롯도 같은 선택·과금 근거 스냅샷을 만든다 — 성격은 사람 유무만 바꾼다."""
        slot, group = self.w.shared_ad()
        decision = self.decide(slot)
        self.assertEqual((decision.chosen.ad_group_id, decision.chosen.applied_amount), (group.ad_group_id, 400))

    def test_decision_by_audience(self):
        self.run_cases()


@tag("security")
class DecisionDbConstraintTests(TestCase):
    def test_db_rejects_a_decision_whose_subject_contradicts_its_audience(self):
        base = dict(media_id=uuid.uuid4(), slot_id=uuid.uuid4(), selection_policy="p", candidate_count=0)
        Decision.objects.create(audience="individual", subject_id=SUBJECT, **base)
        Decision.objects.create(audience="shared", subject_id=None, **base)
        for bad in (dict(audience="individual", subject_id=None), dict(audience="shared", subject_id=SUBJECT), dict(audience="", subject_id=SUBJECT)):
            with self.subTest(bad), self.assertRaises(IntegrityError), transaction.atomic():
                Decision.objects.create(**bad, **base)


@tag("security")
class DecisionApiByAudienceTests(Cases, DecisionApiMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.shared = shared_slot(self.w.admin)
        self.shared_key = masters.issue_media_key(self.w.admin, self.shared.media_id).key

    def post_shared(self, **body):
        return self.post({"slot_id": str(self.shared.slot_id), **body}, key=self.shared_key)

    def case_individual_decision_response_carries_audience_and_matches_the_contract(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(response.json()["audience"], "individual")
        got = self.get(f"/decisions/{response.json()['decision_id']}")
        self.assertContract(self.contract, "/decisions/{decision_id}", "get", got)
        self.assertEqual(got.json()["audience"], "individual")

    def case_shared_decision_without_subject_is_201_and_stores_no_subject(self):
        response = self.post_shared()
        self.assertEqual(response.status_code, 201)
        self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(response.json()["audience"], "shared")
        stored = Decision.objects.get(pk=response.json()["decision_id"])
        self.assertEqual((stored.audience, stored.subject_id), ("shared", None))

    def case_subject_rules_are_400_with_a_pointer_and_nothing_is_recorded(self):
        cases = {
            "individual without subject": self.post({"slot_id": str(self.w.slot.slot_id)}),
            "shared with subject": self.post_shared(subject_id=SUBJECT),
            "shared with malformed subject": self.post_shared(subject_id="learner-1"),
            "individual with null subject": self.post({"slot_id": str(self.w.slot.slot_id), "subject_id": None}),
        }
        for label, response in cases.items():
            self.assertEqual(response.status_code, 400, label)
            self.assertIn("/subject_id", [e["pointer"] for e in response.json()["errors"]], label)
            self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(Decision.objects.count(), 0)

    def case_a_foreign_shared_slot_is_404_even_with_the_wrong_subject_rule(self):
        response = self.post({"slot_id": str(self.shared.slot_id), "subject_id": SUBJECT})  # 다른 매체의 일괄 슬롯 + 사람
        self.assertEqual(response.status_code, 404)
        self.assertContract(self.contract, "/decisions", "post", response)

    def test_decision_api_by_audience(self):
        self.run_cases()
