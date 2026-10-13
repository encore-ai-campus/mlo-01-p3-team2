"""2-9 반응 판정 확장: 퍼널 규칙(순서·기간·클릭 출처·사람·시각·캠페인 종료)과 보류.

규칙의 원본은 설계 §10 "반응 퍼널 규칙"·"일괄 슬롯"·"클릭 출처"와 계약 C1 v1.1이다. 판정 단위는 개인 슬롯이면 결정, 일괄 슬롯이면 (결정, 사람)이다.
시각은 모두 고정한다: 결정은 `NOW`, 반응은 `NOW + 몇 초`에 수신, 판정은 `now=` 로 주입한다.
"""
import json
import uuid
from datetime import timedelta
from random import Random
from unittest import mock

from django.db import connection
from django.test import Client, TestCase, override_settings, tag
from django.test.utils import CaptureQueriesContext

from billing import api as billing
from campaigns.models import Campaign
from masters import api as masters
from records import api as records
from records.models import Reaction
from tests.contract_support import Contract, ProviderContractMixin
from tests.factories import NOW, SHARES, SUBJECT, World, at, png_file

A = "0197a5c0-0000-7000-8000-0000000000a1"
B = "0197a5c0-0000-7000-8000-0000000000b2"
C = "0197a5c0-0000-7000-8000-0000000000c3"
SEC = timedelta(seconds=1)


class FunnelMixin:
    UNIT = "IMPRESSION"  # 광고그룹의 과금 단위 — 금전 영향을 보려면 시험 클래스가 바꾼다

    def setUp(self):
        self.w = World(unit=self.UNIT)
        self.media = self.w.slot.media_id
        self.decision = self.decide(self.w.slot, SUBJECT)

    def decide(self, slot, subject, when=NOW):
        return records.decide(slot.media_id, slot.slot_id, subject_id=subject, now=when, rng=Random(1))

    def shared(self):
        """일괄 슬롯과 거기에 놓인 광고(같은 광고주·캠페인). 결정은 사람 없이 한 번 만든다."""
        slot = masters.create_slot(self.w.admin, self.media, "전광판", "IMPRESSION", 10, 20, 50, "초기", audience="shared", **SHARES)
        group = self.w.api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "일괄 그룹", "IMPRESSION", [slot.slot_id], bid_amount=40, now=NOW)
        self.w.api.create_creative(self.w.adv, group.ad_group_id, "전광판", "https://example.com/board", png_file((3, 3, 3)), now=NOW)
        return slot, self.decide(slot, None)

    def report(self, rtype, decision=None, when=0, occurred=None, subject=None, rid=None):
        """매체가 보고한 반응(노출·전환·매체 클릭)을 `when` 초에 수신했다."""
        decision = decision or self.decision
        view, created = records.receive_reaction(
            self.media, decision.decision_id, rid or uuid.uuid4(), rtype, occurred if occurred is not None else at(when), {"type": rtype},
            subject_id=subject, now=at(when),
        )
        self.assertTrue(created)
        return Reaction.objects.get(pk=view.inbox_id)

    def click(self, decision=None, when=0, viewer=None):
        """서버가 관측한 클릭(`GET /c/{token}`)을 `when` 초에 수신했다."""
        decision = decision or self.decision
        records.observe_click(decision.decision_id, viewer, now=at(when))
        qs = Reaction.objects.filter(decision_id=decision.decision_id, source="server")
        return qs.filter(subject_id=viewer).get() if viewer else qs.get()

    def judge(self, row, when=0):
        outcome = records.process_reaction(row.inbox_id, now=at(when))
        row.refresh_from_db()
        return outcome

    def verdict(self, row):
        return (row.status, row.reason_code, row.applied_rule)

    def accept_impression(self, decision=None, subject=None, when=0):
        row = self.report("IMPRESSION", decision, when=when, subject=subject)
        self.assertEqual(self.judge(row, when), "ACCEPTED")
        return row


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)  # 판정 시각은 시험이 정한다
class FunnelBase(FunnelMixin, TestCase):
    pass


@tag("security")
class ClickSourceTests(FunnelBase):
    def test_a_click_reported_by_the_media_is_rejected_and_never_used(self):
        self.accept_impression()
        reported = self.report("CLICK", when=1)
        self.assertEqual(self.judge(reported, 1), "REJECTED")
        self.assertEqual(self.verdict(reported), ("REJECTED", "click_not_reported", "click-source"))
        conversion = self.report("CONVERSION", when=2)
        self.assertEqual(self.judge(conversion, 2), "PENDING")  # 매체의 클릭 보고는 전환의 전제가 되지 않는다

    def test_the_media_click_does_not_take_the_seat_of_the_real_one(self):
        self.accept_impression()
        self.judge(self.report("CLICK", when=1), 1)
        real = self.click(when=2)
        self.assertEqual(self.judge(real, 2), "ACCEPTED")
        self.assertEqual(Reaction.objects.filter(decision_id=self.decision.decision_id, type="CLICK", status="ACCEPTED").count(), 1)

    def test_removing_the_rule_from_settings_does_not_open_the_gate(self):
        row = self.report("CLICK")
        with override_settings(REACTION_RULES=()):
            self.assertEqual(self.judge(row), "REJECTED")
        self.assertEqual(self.verdict(row), ("REJECTED", "click_not_reported", "guard"))


@tag("security")
class SubjectTests(FunnelBase):
    def test_a_shared_decision_needs_the_person_in_every_report(self):
        _slot, decision = self.shared()
        row = self.report("IMPRESSION", decision)
        self.assertEqual(self.judge(row), "REJECTED")
        self.assertEqual(self.verdict(row), ("REJECTED", "subject_required", "subject"))
        self.assertEqual(self.judge(self.report("IMPRESSION", decision, subject=A)), "ACCEPTED")

    def test_an_individual_report_may_omit_the_person_but_not_contradict_it(self):
        omitted, same, other = (self.report("IMPRESSION", subject=s) for s in (None, SUBJECT, A))
        self.assertEqual(self.judge(other), "REJECTED")
        self.assertEqual(self.verdict(other), ("REJECTED", "subject_mismatch", "subject"))
        self.assertEqual(self.judge(omitted), "ACCEPTED")
        self.assertEqual(self.judge(same), "REJECTED")  # 이미 인정된 노출이 있으니 중복 — 같은 사람의 같은 유형
        self.assertEqual(same.reason_code, "duplicate_type")

    def test_the_person_checks_survive_removing_the_rule(self):
        _slot, decision = self.shared()
        row = self.report("IMPRESSION", decision)
        other = self.report("IMPRESSION", subject=A)
        with override_settings(REACTION_RULES=()):
            self.assertEqual((self.judge(row), self.judge(other)), ("REJECTED", "REJECTED"))
        self.assertEqual((row.reason_code, row.applied_rule), ("subject_required", "guard"))
        self.assertEqual((other.reason_code, other.applied_rule), ("subject_mismatch", "guard"))

    def test_an_accepted_reaction_always_carries_the_judged_person(self):
        row = self.accept_impression()
        self.assertEqual(row.person_id, SUBJECT)  # 보고에 사람이 없어도 개인 슬롯은 결정의 사람
        self.assertEqual(row.accepted_key, f"{self.decision.decision_id}:{SUBJECT}:IMPRESSION")  # 유일 제약이 지키는 (결정, 사람, 유형) 키
        _slot, decision = self.shared()
        self.assertEqual(self.accept_impression(decision, subject=A).person_id, A)


