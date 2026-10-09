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
from tests.factories import DAY, NOW, SUBJECT, World, png_file

UNIT = "IMPRESSION"


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
        self.assertEqual((before.chosen.applied_amount, before.chosen.bid_amount, before.chosen.title), (30, 30, "제목"))
        raw_before = list(Decision.objects.values())

        campaigns.add_bid(w.adv, w.group.ad_group_id, 99, expected_version=1, now=NOW)
        masters.add_policy_version(w.admin, w.slot.slot_id, 1, 2, 3, "정책 대폭 변경", expected_version=1)
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
        self.assertEqual(Decision.objects.get(pk=row.pk).applied_amount, 30)

    def test_chosen_columns_are_all_or_none_in_db(self):
        base = dict(media_id=uuid.uuid4(), slot_id=uuid.uuid4(), subject_id=SUBJECT, audience="individual", selection_policy="p", candidate_count=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Decision.objects.create(campaign_id=uuid.uuid4(), **base)  # 일부만 채움
        Decision.objects.create(**base)  # 광고 없음

    def test_decision_records_both_versions_and_policy_name(self):
        w = World()
        masters.add_policy_version(w.admin, w.slot.slot_id, 10, 20, 50, "v2", expected_version=1)
        campaigns.add_bid(w.adv, w.group.ad_group_id, 35, expected_version=1, now=NOW)
        d = decide(w)
        self.assertEqual((d.chosen.bid_version, d.chosen.policy_version, d.chosen.bid_amount, d.chosen.applied_amount), (2, 2, 35, 35))
        self.assertEqual(d.selection_policy, "highest-bid/v1")
        self.assertEqual((d.trace["policy"], d.trace["picked"]), ("highest-bid/v1", str(w.group.ad_group_id)))
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

    def test_inactive_slot_of_an_active_media_is_recorded_as_no_ad(self):
        """DRD D-1: 꺼진 슬롯은 후보가 있어도 광고 없음으로 기록한다(계약 C1: 201 + `ad: null`)."""
        w = World()
        masters.set_slot_active(w.admin, w.slot.slot_id, False)
        d = decide(w)
        self.assertIsNone(d.chosen)
        self.assertEqual((Decision.objects.count(), d.candidate_count), (1, 0))
        masters.set_slot_active(w.admin, w.slot.slot_id, True)
        self.assertIsNotNone(decide(w).chosen)  # 다시 켜면 광고가 나간다

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
        billing.charge_for_reaction(owner, cid, UNIT, UNIT, 4_990, "m:r1", now=NOW)
        d = decide(w)
        self.assertEqual((d.chosen, d.rejected_counts), (None, {"budget_exhausted": 1}))  # 남은 10 < 적용 금액 30
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
        campaigns.add_bid(w.adv, w.group.ad_group_id, 5, expected_version=1, now=NOW)  # 하한 10 미만
        self.assertEqual(decide(w).rejected_counts, {"below_floor": 1})
        campaigns.add_bid(w.adv, w.group.ad_group_id, 500, expected_version=2, now=NOW)  # 상한 50 초과
        d = decide(w)
        self.assertEqual((d.chosen.bid_amount, d.chosen.applied_amount), (500, 50))  # 입찰 원금액과 적용 금액이 함께 남는다

    def test_unit_aware_candidates(self):
        """슬롯과 과금 단위가 다른 광고그룹은 후보가 되지 않는다(서비스가 막지만 구조적 일관성을 한 번 더 확인)."""
        from campaigns.models import AdGroup

        w = World()
        AdGroup.objects.filter(pk=w.group.ad_group_id).update(pricing_unit="CLICK")  # 서비스를 우회한 불일치 상태
        self.assertEqual(decide(w).candidate_count, 0)

    def test_two_advertisers_compete_and_tie_is_random_but_reproducible(self):
        w = World()
        slot_id = w.slot.slot_id
        from tests.factories import make_advertiser  # 같은 슬롯에 경쟁 광고주를 하나 더 둔다

        adv2 = make_advertiser()
        billing.grant_signup(adv2, now=NOW)
        camp2 = campaigns.create_campaign(adv2, "경쟁", NOW - DAY, None, 5_000, now=NOW)
        group2 = campaigns.create_ad_group(adv2, camp2.campaign_id, "경쟁 그룹", UNIT, [slot_id], bid_amount=500, now=NOW)  # 상한 50 으로 적용
        campaigns.create_creative(adv2, group2.ad_group_id, "경쟁 광고", "https://rival.example", png_file((3, 3, 3)), now=NOW)
        campaigns.add_bid(w.adv, w.group.ad_group_id, 400, expected_version=1, now=NOW)  # 둘 다 상한 50 → 동점
        winners = {decide(w, rng=Random(seed)).chosen.campaign_id for seed in range(40)}
        self.assertEqual(winners, {w.campaign.campaign_id, camp2.campaign_id})  # 동점이면 고르게 뽑힌다
        self.assertEqual(decide(w, rng=Random(5)).chosen.campaign_id, decide(w, rng=Random(5)).chosen.campaign_id)  # 시드 고정이면 재현


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
        self.assertEqual((default.selection_policy, swapped.selection_policy), ("highest-bid/v1", "lowest-bid/v1"))
        a, b = Decision.objects.get(decision_id=default.decision_id), Decision.objects.get(decision_id=swapped.decision_id)
        self.assertEqual({k for k in vars(a) if not k.startswith("_")}, {k for k in vars(b) if not k.startswith("_")})  # 열 구조가 같다
        self.assertEqual((a.applied_amount, b.applied_amount), (30, 30))
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
        root = Path(__file__).resolve().parent.parent / "records"
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
        masters.add_policy_version(w.admin, w.slot.slot_id, 10, 20, 50, "v2", expected_version=1)
        new_bid = campaigns.add_bid(w.adv, w.group.ad_group_id, 40, expected_version=1, now=NOW)
        d = decide(w)
        self.assertEqual(d.chosen.bid_id, new_bid.bid_id)
        self.assertEqual(d.chosen.bid_id, Bid.objects.get(ad_group_id=w.group.ad_group_id, bid_version=2).bid_id)
        self.assertEqual(d.chosen.bid_policy_id, BidPolicy.objects.get(slot_id=w.slot.slot_id, policy_version=2).bid_policy_id)
        campaigns.add_bid(w.adv, w.group.ad_group_id, 45, expected_version=2, now=NOW)  # 나중 변경은 과거 결정에 영향 없음
        self.assertEqual(records.get_decision(w.slot.media_id, d.decision_id).chosen.bid_id, new_bid.bid_id)
        self.assertIsNone(decide(World(with_creative=False)).chosen)

    def test_version_rows_have_unique_immutable_uuids_exposed_by_api(self):
        w = World()
        v1 = campaigns.list_bids(w.adv, w.group.ad_group_id)[0]
        v2 = campaigns.add_bid(w.adv, w.group.ad_group_id, 40, expected_version=1, now=NOW)
        self.assertNotEqual(v1.bid_id, v2.bid_id)
        self.assertEqual(campaigns.get_ad_group(w.adv, w.group.ad_group_id).current_bid.bid_id, v2.bid_id)
        p1 = masters.get_slot(w.slot.slot_id).policy
        p2 = masters.add_policy_version(w.admin, w.slot.slot_id, 11, 21, 51, "v2", expected_version=1)
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
