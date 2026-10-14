import re
import uuid
from pathlib import Path
from random import Random
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings, tag

from billing import api as billing
from campaigns import api as campaigns
from engine import api as engine
from foundation.errors import Forbidden, NotFound
from foundation.models import AppendOnlyError
from masters import api as masters
from records import api as records
from records.models import Decision, Reaction
from tests.support.factories import DAY, NOW, SHARES, SUBJECT, WHOLE, World, png_file



def decide(w, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("rng", Random(1))
    kw.setdefault("subject_id", SUBJECT)
    return records.decide(w.slot.media_id, w.slot.slot_id, **kw)


@tag("security")
class DecisionSnapshotTests(TestCase):
    def test_decision_snapshot_survives_edits(self):
        """입찰·정책·소재를 고치고 캠페인을 중단·종료해도 과거 결정은 변하지 않는다(설계 §4.4-1)."""
        w = World()
        d = decide(w, subject_id="learner-1")
        before = records.get_decision(w.slot.media_id, d.decision_id)
        self.assertEqual((before.chosen.applied_amount, before.chosen.bid_amount, before.chosen.title), (300, 300, "제목"))
        raw_before = list(Decision.objects.values())

        campaigns.add_bid(w.adv, w.group.ad_group_id, 990, expected_version=1, now=NOW)
        masters.add_policy_version(w.admin, w.slot.slot_id, 100, 200, 300, "정책 대폭 변경", expected_version=1, **SHARES)
        campaigns.update_creative(w.adv, w.creative.creative_id, {"title": "완전히 다른 제목", "redirect_url": "https://changed.example"}, now=NOW)
        campaigns.replace_creative_image(w.adv, w.creative.creative_id, png_file((1, 2, 3)), now=NOW)
        campaigns.suspend_campaign(w.admin, w.campaign.campaign_id, "사유", now=NOW)
        campaigns.release_campaign(w.admin, w.campaign.campaign_id, now=NOW)
        campaigns.end_campaign(w.adv, w.campaign.campaign_id, now=NOW)

        after = records.get_decision(w.slot.media_id, d.decision_id)
        self.assertEqual(after, before)  # 값 객체가 그대로
        self.assertEqual(list(Decision.objects.values()), raw_before)  # 저장된 행도 그대로
        self.assertEqual((after.chosen.title, after.chosen.redirect_url, after.chosen.image_name), ("제목", "https://example.com/landing", w.creative.image_name))

    def test_decision_is_append_only(self):
        w = World()
        d = decide(w)
        row = Decision.objects.get(decision_id=d.decision_id)
        row.applied_amount = 1
        with self.assertRaises(AppendOnlyError):
            row.save()
        with self.assertRaises(AppendOnlyError):
            row.delete()
        with self.assertRaises(AppendOnlyError):
            Decision.objects.filter(pk=row.pk).update(applied_amount=1)
        with self.assertRaises(AppendOnlyError):
            Decision.objects.all().delete()
        clone = Decision(pk=row.pk, media_id=row.media_id, slot_id=row.slot_id, subject_id=SUBJECT, audience="individual", selection_policy="x", candidate_count=0)
        with self.assertRaises((IntegrityError, AppendOnlyError)), transaction.atomic():
            clone.save()
        with self.assertRaises(AppendOnlyError):
            Decision.objects.bulk_create([clone], update_conflicts=True, update_fields=["selection_policy"], unique_fields=["decision_id"])
        self.assertEqual(Decision.objects.get(pk=row.pk).applied_amount, 300)

    def test_chosen_columns_are_all_or_none_in_db(self):
        base = dict(media_id=uuid.uuid4(), slot_id=uuid.uuid4(), subject_id=SUBJECT, audience="individual", selection_policy="p", candidate_count=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Decision.objects.create(campaign_id=uuid.uuid4(), **base)  # 일부만 채움
        Decision.objects.create(**base)  # 광고 없음

    def test_charge_shares_follow_the_policy_rule_in_db(self):
        """결정에 남긴 비율(6-10c)도 DB 가 지킨다: 광고가 있으면 각각 1~98·합 100, 광고 없음이면 비어 있다."""
        base = dict(media_id=uuid.uuid4(), slot_id=uuid.uuid4(), subject_id=SUBJECT, audience="individual", selection_policy="p", candidate_count=1)
        chosen = dict(owner_id=uuid.uuid4(), campaign_id=uuid.uuid4(), ad_group_id=uuid.uuid4(), creative_id=uuid.uuid4(), bid_amount=300, applied_amount=300,
                      bid_version=1, policy_version=1, bid_id=uuid.uuid4(), bid_policy_id=uuid.uuid4(), snapshot={"title": "t", "redirect_url": "u", "image_name": "i"})
        shares = lambda i, c, v: dict(impression_share=i, click_share=c, conversion_share=v)  # noqa: E731
        for label, values in {
            "노출 0%": {**chosen, **shares(0, 2, 98)}, "클릭 0%": {**chosen, **shares(2, 0, 98)}, "전환 0%": {**chosen, **shares(2, 98, 0)},
            "98% 초과": {**chosen, **shares(99, 1, 0)}, "합 99": {**chosen, **shares(97, 1, 1)},
            "합 101": {**chosen, **shares(98, 2, 1)}, "하나 빠짐": {**chosen, "impression_share": 98, "click_share": 2},
            "광고 없음인데 비율": shares(98, 1, 1), "광고 없음인데 노출 비율만": {"impression_share": 98},
            "광고 없음인데 클릭 비율만": {"click_share": 98}, "광고 없음인데 전환 비율만": {"conversion_share": 98},
        }.items():
            with self.subTest(label), self.assertRaises(IntegrityError), transaction.atomic():
                Decision.objects.create(**base, **values)
        Decision.objects.create(**base, **chosen, **shares(98, 1, 1))
        Decision.objects.create(**base, **chosen, **shares(1, 1, 98))

    def test_decision_records_both_versions_and_policy_name(self):
        w = World()
        masters.add_policy_version(w.admin, w.slot.slot_id, 100, 200, 500, "v2", expected_version=1, **SHARES)
        campaigns.add_bid(w.adv, w.group.ad_group_id, 350, expected_version=1, now=NOW)
        d = decide(w)
        self.assertEqual((d.chosen.bid_version, d.chosen.policy_version, d.chosen.bid_amount, d.chosen.applied_amount), (2, 2, 350, 350))
        self.assertEqual(d.selection_policy, "weighted-by-bid/v1")
        self.assertEqual((d.trace["policy"], d.trace["picked"]), ("weighted-by-bid/v1", str(w.group.ad_group_id)))
        self.assertEqual((d.trace["total"], d.trace["weight"]), (900, 900))  # 판정에 쓴 정책 v2(하한 100·상한 500)의 가중치: 400 + 2 × (350 − 100)
        self.assertEqual((d.candidate_count, d.rejected_counts), (1, {}))
        self.assertEqual(d.chosen.owner_id, w.adv.pk)
        self.assertTrue(d.chosen.image_url.endswith(f"/assets/{w.creative.image_name}"))
        self.assertEqual(Decision.objects.get(decision_id=d.decision_id).decided_at, NOW)

    def test_no_ad_is_recorded_as_decision(self):
        w = World(with_creative=False)  # 소재가 없어 후보 없음
        d = decide(w)
        self.assertIsNone(d.chosen)
        self.assertEqual((d.candidate_count, d.rejected_counts), (0, {}))
        row = Decision.objects.get(decision_id=d.decision_id)
        self.assertIsNone(row.creative_id)
        self.assertEqual(Decision.objects.count(), 1)  # 광고 없음도 한 건으로 남는다

    def test_decision_lookup_is_scoped_to_its_media(self):
        w, other = World(), World()
        d = decide(w)
        with self.assertRaises(NotFound):
            records.get_decision(other.slot.media_id, d.decision_id)  # 다른 매체는 없는 것과 같다
        for bad in ("nope", uuid.uuid4()):
            with self.assertRaises(NotFound):
                records.get_decision(w.slot.media_id, bad)

    def test_decision_not_saved_when_storage_fails(self):
        w = World()
        with mock.patch.object(Decision._default_manager, "create", side_effect=IntegrityError("disk full")):
            with self.assertRaises(IntegrityError):
                decide(w)
        self.assertEqual(Decision.objects.count(), 0)  # 예외가 나가서 decision_id 가 응답으로 나가지 않는다


class SlotValidationTests(TestCase):
    def test_other_media_and_missing_slots_are_not_found_and_leave_no_decision(self):
        w, other = World(), World()
        with self.assertRaises(NotFound):
            records.decide(other.slot.media_id, w.slot.slot_id, now=NOW)  # 다른 매체의 슬롯
        with self.assertRaises(NotFound):
            records.decide(w.slot.media_id, uuid.uuid4(), now=NOW)
        with self.assertRaises(NotFound):
            records.decide("nope", "nope", now=NOW)
        self.assertEqual(Decision.objects.count(), 0)

    def test_inactive_media_is_forbidden_and_leaves_no_decision(self):
        w = World()
        masters.set_media_active(w.admin, w.slot.media_id, False)
        with self.assertRaises(Forbidden):
            decide(w)
        self.assertEqual(Decision.objects.count(), 0)

    def test_context_is_stored_with_the_decision(self):
        w = World()
        d = decide(w, context={"scene": "lobby"})
        self.assertEqual(Decision.objects.get(pk=d.decision_id).context, {"scene": "lobby"})
        self.assertEqual(Decision.objects.get(pk=decide(w).decision_id).context, {})


class GatingTests(TestCase):
    def test_ended_and_stale_active_campaign_excluded(self):
        w = World()
        self.assertIsNotNone(decide(w, now=NOW).chosen)
        d = decide(w, now=NOW + 11 * DAY)  # 저장된 상태는 아직 ACTIVE 지만 기간이 지났다 → engine 이 거른다
        self.assertEqual((d.chosen, d.rejected_counts, d.candidate_count), (None, {"expired": 1}, 1))
        campaigns.end_campaign(w.adv, w.campaign.campaign_id, now=NOW)
        self.assertEqual(decide(w).candidate_count, 0)  # 저장된 ENDED 는 구조적으로 후보가 아니다

    def test_pause_suspend_and_disabled_flags_exclude(self):
        w = World()
        campaigns.update_campaign(w.adv, w.campaign.campaign_id, {"status": "PAUSED"}, now=NOW)
        self.assertIsNone(decide(w).chosen)
        campaigns.update_campaign(w.adv, w.campaign.campaign_id, {"status": "ACTIVE"}, now=NOW)
        self.assertIsNotNone(decide(w).chosen)
        campaigns.suspend_campaign(w.admin, w.campaign.campaign_id, "사유", now=NOW)
        self.assertIsNone(decide(w).chosen)

    def test_wallet_and_budget_gate_exposure(self):
        w = World()
        owner, cid = w.adv.pk, w.campaign.campaign_id
        self.assertIsNotNone(decide(w).chosen)
        # 일예산 소진: 한도 5,000 을 과금으로 채우면 후보에서 빠지고, 예산을 늘리면 다시 노출된다
        campaigns.update_campaign(w.adv, cid, {"daily_budget": 5_000}, now=NOW)
        billing.charge_for_reaction(owner, cid, "IMPRESSION", WHOLE, 4_990, "m:r1", now=NOW)
        d = decide(w)
        self.assertEqual((d.chosen, d.rejected_counts), (None, {"budget_exhausted": 1}))  # 남은 10 < 적용 금액 300
        campaigns.update_campaign(w.adv, cid, {"daily_budget": 10_000}, now=NOW)
        self.assertIsNotNone(decide(w).chosen)
        # 잔액 소진: 잔액을 0 으로 만들면 빠지고, 충전(관리자 조정)하면 다시 노출된다
        left = billing.get_wallet(w.adv, now=NOW).balance
        billing.adjust(w.admin, owner, -left, "전액 회수", now=NOW)
        self.assertEqual(decide(w).rejected_counts, {"insufficient_balance": 1})
        billing.adjust(w.admin, owner, 1_000, "충전", now=NOW)
        self.assertIsNotNone(decide(w).chosen)
        # 다음 날에는 일예산이 다시 열린다
        billing.adjust(w.admin, owner, 100_000, "충전", now=NOW)
        campaigns.update_campaign(w.adv, cid, {"daily_budget": 4_995}, now=NOW)  # 오늘 이미 4,990 을 썼으니 남은 5
        self.assertEqual(decide(w).rejected_counts, {"budget_exhausted": 1})
        self.assertIsNotNone(decide(w, now=NOW + DAY).chosen)

    def test_below_floor_bid_is_excluded_and_cap_applies(self):
        w = World()
        campaigns.add_bid(w.adv, w.group.ad_group_id, 50, expected_version=1, now=NOW)  # 하한 100 미만
        self.assertEqual(decide(w).rejected_counts, {"below_floor": 1})
        campaigns.add_bid(w.adv, w.group.ad_group_id, 5000, expected_version=2, now=NOW)  # 상한 500 초과
        d = decide(w)
        self.assertEqual((d.chosen.bid_amount, d.chosen.applied_amount), (5000, 500))  # 입찰 원금액과 적용 금액이 함께 남는다


class PolicySwapTests(TestCase):
    def test_selection_policy_swap_by_setting_keeps_decision_shape(self):
        class Lowest:
            name = "lowest-bid/v1"

            def select(self, candidates, request, rng):
                return engine.Selection(min(candidates, key=lambda c: c.applied_amount) if candidates else None, {"policy": self.name})

        engine.register_policy(Lowest())
        self.addCleanup(engine.unregister_policy, "lowest-bid/v1")
        w = World()
        default = decide(w)
        with override_settings(ADS_SELECTION_POLICY="lowest-bid/v1"):
            swapped = decide(w)
        self.assertEqual((default.selection_policy, swapped.selection_policy), ("weighted-by-bid/v1", "lowest-bid/v1"))
        a, b = Decision.objects.get(decision_id=default.decision_id), Decision.objects.get(decision_id=swapped.decision_id)
        self.assertEqual({k for k in vars(a) if not k.startswith("_")}, {k for k in vars(b) if not k.startswith("_")})  # 열 구조가 같다
        self.assertEqual((a.applied_amount, b.applied_amount), (300, 300))
        with override_settings(ADS_SELECTION_POLICY="no-such/v1"):
            with self.assertRaises(engine.UnknownName):
                decide(w)
        self.assertEqual(Decision.objects.count(), 2)  # 설정 오류는 결정을 남기지 않는다

    def test_filters_are_chosen_by_setting(self):
        w = World()
        campaigns.update_campaign(w.adv, w.campaign.campaign_id, {"status": "ACTIVE"}, now=NOW)
        campaigns.update_ad_group(w.adv, w.group.ad_group_id, {"enabled": True}, now=NOW)
        with override_settings(ADS_ENGINE_FILTERS=("period", "floor", "budget", "balance")):  # status 필터를 뺀 구성
            self.assertIsNotNone(decide(w).chosen)
        with override_settings(ADS_ENGINE_FILTERS=("status", "period", "floor", "budget", "no-such-filter")):
            with self.assertRaises(engine.UnknownName):
                decide(w)  # 알 수 없는 필터 이름은 즉시 오류


@tag("security")
class OnlyEngineDecidesTests(TestCase):
    def test_only_engine_decides(self):
        """records 에는 적용 금액·하한·종료 판정 코드가 없다. engine.api.decide 호출만 있다(설계 §4.2)."""
        root = Path(__file__).resolve().parents[2] / "records"
        forbidden = re.compile(r"effect_of|is_expired|\bfloor\b\s*[<>]|\bcap\b\s*[<>]|min\(.*cap|applied_amount\s*=\s*(min|max)")
        hits = []
        for path in root.rglob("*.py"):
            if "migrations" in path.parts:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if forbidden.search(line) and not line.lstrip().startswith(("#", '"""')):
                    hits.append(f"{path.name}:{n}: {line.strip()}")
        self.assertEqual(hits, [])
        self.assertIn("engine_decide(", (root / "services.py").read_text(encoding="utf-8"))


class VersionRowIdentityTests(TestCase):
    def test_decision_records_the_uuids_of_the_exact_bid_and_policy_rows(self):
        """팀 DRD 의 selected_bid_id·selected_bid_policy_id 에 해당한다: 판정에 쓴 버전 행을 UUID 로 가리킨다."""
        from campaigns.models import Bid
        from masters.models import BidPolicy

        w = World()
        masters.add_policy_version(w.admin, w.slot.slot_id, 100, 200, 500, "v2", expected_version=1, **SHARES)
        new_bid = campaigns.add_bid(w.adv, w.group.ad_group_id, 400, expected_version=1, now=NOW)
        d = decide(w)
        self.assertEqual(d.chosen.bid_id, new_bid.bid_id)
        self.assertEqual(d.chosen.bid_id, Bid.objects.get(ad_group_id=w.group.ad_group_id, bid_version=2).bid_id)
        self.assertEqual(d.chosen.bid_policy_id, BidPolicy.objects.get(slot_id=w.slot.slot_id, policy_version=2).bid_policy_id)
        campaigns.add_bid(w.adv, w.group.ad_group_id, 450, expected_version=2, now=NOW)  # 나중 변경은 과거 결정에 영향 없음
        self.assertEqual(records.get_decision(w.slot.media_id, d.decision_id).chosen.bid_id, new_bid.bid_id)
        self.assertIsNone(decide(World(with_creative=False)).chosen)

    def test_two_ad_groups_with_the_same_creative_each_record_their_own_bid_row(self):
        """6-16d(E3): 소재를 여러 광고에 쓸 수 있게 된 뒤(6-9) 후보 사실을 소재 ID 로 묶어, 같은 소재를 고른 광고그룹 둘이 한 구성에 있으면
        한쪽이 덮였다 — 뽑힌 광고그룹과 다른 광고그룹의 입찰 행이 결정과 C2 `ad.decision` 에 남았다(소유자·제목·이미지는 같아 드러나지 않음)."""
        from campaigns.models import Bid
        from events.models import EventOutbox

        w = World()
        second = campaigns.create_ad_group(w.adv, w.campaign.campaign_id, "둘째", [w.slot.slot_id], bid_amount=350, now=NOW)
        campaigns.link_creative(w.adv, second.ad_group_id, w.creative.creative_id, now=NOW, select=True)
        picked = set()
        for seed in range(40):
            d = decide(w, rng=Random(seed))
            expected = Bid.objects.filter(ad_group_id=d.chosen.ad_group_id).latest("bid_version").bid_id
            self.assertEqual(d.chosen.bid_id, expected, seed)
            self.assertEqual(EventOutbox.objects.get(aggregate_id=d.decision_id, event_name="ad.decision").payload["selected"]["bid_id"], str(expected), seed)
            picked.add(d.chosen.ad_group_id)
        self.assertEqual(picked, {w.group.ad_group_id, second.ad_group_id})  # 둘 다 뽑혀야 이 시험이 어느 쪽이 덮이든 잡는다

    def test_version_rows_have_unique_immutable_uuids_exposed_by_api(self):
        w = World()
        v1 = campaigns.list_bids(w.adv, w.group.ad_group_id)[0]
        v2 = campaigns.add_bid(w.adv, w.group.ad_group_id, 400, expected_version=1, now=NOW)
        self.assertNotEqual(v1.bid_id, v2.bid_id)
        self.assertEqual(campaigns.get_ad_group(w.adv, w.group.ad_group_id).current_bid.bid_id, v2.bid_id)
        p1 = masters.get_slot(w.slot.slot_id).policy
        p2 = masters.add_policy_version(w.admin, w.slot.slot_id, 110, 210, 510, "v2", expected_version=1, **SHARES)
        self.assertNotEqual(p1.bid_policy_id, p2.bid_policy_id)
        self.assertEqual(masters.get_slot(w.slot.slot_id).policy.bid_policy_id, p2.bid_policy_id)
        facts = campaigns.candidate_facts_for_slot(w.slot.slot_id)
        self.assertEqual(facts[0].bid_id, v2.bid_id)  # 후보 사실도 최신 버전 행을 가리킨다


@tag("security")
class ReactionInboxConstraintTests(TestCase):
    """수신함의 무결성은 DB 도 지킨다(서비스가 틀려도 잘못된 행이 들어가지 않는다)."""

    def row(self, **kw):
        values = dict(media_id=uuid.uuid4(), reaction_id=uuid.uuid4(), decision_id=uuid.uuid4(), type="CLICK", occurred_at=NOW, raw={})
        values.update(kw)
        if values.get("status", "RECEIVED") != "RECEIVED":
            values.setdefault("basis", {"v": 1})  # 판정한 행에는 근거가 있어야 한다(DB 제약) — 근거를 일부러 빼는 경우만 basis=None 으로 넘긴다
        return Reaction(**values)

    def test_db_rejects_duplicates_per_media_and_invalid_codes(self):
        base = self.row()
        base.save()
        cases = {
            "same media and reaction id": self.row(media_id=base.media_id, reaction_id=base.reaction_id),
            "bad type": self.row(type="VIEW"),
            "bad status": self.row(status="DONE"),
            "reason without rejection": self.row(status="ACCEPTED", reason_code="x"),
            "rejection without reason": self.row(status="REJECTED", processed_at=NOW, applied_rule="once-per-type"),
            "processed without a time": self.row(status="ACCEPTED"),
            "decided without a basis": self.row(status="REJECTED", reason_code="x", applied_rule="x", processed_at=NOW, basis=None),
            "a basis on a row that is not decided": self.row(status="RECEIVED", basis={"v": 1}),
            "received but already processed": self.row(processed_at=NOW),
            "rejected without a rule": self.row(status="REJECTED", reason_code="x", processed_at=NOW),
            "accepted with a rule": self.row(status="ACCEPTED", processed_at=NOW, applied_rule="x"),
        }
        for label, row in cases.items():
            with self.assertRaises(IntegrityError, msg=label), transaction.atomic():
                row.save()
        self.row(reaction_id=base.reaction_id).save()  # 다른 매체는 같은 reaction_id 를 쓸 수 있다
        self.row(status="REJECTED", reason_code="unknown_decision", applied_rule="known-decision", processed_at=NOW).save()
        self.assertEqual(Reaction.objects.count(), 3)

    def test_only_one_reaction_per_type_can_be_accepted_per_person_of_a_decision(self):
        decision, person = uuid.uuid4(), "0197a5c0-0000-7000-8000-000000000001"
        def accepted(person_id=person, rtype="CLICK"):
            return dict(decision_id=decision, type=rtype, status="ACCEPTED", processed_at=NOW, person_id=person_id, accepted_key=f"{decision}:{person_id}:{rtype}")

        self.row(**accepted()).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.row(**accepted()).save()  # 같은 결정·사람·유형의 두 번째 인정
        self.row(**accepted(rtype="IMPRESSION")).save()  # 다른 유형은 된다
        self.row(**accepted(person_id="0197a5c0-0000-7000-8000-000000000002")).save()  # 일괄 슬롯: 다른 사람의 같은 유형은 된다
        for label, bad in {
            "accepted without a key (NULL slips past a unique constraint)": dict(decision_id=decision, status="ACCEPTED", processed_at=NOW, person_id=person),
            "a key on a row that is not accepted": dict(decision_id=decision, accepted_key="x"),
            "a rejected row with a key": dict(decision_id=decision, status="REJECTED", reason_code="r", applied_rule="x", processed_at=NOW, accepted_key="y"),
        }.items():
            with self.subTest(label), self.assertRaises(IntegrityError), transaction.atomic():
                self.row(**bad).save()
        for _ in range(3):  # 인정되지 않은 행(키 없음)은 몇 개든 된다 — NULL 은 서로 다른 값이다
            self.row(decision_id=decision, status="RECEIVED").save()
        for _ in range(2):  # 거부는 몇 개든 된다
            self.row(decision_id=decision, status="REJECTED", reason_code="duplicate_type", applied_rule="once-per-type", processed_at=NOW).save()