@tag("security")
class OccurredAtTests(FunnelBase):
    def test_the_reported_time_must_be_plausible_within_the_tolerance(self):
        cases = {  # (수신 후 몇 초에 감지했다고 보고) → 기대
            "just after the decision": (0, "ACCEPTED"), "60 s before the decision": (-60, "ACCEPTED"), "61 s before the decision": (-61, "REJECTED"),
            "60 s ahead of receipt": (160, "ACCEPTED"), "61 s ahead of receipt": (161, "REJECTED"),
        }
        for label, (occurred, expected) in cases.items():
            with self.subTest(label):
                row = self.report("IMPRESSION", when=100, occurred=at(occurred))
                self.assertEqual(self.judge(row, 100), expected)
                if expected == "REJECTED":
                    self.assertEqual(self.verdict(row), ("REJECTED", "invalid_occurred_at", "occurred-at"))
                Reaction.objects.filter(pk=row.pk).delete()
                Reaction.objects.filter(decision_id=self.decision.decision_id, status="ACCEPTED").delete()  # 다음 경우를 위해 비운다

    def test_a_conversion_time_is_checked_too_and_the_server_click_is_exempt(self):
        self.accept_impression()
        self.judge(self.click(when=1), 1)
        conversion = self.report("CONVERSION", when=2, occurred=at(-3600))
        self.assertEqual(self.judge(conversion, 2), "REJECTED")
        self.assertEqual(conversion.reason_code, "invalid_occurred_at")
        self.assertEqual(self.click_row().status, "ACCEPTED")

    def click_row(self):
        return Reaction.objects.get(decision_id=self.decision.decision_id, source="server")


@tag("security")
class CampaignOpenTests(FunnelBase):
    def end_at(self, seconds):
        Campaign.objects.filter(pk=self.w.campaign.campaign_id).update(ends_at=at(seconds))

    def test_a_reaction_received_at_or_after_the_end_is_not_accepted_or_charged(self):
        self.end_at(100)
        late = self.report("IMPRESSION", when=100)  # 종료 시각은 미포함 경계: 같은 시각은 종료다
        self.assertEqual(self.judge(late, 200), "REJECTED")  # 처리가 늦어도 판단은 수신 시각 기준이다
        self.assertEqual(self.verdict(late), ("REJECTED", "campaign_ended", "campaign-open"))
        self.assertEqual(Reaction.objects.get(pk=late.pk).person_id, None)
        self.assertEqual(billing.get_wallet(self.w.adv, now=NOW).balance, 50_000)

    def test_received_before_the_end_is_accepted_even_when_processed_after_it(self):
        self.end_at(100)
        early = self.report("IMPRESSION", when=99)
        self.assertEqual(self.judge(early, 500), "ACCEPTED")

    def test_an_extension_after_receipt_is_reflected_at_judgment_time(self):
        self.end_at(100)
        row = self.report("IMPRESSION", when=100)
        self.end_at(1000)  # 연장
        self.assertEqual(self.judge(row, 200), "ACCEPTED")

    def test_the_end_check_survives_removing_the_rule(self):
        self.end_at(10)
        row = self.report("IMPRESSION", when=20)
        with override_settings(REACTION_RULES=()):
            self.assertEqual(self.judge(row, 20), "REJECTED")
        self.assertEqual((row.reason_code, row.applied_rule), ("campaign_ended", "guard"))


@tag("security")
class FunnelOrderTests(FunnelBase):
    def test_a_click_without_an_impression_is_held_and_accepted_when_the_impression_arrives(self):
        click = self.click(when=1)
        self.assertEqual(self.judge(click, 1), "PENDING")
        self.assertEqual((click.status, click.attempts, click.checked_at), ("RECEIVED", 0, at(1)))  # 실패가 아니다: 횟수를 올리지 않는다
        self.accept_impression(when=2)  # 재시도 큐 때문에 늦게 도착한 노출
        self.assertEqual(self.judge(click, 10), "ACCEPTED")

    def test_an_impression_that_is_only_received_does_not_count_yet(self):
        impression = self.report("IMPRESSION", when=0)
        click = self.click(when=1)
        self.assertEqual(self.judge(click, 1), "PENDING")  # 인정되기 전의 노출은 "있음"이 아니다
        self.judge(impression, 2)
        self.assertEqual(self.judge(click, 3), "ACCEPTED")

    def test_the_wait_ends_with_missing_prerequisite_after_the_hold_time(self):
        click = self.click(when=1)
        self.assertEqual(self.judge(click, 1 + 299), "PENDING")
        self.assertEqual(self.judge(click, 1 + 300), "REJECTED")
        self.assertEqual(self.verdict(click), ("REJECTED", "missing_prerequisite", "funnel-order"))

    def test_a_conversion_needs_an_accepted_click_and_never_rides_on_a_pending_one(self):
        conversion = self.report("CONVERSION", when=2)
        self.assertEqual(self.judge(conversion, 2), "PENDING")  # 클릭이 없다
        click = self.click(when=1)
        self.assertEqual(self.judge(conversion, 10), "PENDING")  # 클릭은 있지만 아직 인정 전(노출을 기다린다)
        self.assertEqual(click.status, "RECEIVED")
        self.accept_impression(when=3)
        self.assertEqual(self.judge(click, 11), "ACCEPTED")
        self.assertEqual(self.judge(conversion, 12), "ACCEPTED")

    def test_a_conversion_is_not_accepted_after_the_click_was_rejected(self):
        click = self.click(when=1)
        self.judge(click, 1 + 301)  # 노출 없이 기한 초과
        self.assertEqual(click.status, "REJECTED")
        conversion = self.report("CONVERSION", when=400)
        self.assertEqual(self.judge(conversion, 400), "PENDING")
        self.assertEqual(self.judge(conversion, 400 + 300), "REJECTED")
        self.assertEqual(conversion.reason_code, "missing_prerequisite")

    def test_a_hard_rejection_is_decided_before_waiting(self):
        """기한을 넘긴 클릭은 노출을 기다리지 않고 바로 `window_expired` 다(되돌릴 수 없는 거부가 보류보다 먼저)."""
        click = self.click(when=301)
        self.assertEqual(self.judge(click, 301), "REJECTED")
        self.assertEqual(self.verdict(click), ("REJECTED", "window_expired", "funnel-window"))


@tag("security")
class FunnelWindowTests(FunnelBase):
    def test_a_click_must_come_within_the_click_window_after_the_decision(self):
        self.accept_impression()
        inside, outside = self.click(when=300), None
        self.assertEqual(self.judge(inside, 300), "ACCEPTED")
        w = World()
        d = self.decide(w.slot, SUBJECT, when=NOW)
        self.media = w.slot.media_id
        outside = self.click(d, when=301)
        self.assertEqual(self.judge(outside, 301), "REJECTED")
        self.assertEqual(outside.reason_code, "window_expired")

    def test_the_click_window_is_a_setting(self):
        self.accept_impression()
        with override_settings(REACTION_CLICK_WINDOW_SECONDS=10):
            self.assertEqual(self.judge(self.click(when=11), 11), "REJECTED")

    def probe(self, decision, seconds):
        """`decision` 에 대한 클릭을 `seconds` 초에 수신해 판정한 결과(이전 클릭 행은 지운다 — 유형당 1회 규칙에 걸리지 않게)."""
        Reaction.objects.filter(decision_id=decision.decision_id, type="CLICK").delete()
        row = self.click(decision, when=seconds)
        self.judge(row, seconds)
        return row.reason_code or row.status

    def test_a_next_decision_without_an_impression_does_not_end_the_display(self):
        """검토 2-12 ①: 응답을 못 받아 화면에 적용하지 못한 결정(노출 보고 없음)은 기존 광고를 내리지 않는다."""
        self.accept_impression()
        self.decide(self.w.slot, SUBJECT, when=at(10))  # 같은 슬롯·같은 사람의 다음 결정이지만 노출이 없다
        self.assertEqual(self.probe(self.decision, 100), "ACCEPTED")

    def test_the_display_ends_when_the_next_ads_impression_arrives_plus_the_grace(self):
        self.accept_impression()
        second = self.decide(self.w.slot, SUBJECT, when=at(10))
        self.report("IMPRESSION", second, when=20)  # 다음 광고의 노출이 20초에 도착
        self.assertEqual(self.probe(self.decision, 25), "ACCEPTED")  # 도착 + 5초까지는 인정(경계 포함)
        self.assertEqual(self.probe(self.decision, 25.000001), "display_ended")  # 1마이크로초 뒤는 거부
        with override_settings(REACTION_DISPLAY_GRACE_SECONDS=0):
            self.assertEqual(self.probe(self.decision, 20.5), "display_ended")  # 여유는 설정값

    def test_the_first_impression_among_all_later_decisions_is_the_signal(self):
        """중간 결정에 노출이 없어도, 그 뒤 결정의 노출이 신호다. 여럿이면 가장 먼저 도착한 노출이다."""
        self.accept_impression()
        self.decide(self.w.slot, SUBJECT, when=at(10))  # 노출 없음 — 무시
        third = self.decide(self.w.slot, SUBJECT, when=at(20))
        fourth = self.decide(self.w.slot, SUBJECT, when=at(25))
        self.report("IMPRESSION", third, when=40)
        self.report("IMPRESSION", fourth, when=30)  # 결정은 더 늦지만 노출은 먼저 도착
        self.assertEqual(self.probe(self.decision, 35), "ACCEPTED")
        self.assertEqual(self.probe(self.decision, 36), "display_ended")

    def test_the_impression_counts_whatever_its_verdict_or_whether_it_was_judged(self):
        self.accept_impression()
        second = self.decide(self.w.slot, SUBJECT, when=at(10))
        waiting = self.report("IMPRESSION", second, when=20)  # 아직 판정 전(RECEIVED)
        self.assertEqual(self.probe(self.decision, 26), "display_ended")
        self.judge(waiting, 20)
        Reaction.objects.filter(pk=waiting.pk).update(status="REJECTED", reason_code="duplicate_type", applied_rule="once-per-type", accepted_key=None)  # 거부된 노출
        self.assertEqual(self.probe(self.decision, 26), "display_ended")

    def test_an_earlier_decisions_impression_does_not_end_this_display(self):
        earlier = self.decide(self.w.slot, SUBJECT, when=at(-20))
        self.report("IMPRESSION", earlier, when=-10)
        self.accept_impression()
        self.assertEqual(self.probe(self.decision, 100), "ACCEPTED")

    def test_impressions_of_other_people_or_slots_do_not_end_this_display(self):
        self.accept_impression()
        theirs = self.decide(self.w.slot, A, when=at(10))  # 같은 슬롯, 다른 사람 — 개인 슬롯의 표시 단위는 (슬롯, 사람)
        self.report("IMPRESSION", theirs, when=11, subject=A)
        other = World()
        elsewhere = self.decide(other.slot, SUBJECT, when=at(10))  # 다른 슬롯
        records.receive_reaction(other.slot.media_id, elsewhere.decision_id, uuid.uuid4(), "IMPRESSION", at(11), {}, now=at(11))
        self.assertEqual(self.probe(self.decision, 100), "ACCEPTED")

    def test_in_a_shared_slot_anyones_impression_of_a_later_decision_ends_the_display(self):
        slot, decision = self.shared()
        self.accept_impression(decision, subject=A)
        later = self.decide(slot, None, when=at(10))
        self.assertEqual(self.judge(self.click(decision, when=15, viewer=A), 15), "ACCEPTED")  # 노출이 없는 다음 결정은 무시
        self.report("IMPRESSION", later, when=16, subject=B)  # 다른 사람(B)의 노출이 교체 신호
        self.accept_impression(decision, subject=B, when=16)
        late = self.click(decision, when=22, viewer=B)
        self.assertEqual(self.judge(late, 22), "REJECTED")
        self.assertEqual(late.reason_code, "display_ended")

    def test_the_lookup_is_one_query_however_many_later_decisions_exist(self):
        self.accept_impression()
        for n in range(5):
            self.report("IMPRESSION", self.decide(self.w.slot, SUBJECT, when=at(10 + n)), when=20 + n)
        from records import facts

        with CaptureQueriesContext(connection) as queries:
            facts.display_signal(self.decision)
        self.assertEqual(len(queries), 1)

    def test_a_conversion_must_follow_its_click_within_the_conversion_window(self):
        Campaign.objects.filter(pk=self.w.campaign.campaign_id).update(ends_at=None)  # 30일 뒤에도 캠페인은 진행 중이다
        self.accept_impression()
        self.judge(self.click(when=1), 1)
        day = 24 * 3600
        ok = self.report("CONVERSION", when=1 + 30 * day, occurred=at(1 + 30 * day))
        self.assertEqual(self.judge(ok, 1 + 30 * day), "ACCEPTED")
        Reaction.objects.filter(pk=ok.pk).delete()
        late = self.report("CONVERSION", when=1 + 30 * day + 1, occurred=at(1 + 30 * day + 1))
        self.assertEqual(self.judge(late, 1 + 30 * day + 1), "REJECTED")
        self.assertEqual(self.verdict(late), ("REJECTED", "window_expired", "funnel-window"))


@tag("security")
class SharedSlotFunnelTests(FunnelBase):
    def setUp(self):
        super().setUp()
        self.slot, self.shared_decision = self.shared()

    def test_each_person_has_their_own_funnel_and_their_own_seats(self):
        for person in (A, B):
            self.accept_impression(self.shared_decision, subject=person)
        self.assertEqual(self.judge(self.click(self.shared_decision, when=1, viewer=A), 1), "ACCEPTED")
        again = self.report("IMPRESSION", self.shared_decision, when=2, subject=A)
        self.assertEqual(self.judge(again, 2), "REJECTED")  # 같은 사람의 같은 유형은 한 번
        self.assertEqual(again.reason_code, "duplicate_type")
        accepted = Reaction.objects.filter(decision_id=self.shared_decision.decision_id, status="ACCEPTED")
        self.assertEqual(sorted((r.person_id, r.type) for r in accepted), [(A, "CLICK"), (A, "IMPRESSION"), (B, "IMPRESSION")])

    def test_one_persons_impression_does_not_admit_another_persons_click(self):
        self.accept_impression(self.shared_decision, subject=A)
        other = self.click(self.shared_decision, when=1, viewer=B)
        self.assertEqual(self.judge(other, 1), "PENDING")
        self.assertEqual(self.judge(other, 1 + 300), "REJECTED")
        self.assertEqual(other.reason_code, "missing_prerequisite")

    def test_a_click_with_an_arbitrary_s_value_is_never_accepted_without_that_persons_impression(self):
        """`?s=` 는 최종 사용자가 마음대로 바꿀 수 있다 — 막는 장치는 같은 사람의 인정된 노출을 요구하는 순서 규칙이다."""
        self.accept_impression(self.shared_decision, subject=A)
        forged = [self.click(self.shared_decision, when=1, viewer=str(uuid.uuid4())) for _ in range(5)]
        for row in forged:
            self.assertEqual(self.judge(row, 1), "PENDING")
            self.assertEqual(self.judge(row, 400), "REJECTED")
            self.assertEqual(row.reason_code, "missing_prerequisite")
        self.assertFalse(Reaction.objects.filter(type="CLICK", status="ACCEPTED").exists())

    def test_a_conversion_follows_that_persons_click_only(self):
        for person in (A, B):
            self.accept_impression(self.shared_decision, subject=person)
        self.judge(self.click(self.shared_decision, when=1, viewer=A), 1)
        mine = self.report("CONVERSION", self.shared_decision, when=2, subject=A)
        theirs = self.report("CONVERSION", self.shared_decision, when=2, subject=B)
        self.assertEqual((self.judge(mine, 2), self.judge(theirs, 2)), ("ACCEPTED", "PENDING"))


@tag("security")
class HoldQueueTests(FunnelBase):
    def test_held_reactions_are_rechecked_only_after_the_interval(self):
        click = self.click(when=0)
        self.assertEqual(records.process_pending(now=at(0))["pending"], 1)
        self.assertEqual(sum(records.process_pending(now=at(4)).values()), 0)  # 간격(30초, 안전망) 전에는 다시 보지 않는다
        self.accept_impression(when=4)
        self.assertEqual(records.process_pending(now=at(5))["accepted"], 1)
        click.refresh_from_db()
        self.assertEqual(click.status, "ACCEPTED")

    def test_the_prerequisite_finishing_wakes_the_held_reaction_without_waiting_for_the_interval(self):
        """DB-1d: 앞 단계가 끝났다는 사건이 생기면 같은 결정의 보류분을 바로 다시 판정한다 — 보류를 짧은 주기로 계속 다시 보지 않아도 된다."""
        click = self.click(when=0)
        self.assertEqual(records.process_pending(now=at(0))["pending"], 1)
        self.assertEqual(Reaction.objects.get(pk=click.pk).checked_at, at(0))
        impression = self.report("IMPRESSION", when=1)
        self.assertEqual(records.process_reaction(impression.inbox_id, now=at(1)), "ACCEPTED")
        self.assertIsNone(Reaction.objects.get(pk=click.pk).checked_at)  # 깨워졌다 — 간격(30초)이 지나지 않았는데도
        self.assertEqual(records.process_pending(now=at(2))["accepted"], 1)
        self.assertEqual(Reaction.objects.get(pk=click.pk).status, "ACCEPTED")

    def test_a_finished_reaction_of_another_decision_or_media_does_not_wake_it(self):
        click = self.click(when=0)
        records.process_pending(now=at(0))
        other = World()
        elsewhere = records.decide(other.slot.media_id, other.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(other.slot.media_id, elsewhere.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=at(1))
        records.process_reaction(view.inbox_id, now=at(1))  # 다른 결정
        foreign, _ = records.receive_reaction(other.slot.media_id, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=at(1))
        records.process_reaction(foreign.inbox_id, now=at(1))  # 같은 결정이지만 다른 매체의 보고(거부된다)
        self.assertEqual(Reaction.objects.get(pk=click.pk).checked_at, at(0))  # 그대로다

    def test_the_interval_is_still_the_safety_net_for_the_deadline(self):
        """깨울 사건이 없어도(앞 단계가 끝내 오지 않아도) 기한이 지나면 안전망 주기에 `missing_prerequisite` 로 거부된다."""
        click = self.click(when=0)
        records.process_pending(now=at(0))
        self.assertEqual(sum(records.process_pending(now=at(29)).values()), 0)
        self.assertEqual(records.process_pending(now=at(301))["rejected"], 1)
        self.assertEqual(Reaction.objects.get(pk=click.pk).reason_code, "missing_prerequisite")

    def test_never_checked_reactions_come_before_held_ones_whatever_their_age(self):
        """정렬: 한 번도 확인하지 않은(또는 깨워진) 것 먼저, 그다음은 마지막 확인이 오래된 순 — 보류분이 쌓여도 새 반응이 밀리지 않는다."""
        _slot, decision = self.shared()
        old_held = self.click(decision, when=0, viewer=A)
        records.process_pending(now=at(0))  # old_held 확인 @0
        newer_held = self.click(decision, when=1, viewer=B)
        records.process_pending(now=at(10), limit=1)  # newer_held 확인 @10 (old_held 는 간격 전이라 건너뛴다)
        fresh = self.report("IMPRESSION", when=20)  # 접수가 가장 늦지만 한 번도 확인하지 않았다
        order = []
        from records import processing

        original = processing.process_reaction
        with mock.patch("records.processing.process_reaction", side_effect=lambda i, now=None: (order.append(i), original(i, now=now))[1]):
            records.process_pending(now=at(100), limit=10)
        self.assertEqual(order[:3], [fresh.inbox_id, old_held.inbox_id, newer_held.inbox_id])

    def test_a_pile_of_held_reactions_does_not_starve_new_ones(self):
        """보류분은 마지막으로 손댄 순서로 돌려 처리한다 — 보류 N 건이 있어도 새 반응은 몇 번의 처리 안에 판정된다."""
        _slot, decision = self.shared()
        held = [self.click(decision, when=0, viewer=str(uuid.uuid4())) for _ in range(6)]
        records.process_pending(limit=100, now=at(0))
        self.assertTrue(all(Reaction.objects.get(pk=h.pk).status == "RECEIVED" for h in held))
        fresh = self.report("IMPRESSION", when=10)
        passes = 0
        while Reaction.objects.get(pk=fresh.pk).status == "RECEIVED" and passes < 6:
            records.process_pending(limit=2, now=at(10))
            passes += 1
        self.assertEqual(Reaction.objects.get(pk=fresh.pk).status, "ACCEPTED")
        self.assertLessEqual(passes, 4)  # 보류 6건 ÷ 한 번에 2건 = 3번 + 1

    def test_holding_is_not_a_failure(self):
        self.click(when=0)
        for _ in range(10):
            records.process_pending(now=at(100))
        self.assertEqual(Reaction.objects.get(type="CLICK").attempts, 0)
        self.assertEqual(records.stuck_count(), 0)

    def test_the_cost_of_judging_does_not_grow_with_the_number_of_other_reactions(self):
        self.accept_impression()
        first = self.click(when=1)
        with CaptureQueriesContext(connection) as small:
            self.judge(first, 1)
        w = World()
        d = self.decide(w.slot, SUBJECT)
        self.media = w.slot.media_id
        crowd = [self.report("IMPRESSION", d, when=0) for _ in range(25)]  # 같은 결정에 다른 반응이 많아도
        self.decision = d
        for row in crowd:  # 먼저 접수된 것부터 끝낸다(같은 유형은 먼저 접수된 쪽이 대표라 뒤쪽은 그것을 기다린다)
            self.judge(row, 0)
        self.assertEqual(self.judge(self.report("IMPRESSION", d, when=0), 0), "REJECTED")  # 중복 — 판정 경로가 작은 쪽(인정)과 다르지 않게 클릭은 인정된 노출 위에서 판정된다
        second = self.click(d, when=1)
        with CaptureQueriesContext(connection) as large:
            self.judge(second, 1)
        self.assertEqual(len(small), len(large))


@tag("security")
class MandatoryRulesRemainTests(FunnelBase):
    def test_with_no_configured_rules_only_the_mandatory_conditions_apply(self):
        """설정을 비워도 돈이 걸린 조건(결정·매체·광고, 클릭 출처, 사람, 종료)은 유지되고, 순서·기간 같은 정책만 빠진다."""
        with override_settings(REACTION_RULES=()):
            click_without_impression = self.click(when=1)  # 정책이 빠졌으니 노출 없이도 인정된다
            self.assertEqual(self.judge(click_without_impression, 1), "ACCEPTED")
            media_click = self.report("CLICK", when=2)
            self.assertEqual(self.judge(media_click, 2), "REJECTED")


@tag("security")
class ReactionSubjectApiTests(ProviderContractMixin, TestCase):
    contract = Contract("serving")

    def setUp(self):
        from serving_api.throttle import buckets

        buckets.reset()
        self.addCleanup(buckets.reset)
        self.w = World()
        self.key = masters.issue_media_key(self.w.admin, self.w.slot.media_id).key
        self.decision = records.decide(self.w.slot.media_id, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))

    def put(self, rid, body, key="USE"):
        return Client().put(
            f"/api/media/v1/decisions/{self.decision.decision_id}/reactions/{rid}", data=json.dumps(body), content_type="application/json",
            HTTP_X_MEDIA_KEY=self.key if key == "USE" else key,
        )

    def test_the_subject_is_stored_lowercase_and_echoed_and_matches_the_contract(self):
        rid = uuid.uuid4()
        body = {"type": "IMPRESSION", "occurred_at": "2026-10-07T12:00:00Z", "subject_id": A.upper()}
        response = self.put(rid, body)
        self.assertEqual(response.status_code, 201)
        self.assertContract(self.contract, "/decisions/{decision_id}/reactions/{reaction_id}", "put", response)
        self.assertEqual(response.json()["subject_id"], A)
        self.assertEqual(Reaction.objects.get(reaction_id=rid).subject_id, A)
        self.assertEqual(Reaction.objects.get(reaction_id=rid).raw["subject_id"], A.upper())  # 받은 원문은 그대로

    def test_a_resend_must_carry_the_same_person(self):
        rid, body = uuid.uuid4(), {"type": "IMPRESSION", "occurred_at": "2026-10-07T12:00:00Z", "subject_id": A}
        self.assertEqual(self.put(rid, body).status_code, 201)
        self.assertEqual(self.put(rid, {**body, "subject_id": A.upper()}).status_code, 200)  # 표기만 다른 같은 사람
        self.assertEqual(self.put(rid, {**body, "subject_id": B}).status_code, 409)
        without = {k: v for k, v in body.items() if k != "subject_id"}
        self.assertEqual(self.put(rid, without).status_code, 409)

    def test_a_malformed_person_is_400_and_absent_is_null(self):
        bad = self.put(uuid.uuid4(), {"type": "IMPRESSION", "occurred_at": "2026-10-07T12:00:00Z", "subject_id": "learner-1"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("/subject_id", [e["pointer"] for e in bad.json()["errors"]])
        self.assertContract(self.contract, "/decisions/{decision_id}/reactions/{reaction_id}", "put", bad)
        ok = self.put(uuid.uuid4(), {"type": "IMPRESSION", "occurred_at": "2026-10-07T12:00:00Z"})
        self.assertIsNone(ok.json()["subject_id"])
        self.assertContract(self.contract, "/decisions/{decision_id}/reactions/{reaction_id}", "put", ok)

    def test_the_result_shows_the_verdict_with_the_new_reason_codes(self):
        rid = uuid.uuid4()
        self.put(rid, {"type": "CLICK", "occurred_at": "2026-10-07T12:00:00Z"})
        records.process_pending(now=NOW)
        got = Client().get(f"/api/media/v1/decisions/{self.decision.decision_id}/reactions/{rid}", HTTP_X_MEDIA_KEY=self.key)
        self.assertEqual((got.status_code, got.json()["status"], got.json()["reason_code"]), (200, "REJECTED", "click_not_reported"))
        self.assertContract(self.contract, "/decisions/{decision_id}/reactions/{reaction_id}", "get", got)


@tag("security")
class EndToEndFunnelTests(TestCase):
    """실제 URL 로 결정 → 노출 → 클릭(`click_url`) → 전환까지. 수신 직후 처리가 켜진 기본 설정이다. 시각은 `NOW` 로 고정한다."""

    def setUp(self):
        from unittest import mock

        from serving_api.throttle import buckets

        buckets.reset()
        self.addCleanup(buckets.reset)
        for target in ("records.services._now", "records.processing._now"):
            patcher = mock.patch(target, lambda now=None: now or NOW)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.w = World()
        self.key = masters.issue_media_key(self.w.admin, self.w.slot.media_id).key

    def api(self, method, path, body=None):
        extra = {"HTTP_X_MEDIA_KEY": self.key}
        client = Client()
        if body is None:
            return getattr(client, method)(path, **extra)
        return getattr(client, method)(path, data=json.dumps(body), content_type="application/json", **extra)

    def decide(self, slot, **body):
        response = self.api("post", "/api/media/v1/decisions", {"slot_id": str(slot.slot_id), **body})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def report(self, decision, rtype, **extra):
        rid = uuid.uuid4()
        response = self.api("put", f"/api/media/v1/decisions/{decision['decision_id']}/reactions/{rid}", {"type": rtype, "occurred_at": "2026-10-07T12:00:00Z", **extra})
        self.assertEqual(response.status_code, 201, response.content)
        return rid

    def status(self, decision, rid):
        body = self.api("get", f"/api/media/v1/decisions/{decision['decision_id']}/reactions/{rid}").json()
        return body["status"], body["reason_code"]

    def follow(self, url):
        return Client().get(url.removeprefix("http://testserver"))

    def test_an_individual_visitor_goes_through_the_whole_funnel(self):
        decision = self.decide(self.w.slot, subject_id=SUBJECT)
        impression = self.report(decision, "IMPRESSION")
        self.assertEqual(self.status(decision, impression), ("ACCEPTED", None))
        self.assertEqual(self.follow(decision["ad"]["click_url"]).status_code, 302)
        conversion = self.report(decision, "CONVERSION")
        self.assertEqual(self.status(decision, conversion), ("ACCEPTED", None))
        accepted = Reaction.objects.filter(decision_id=decision["decision_id"], status="ACCEPTED")
        self.assertEqual(sorted(accepted.values_list("type", flat=True)), ["CLICK", "CONVERSION", "IMPRESSION"])
        self.assertEqual({r.person_id for r in accepted}, {SUBJECT})
        self.assertEqual(billing.get_wallet(self.w.adv, now=NOW).balance, 50_000 - 30)

    def test_a_click_that_beats_its_impression_waits_and_is_accepted_when_the_impression_lands(self):
        decision = self.decide(self.w.slot, subject_id=SUBJECT)
        self.follow(decision["ad"]["click_url"])
        click = Reaction.objects.get(decision_id=decision["decision_id"], source="server")
        self.assertEqual((click.status, click.attempts), ("RECEIVED", 0))  # 보류: 거부도 실패도 아니다
        self.assertEqual(self.status(decision, self.report(decision, "IMPRESSION")), ("ACCEPTED", None))
        self.assertEqual(records.process_pending(now=at(6))["accepted"], 1)  # 재확인 간격이 지나 다시 판정한다
        click.refresh_from_db()
        self.assertEqual(click.status, "ACCEPTED")

    def test_in_a_shared_slot_each_viewer_reports_their_own_funnel(self):
        slot = masters.create_slot(self.w.admin, self.w.slot.media_id, "전광판", "IMPRESSION", 10, 20, 50, "초기", audience="shared", **SHARES)
        group = self.w.api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "일괄", "IMPRESSION", [slot.slot_id], bid_amount=40, now=NOW)
        self.w.api.create_creative(self.w.adv, group.ad_group_id, "전광판", "https://example.com/board", png_file((4, 4, 4)), now=NOW)
        decision = self.decide(slot)
        self.assertTrue(decision["ad"]["click_url"].endswith("?s={subject_id}"))
        for person in (A, B):
            self.assertEqual(self.status(decision, self.report(decision, "IMPRESSION", subject_id=person)), ("ACCEPTED", None))
        self.assertEqual(self.status(decision, self.report(decision, "IMPRESSION")), ("REJECTED", "subject_required"))
        self.follow(decision["ad"]["click_url"].replace("{subject_id}", A))
        self.follow(decision["ad"]["click_url"].replace("{subject_id}", C))  # 노출이 없는 임의의 사람
        clicks = {r.subject_id: r.status for r in Reaction.objects.filter(decision_id=decision["decision_id"], source="server")}
        self.assertEqual(clicks, {A: "ACCEPTED", C: "RECEIVED"})
        self.assertEqual(self.status(decision, self.report(decision, "CONVERSION", subject_id=B)), ("RECEIVED", None))  # B 는 클릭하지 않았다: 보류
        self.assertEqual(self.status(decision, self.report(decision, "CONVERSION", subject_id=A)), ("ACCEPTED", None))
        self.assertEqual(Reaction.objects.get(decision_id=decision["decision_id"], type="IMPRESSION", subject_id=A).person_id, A)


class TimingBase(FunnelBase):
    def balance(self):
        return billing.get_wallet(self.w.adv, now=NOW).balance


@tag("security")
class LatePrerequisiteTests(TimingBase):
    """검토 2-9 후속 #1: 보류 기한이 지난 뒤에 도착한 노출이 클릭을 되살려 과금시키면 안 된다. 단, 제때 도착했는데 처리만 늦은 경우는 거부하면 안 된다."""

    UNIT = "CLICK"  # 클릭이 과금 단위라 인정되면 곧바로 원장에 나타난다

    def test_a_prerequisite_that_first_arrived_after_the_hold_window_does_not_rescue_a_held_click(self):
        click = self.click(when=1)
        self.assertEqual(self.judge(click, 1), "PENDING")
        late = self.report("IMPRESSION", when=302)  # 클릭 접수 + 301초: 기한(300초) 뒤에 처음 도착했다
        self.assertEqual(self.judge(late, 302), "ACCEPTED")  # 노출 자체는 정상이다
        self.assertEqual(self.judge(click, 303), "REJECTED")
        self.assertEqual(self.verdict(click), ("REJECTED", "missing_prerequisite", "funnel-order"))
        self.assertEqual(self.balance(), 50_000)  # 과금 없음

    def test_the_deadline_is_inclusive_to_the_microsecond(self):
        click = self.click(when=1)
        self.assertEqual(self.judge(click, 1), "PENDING")
        on_time = self.report("IMPRESSION", when=301)  # 정확히 접수 + 300초
        self.judge(on_time, 400)
        self.assertEqual(self.judge(click, 401), "ACCEPTED")
        self.assertEqual(self.balance(), 50_000 - 30)

        other = self.decide(self.w.slot, A)
        click2 = self.click(other, when=1)
        self.assertEqual(self.judge(click2, 1), "PENDING")
        too_late = self.report("IMPRESSION", other, when=301, occurred=at(301))
        Reaction.objects.filter(pk=too_late.pk).update(received_at=at(301) + timedelta(microseconds=1))
        self.judge(too_late, 400)
        self.assertEqual(self.judge(click2, 401), "REJECTED")
        self.assertEqual(self.balance(), 50_000 - 30)

    def test_a_prerequisite_that_arrived_in_time_but_was_processed_late_still_counts(self):
        """처리 작업자가 늦게 돈 것은 매체의 잘못이 아니다 — 제때 도착한 노출이 기한 뒤에 인정돼도 클릭은 인정된다."""
        click = self.click(when=1)
        self.assertEqual(self.judge(click, 1), "PENDING")
        impression = self.report("IMPRESSION", when=250)  # 제때 도착
        self.assertEqual(self.judge(impression, 310), "ACCEPTED")  # 작업자가 기한 뒤에 처리
        self.assertEqual(self.judge(click, 311), "ACCEPTED")
        self.assertEqual(self.balance(), 50_000 - 30)

    def test_a_prerequisite_that_arrived_in_time_but_is_still_unprocessed_keeps_the_click_waiting(self):
        click = self.click(when=1)
        impression = self.report("IMPRESSION", when=250)  # 제때 도착, 아직 처리 전
        self.assertEqual(self.judge(click, 400), "PENDING")  # 기한이 지났어도 거부하지 않는다
        self.assertEqual(click.status, "RECEIVED")
        self.assertEqual(self.judge(impression, 401), "ACCEPTED")
        self.assertEqual(self.judge(click, 402), "ACCEPTED")

    def test_an_unprocessed_prerequisite_that_arrived_too_late_does_not_keep_the_click_waiting_forever(self):
        click = self.click(when=1)
        self.report("IMPRESSION", when=305)  # 기한(301) 뒤에 도착했고 아직 처리 전
        self.assertEqual(self.judge(click, 400), "REJECTED")
        self.assertEqual(click.reason_code, "missing_prerequisite")

    def test_an_unprocessed_prerequisite_that_is_then_rejected_ends_the_wait_at_the_deadline(self):
        self.accept_impression()  # 이미 인정된 노출이 있어 새 노출은 중복으로 거부된다
        decision = self.decide(self.w.slot, A)
        click = self.click(decision, when=1)
        dup = self.report("IMPRESSION", decision, when=250, subject=None)
        Reaction.objects.filter(pk=dup.pk).update(occurred_at=at(-3600))  # 시각이 틀린 노출: 거부될 것
        self.assertEqual(self.judge(dup, 251), "REJECTED")
        self.assertEqual(self.judge(click, 301), "REJECTED")
        self.assertEqual(click.reason_code, "missing_prerequisite")


@tag("security")
class ConversionBeforeClickTests(TimingBase):
    """검토 2-9 후속 #2: 실제 클릭보다 먼저 접수된 전환을 나중에 생긴 클릭으로 소급 인정하면 안 된다."""

    UNIT = "CONVERSION"

    def test_a_conversion_received_before_the_click_is_never_accepted(self):
        self.accept_impression(when=0)
        conversion = self.report("CONVERSION", when=1)
        self.assertEqual(self.judge(conversion, 1), "PENDING")
        click = self.click(when=200)
        self.assertEqual(self.judge(click, 200), "ACCEPTED")
        self.assertEqual(self.judge(conversion, 201), "PENDING")  # 클릭이 있어도 전환이 먼저였다
        self.assertEqual(self.judge(conversion, 301), "REJECTED")
        self.assertEqual(self.verdict(conversion), ("REJECTED", "missing_prerequisite", "funnel-order"))
        self.assertEqual(self.balance(), 50_000)  # 전환 과금 없음

    def test_a_conversion_received_at_the_same_instant_or_later_is_accepted(self):
        self.accept_impression(when=0)
        self.judge(self.click(when=5), 5)
        same = self.report("CONVERSION", when=5)
        self.assertEqual(self.judge(same, 6), "ACCEPTED")
        self.assertEqual(self.balance(), 50_000 - 30)

        other = self.decide(self.w.slot, A)
        self.accept_impression(other, subject=None, when=0)
        self.judge(self.click(other, when=5), 5)
        later = self.report("CONVERSION", other, when=6)
        self.assertEqual(self.judge(later, 7), "ACCEPTED")

    def test_a_click_that_is_still_unprocessed_does_not_admit_an_earlier_conversion_either(self):
        self.accept_impression(when=0)
        conversion = self.report("CONVERSION", when=1)
        click = self.click(when=50)  # 처리 전
        self.assertEqual(self.judge(conversion, 60), "PENDING")
        self.assertEqual(self.judge(click, 61), "ACCEPTED")
        self.assertEqual(self.judge(conversion, 62), "PENDING")
        self.assertEqual(self.judge(conversion, 1 + 300), "REJECTED")


@tag("security")
class ProcessingOrderTests(TimingBase):
    """검토 2-13 후속 P2-1 — **같은 접수 사실이면 처리 순서와 무관하게 같은 판정**(설계 §10 "판정 설계 기준" ②).

    같은 (결정, 사람)의 노출이 둘 접수됐을 때 어느 쪽이 '인정된 노출'(클릭의 전제)이 되는지가 처리 순서가 아니라 **접수 순서**로 정해져야 한다.
    """

    UNIT = "CLICK"

    def scenario(self, order):
        """클릭 t+1, 이른 노출 t+250, 늦은 노출 t+302 를 접수하고, 두 노출을 `order` 순서로 t+303 에, 클릭을 t+304 에 판정한다."""
        self.w = World(unit=self.UNIT)
        self.media = self.w.slot.media_id
        self.decision = self.decide(self.w.slot, SUBJECT)
        click = self.click(when=1)
        early, late = self.report("IMPRESSION", when=250), self.report("IMPRESSION", when=302)
        for name in order:
            self.judge({"early": early, "late": late}[name], 303)
        for row in (early, late):  # 기다리던 쪽은 다음 주기에 다시 판정된다
            if row.status == "RECEIVED":
                self.judge(row, 304)
        self.judge(click, 304)
        return {"click": self.verdict(click), "early": self.verdict(early), "late": self.verdict(late), "balance": self.balance()}

    def test_which_duplicate_impression_is_processed_first_does_not_change_the_clicks_verdict_or_the_charge(self):
        results = {order: self.scenario(order) for order in (("early", "late"), ("late", "early"))}
        self.assertEqual(results[("early", "late")], results[("late", "early")])
        outcome = results[("early", "late")]
        self.assertEqual(outcome["click"], ("ACCEPTED", None, None))  # 제때 도착한 이른 노출이 전제다
        self.assertEqual(outcome["early"], ("ACCEPTED", None, None))
        self.assertEqual(outcome["late"], ("REJECTED", "duplicate_type", "once-per-type"))
        self.assertEqual(outcome["balance"], 50_000 - 30)

    def test_a_later_duplicate_waits_for_the_earlier_one_instead_of_taking_its_place(self):
        early, late = self.report("IMPRESSION", when=250), self.report("IMPRESSION", when=302)
        self.assertEqual(self.judge(late, 303), "PENDING")  # 먼저 접수된 같은 유형이 아직 처리 전이다
        self.assertEqual((late.status, late.basis, late.attempts), ("RECEIVED", None, 0))  # 보류는 판정도 실패도 아니다
        self.assertEqual(self.judge(early, 303), "ACCEPTED")
        self.assertEqual(self.judge(late, 304), "REJECTED")
        self.assertEqual(late.reason_code, "duplicate_type")

    def test_an_earlier_report_that_is_itself_invalid_does_not_take_the_place_of_a_valid_later_one(self):
        """먼저 접수됐지만 거부된 노출(감지 시각이 터무니없음)은 대표가 아니다 — 다음 유효한 노출이 인정되고 클릭의 전제가 된다. 처리 순서와 무관하다."""
        for order in (("bad", "good"), ("good", "bad")):
            with self.subTest(order=order):
                self.w = World(unit=self.UNIT)
                self.media = self.w.slot.media_id
                self.decision = self.decide(self.w.slot, SUBJECT)
                click = self.click(when=1)
                rows = {"bad": self.report("IMPRESSION", when=10, occurred=at(10) + 3600 * SEC), "good": self.report("IMPRESSION", when=20)}
                for name in order:
                    self.judge(rows[name], 21)
                self.judge(rows["good"], 22)
                self.judge(click, 23)
                self.assertEqual(self.verdict(rows["bad"])[:2], ("REJECTED", "invalid_occurred_at"))
                self.assertEqual(self.verdict(rows["good"]), ("ACCEPTED", None, None))
                self.assertEqual(click.status, "ACCEPTED")

    def test_an_earlier_report_that_cannot_be_processed_keeps_the_later_ones_waiting_and_is_visible(self):
        """처리가 반복 실패해 자동 재처리에서 빠진 이른 반응(`stuck`)은 뒤의 같은 유형을 기다리게 한다 — `stuck_count` 로 드러난다(알려진 한계)."""
        from records.models import Reaction as Row
        from records.processing import stuck_count

        early, late = self.report("IMPRESSION", when=10), self.report("IMPRESSION", when=20)
        Row.objects.filter(pk=early.pk).update(attempts=5)
        self.assertEqual(self.judge(late, 30), "PENDING")
        self.assertEqual(stuck_count(), 1)

    def test_other_people_and_other_types_do_not_wait_for_each_other(self):
        """같은 유형이어도 다른 사람(일괄 슬롯)이나 다른 매체의 먼저 접수된 반응은 기다림의 대상이 아니다."""
        slot, decision = self.shared()
        a = self.report("IMPRESSION", decision, when=1, subject=A)
        b = self.report("IMPRESSION", decision, when=2, subject=B)
        self.assertEqual(self.judge(b, 3), "ACCEPTED")  # A 의 먼저 접수된 노출이 처리 전이어도 B 는 기다리지 않는다
        self.assertEqual(a.status, "RECEIVED")
        foreign = World()
        records.receive_reaction(foreign.slot.media_id, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", at(0), {}, now=at(0))  # 다른 매체의 먼저 접수된 노출
        mine = self.report("IMPRESSION", when=5)
        self.assertEqual(self.judge(mine, 6), "ACCEPTED")


class ScopeBase(FunnelBase):
    """2-13 판정 사실의 매체 격리(설계 §10 "판정 사실의 범위"): 판정에 쓰는 반응은 **결정 소유 매체가 보낸 것**(개인 슬롯은 + 보고된 사람이 없거나 결정의 사람)뿐이다.

    접수는 존재를 알리지 않으려고 남의 결정에 대한 보고도 저장한다. 그래서 범위가 없으면 다른 매체의 노출이 (가) 기존 광고의 클릭 창을 닫고 (나) 처리 전인 동안 클릭을 보류시킨다.
    소스 검사(반응을 읽는 입구가 하나인지)는 `tests/boundaries/test_judgment_scope.py`.
    """

    def foreign_impression(self, decision, when):
        """다른 매체가 **우리 결정**에 대해 노출을 보고했다(접수는 존재를 알리지 않으므로 저장된다)."""
        self.other = getattr(self, "other", None) or World()
        view, created = records.receive_reaction(self.other.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", at(when), {}, now=at(when))
        self.assertTrue(created)
        return Reaction.objects.get(pk=view.inbox_id)

    def probe(self, decision, seconds):
        Reaction.objects.filter(decision_id=decision.decision_id, type="CLICK").delete()
        row = self.click(decision, when=seconds)
        self.judge(row, seconds)
        return row.reason_code or row.status


@tag("security")
class DisplaySignalScopeTests(ScopeBase):
    def test_another_medias_impression_is_not_a_display_replacement_signal(self):
        self.accept_impression()
        second = self.decide(self.w.slot, SUBJECT, when=at(10))  # 같은 슬롯·사람의 다음 결정
        self.foreign_impression(second, when=20)  # 다른 매체가 그 결정에 노출을 보고
        self.assertEqual(self.probe(self.decision, 100), "ACCEPTED")  # 기존 광고의 클릭 창이 닫히지 않는다

    def test_an_impression_reported_for_another_person_in_an_individual_slot_is_not_a_signal(self):
        self.accept_impression()
        second = self.decide(self.w.slot, SUBJECT, when=at(10))
        self.report("IMPRESSION", second, when=20, subject=A)  # 같은 매체지만 다른 사람이라고 보고
        self.assertEqual(self.probe(self.decision, 100), "ACCEPTED")
        self.report("IMPRESSION", second, when=30, subject=SUBJECT)  # 이 사람이라고 보고하면 신호다
        self.assertEqual(self.probe(self.decision, 100), "display_ended")

    def test_in_a_normal_shared_slot_any_viewers_impression_of_the_same_media_is_a_signal(self):
        slot, decision = self.shared()
        self.accept_impression(decision, subject=A)
        later = self.decide(slot, None, when=at(10))
        self.foreign_impression(later, when=11)  # 다른 매체의 노출은 신호가 아니다
        self.assertEqual(self.probe_viewer(decision, A, 15), "ACCEPTED")
        self.report("IMPRESSION", later, when=16, subject=B)  # 같은 매체의 다른 시청자(B)의 노출은 신호다
        self.assertEqual(self.probe_viewer(decision, A, 22), "display_ended")

    def probe_viewer(self, decision, viewer, seconds):
        Reaction.objects.filter(decision_id=decision.decision_id, type="CLICK", subject_id=viewer).delete()
        row = self.click(decision, when=seconds, viewer=viewer)
        self.judge(row, seconds)
        return row.reason_code or row.status


@tag("security")
class PrerequisiteScopeTests(ScopeBase):
    def test_another_medias_unprocessed_impression_does_not_hold_a_click(self):
        """처리 전인 남의 노출이 '앞 단계가 곧 올 것'으로 보여 클릭을 보류시키면 판정 시점이 남의 처리 순서에 따라 달라진다."""
        click = self.click(when=0)  # 우리 노출은 없다
        self.foreign_impression(self.decision, when=1)  # 다른 매체의 노출: 처리 전(RECEIVED)
        hold = 300
        self.assertEqual(self.judge(click, hold), "REJECTED")  # 기한에 맞춰 missing_prerequisite
        self.assertEqual(self.verdict(click), ("REJECTED", "missing_prerequisite", "funnel-order"))

    def test_an_impression_reported_for_another_person_is_not_a_prerequisite_of_this_persons_click(self):
        click = self.click(when=0)
        self.report("IMPRESSION", when=1, subject=A)  # 이 결정(SUBJECT)에 다른 사람이라고 보고된 노출 — 처리 전
        self.assertEqual(self.judge(click, 300), "REJECTED")
        self.assertEqual(click.reason_code, "missing_prerequisite")

    def test_the_accepted_types_lookup_is_scoped_too(self):
        """인정된 유형 조회도 범위를 거친다: 다른 매체가 같은 결정에 남긴 행(인정으로 위조된 행 포함)은 '이미 인정'으로 세지 않는다."""
        from records import facts

        forged = self.foreign_impression(self.decision, when=1)
        Reaction.objects.filter(pk=forged.pk).update(
            status="ACCEPTED", processed_at=at(1), person_id=SUBJECT, accepted_key=f"forged:{uuid.uuid4()}", basis={"v": 1},
        )
        row = self.report("IMPRESSION", when=2)
        self.assertEqual(facts.gather(row, self.decision_row(), at(2)).accepted_types, frozenset())

    def decision_row(self):
        from records.models import Decision

        return Decision.objects.get(pk=self.decision.decision_id)
