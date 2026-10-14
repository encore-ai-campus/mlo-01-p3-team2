"""2-10 퍼널 집계 `records.api.daily_report`: 인정된 반응을 결정과 묶어 일별로 센다(읽기 전용, 별도 테이블 없음).

시각은 모두 고정한다. 결정은 `NOW`(2026-10-07 12:00 UTC)를 기준으로 며칠 앞뒤에 만들고, 반응은 결정 1초 뒤에 수신해 바로 처리한다.
예산 일은 기본 UTC 자정이라 `NOW` 의 날은 2026-10-07 이다.
"""
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from random import Random

from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings, tag
from django.test.utils import CaptureQueriesContext

from billing import api as billing
from django.http import Http404

from foundation.errors import Forbidden, InvalidRequest
from masters import api as masters
from records import api as records
from records.models import Reaction
from tests.support.factories import DAY, NOW, SHARES, SUBJECT, World, make_admin, make_advertiser, png_file

D7 = datetime(2026, 10, 7, tzinfo=timezone.utc)  # NOW 가 속한 예산 일의 시작
SEC = timedelta(seconds=1)
HOUR = timedelta(hours=1)
A, B, C = ("0197a5c0-0000-7000-8000-0000000000%02x" % n for n in (0xa1, 0xb2, 0xc3))


def window(days=3, start=D7):
    return start, start + timedelta(days=days)


class ReportMixin:
    def setUp(self):
        self.w = World()
        self.media = self.w.slot.media_id

    def impression(self, when, world=None, subject=SUBJECT, slot=None):
        """`when` 에 결정, 1초 뒤 노출이 수신되어 바로 인정·과금된다. 결정을 돌려준다."""
        world = world or self.w
        slot = slot or world.slot
        decision = records.decide(slot.media_id, slot.slot_id, subject_id=subject if slot.audience == "individual" else None, now=when, rng=Random(1))
        self.assertIsNotNone(decision.chosen)
        self.report(decision, "IMPRESSION", when + SEC, subject=subject if slot.audience == "shared" else None)
        return decision

    def report(self, decision, rtype, received, subject=None):
        if rtype == "CLICK":
            records.observe_click(decision.decision_id, subject, now=received)
            row = Reaction.objects.filter(decision_id=decision.decision_id, source="server", subject_id=subject or decision.subject_id).get()
        else:
            view, _ = records.receive_reaction(decision.media_id, decision.decision_id, uuid.uuid4(), rtype, received, {}, subject_id=subject, now=received)
            row = Reaction.objects.get(pk=view.inbox_id)
        outcome = records.process_reaction(row.inbox_id, now=received)
        self.assertEqual(outcome, "ACCEPTED", f"{rtype}: {Reaction.objects.get(pk=row.pk).reason_code}")

    def full_funnel(self, when, subject=SUBJECT):
        decision = self.impression(when, subject=subject)
        self.report(decision, "CLICK", when + 2 * SEC)
        self.report(decision, "CONVERSION", when + 3 * SEC)
        return decision

    def report_for(self, start_end=None, user=None, **scope):
        start, end = start_end or window()
        return records.daily_report(user or self.w.adv, start, end, **scope)

    def by_date(self, report):
        return {row.date: (row.totals.impressions, row.totals.clicks, row.totals.conversions, row.totals.spent) for row in report.rows}


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
class ReportBase(ReportMixin, TestCase):
    pass


@tag("security")
class DailyReportCountsTests(ReportBase):
    def setUp(self):
        super().setUp()
        self.full_funnel(NOW)  # 10/7: 노출 1·클릭 1·전환 1
        self.impression(NOW + 2 * HOUR, subject=A)  # 10/7: 노출 +1
        self.impression(NOW + DAY)  # 10/8: 노출 1
        self.impression(NOW - DAY + HOUR)  # 10/6(직전 구간): 노출 1

    def test_counts_spent_and_every_day_of_the_window(self):
        report = self.report_for()
        self.assertEqual(self.by_date(report), {date(2026, 10, 7): (2, 1, 1, 594), date(2026, 10, 8): (1, 0, 0, 294), date(2026, 10, 9): (0, 0, 0, 0)})
        self.assertEqual((report.start, report.end), window())
        t = report.totals
        self.assertEqual((t.impressions, t.clicks, t.conversions, t.spent), (3, 1, 1, 888))  # 입찰 300 · 비율 98/1/1: 노출 294 · 클릭 3 · 전환 3

    def test_the_previous_period_of_the_same_length_is_totalled_for_comparison(self):
        previous = self.report_for().previous_totals
        self.assertEqual((previous.impressions, previous.clicks, previous.conversions, previous.spent), (1, 0, 0, 294))
        longer = self.report_for(window(5)).previous_totals  # 10/2~10/6
        self.assertEqual(longer.impressions, 1)
        shifted = self.report_for(window(1, D7 + DAY))  # 10/8 하루 → 직전은 10/7 하루
        self.assertEqual((shifted.totals.impressions, shifted.previous_totals.impressions), (1, 2))

    def test_ratios_are_computed_and_undefined_without_a_denominator(self):
        report = self.report_for()
        self.assertAlmostEqual(report.totals.ctr, 1 / 3)
        self.assertEqual(report.totals.conversion_rate, 1.0)
        empty = self.report_for(window(3, D7 + 5 * DAY)).totals
        self.assertEqual((empty.ctr, empty.conversion_rate), (None, None))  # 0 으로 나누지 않는다
        clickless = self.report_for(window(1, D7 + DAY)).totals
        self.assertEqual((clickless.ctr, clickless.conversion_rate), (0.0, None))

    def test_only_accepted_reactions_are_counted(self):
        decision = self.impression(NOW + 4 * HOUR, subject=C)
        records.receive_reaction(decision.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW + 4 * HOUR, {}, now=NOW + 4 * HOUR + 5 * SEC)  # 중복 → 거부될 것
        records.receive_reaction(decision.media_id, decision.decision_id, uuid.uuid4(), "CONVERSION", NOW + 4 * HOUR, {}, now=NOW + 4 * HOUR + 6 * SEC)  # 클릭 없는 전환 → 보류
        records.process_pending(now=NOW + 4 * HOUR + 10 * SEC)
        statuses = sorted(Reaction.objects.filter(decision_id=decision.decision_id).values_list("status", flat=True))
        self.assertEqual(statuses, ["ACCEPTED", "RECEIVED", "REJECTED"])
        self.assertEqual(self.report_for().totals.impressions, 4)  # 노출 3 + 이 결정의 인정된 노출 1
        self.assertEqual(self.report_for().totals.conversions, 1)  # 보류 중인 전환은 세지 않는다

    def test_the_window_includes_from_and_excludes_to(self):
        edge = self.w
        before = records.decide(edge.slot.media_id, edge.slot.slot_id, subject_id=A, now=D7 - SEC, rng=Random(1))
        self.report(before, "IMPRESSION", D7)  # 정확히 from → 포함(10/7)
        late = records.decide(edge.slot.media_id, edge.slot.slot_id, subject_id=B, now=D7 + 3 * DAY - SEC, rng=Random(1))
        self.report(late, "IMPRESSION", D7 + 3 * DAY)  # 정확히 to → 제외
        report = self.report_for()
        self.assertEqual(report.totals.impressions, 4)  # 기존 3 + from 의 1
        self.assertEqual(self.by_date(report)[date(2026, 10, 7)][0], 3)
        self.assertEqual(self.report_for(window(1, D7 + 3 * DAY)).totals.impressions, 1)  # 다음 구간의 첫날에 속한다

    @override_settings(BUDGET_DAY_OFFSET_HOURS=9)
    def test_days_follow_the_budget_day_boundary_setting(self):
        """예산 일 경계가 KST 자정(= UTC 15:00)이면 날짜도 그 경계로 잘린다."""
        w = World()
        start = datetime(2026, 10, 6, 15, tzinfo=timezone.utc)  # 10/7 KST 자정
        a = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=A, now=datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc), rng=Random(1))
        self.report(a, "IMPRESSION", datetime(2026, 10, 7, 14, 59, 59, tzinfo=timezone.utc))  # KST 10/7 23:59:59
        b = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=B, now=datetime(2026, 10, 7, 14, 30, tzinfo=timezone.utc), rng=Random(1))
        self.report(b, "IMPRESSION", datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc))  # KST 10/8 00:00
        report = records.daily_report(w.adv, start, start + 2 * DAY)
        self.assertEqual(self.by_date(report), {date(2026, 10, 7): (1, 0, 0, 294), date(2026, 10, 8): (1, 0, 0, 294)})
        with self.assertRaises(InvalidRequest):  # UTC 자정은 이 설정에서 일 경계가 아니다
            records.daily_report(w.adv, D7, D7 + DAY)


@tag("security")
class ConversionRateCohortTests(ReportBase):
    """검토 2-12 ②: 전환율 = 그 구간에 받은 **클릭 중** 전환으로 이어진 비율. 전환 수는 수신일, 클릭도 수신일이라 나누면 이전 구간 클릭의 전환이 섞여 1 을 넘을 수 있었다."""

    def clicked(self, when, subject=SUBJECT):
        decision = self.impression(when, subject=subject)
        self.report(decision, "CLICK", when + 2 * SEC)
        return decision

    def test_conversions_of_the_previous_periods_clicks_do_not_inflate_the_rate(self):
        yesterday = NOW - DAY
        prior = [self.clicked(yesterday + n * HOUR, subject=s) for n, s in enumerate((A, B))]  # 10/6 에 받은 클릭 2개
        for decision in prior:
            self.report(decision, "CONVERSION", NOW + HOUR)  # 전환은 10/7 에 받는다
        self.clicked(NOW + 2 * HOUR, subject=C)  # 10/7 클릭 1개, 전환 없음
        today = self.report_for(window(1)).totals
        self.assertEqual((today.clicks, today.conversions, today.converted_clicks), (1, 2, 0))
        self.assertEqual(today.conversion_rate, 0.0)  # 전환 / 클릭 = 2.0 이 아니다
        before = self.report_for(window(1)).previous_totals
        self.assertEqual((before.clicks, before.conversions, before.converted_clicks, before.conversion_rate), (2, 0, 2, 1.0))  # 전환은 클릭이 속한 구간의 몫

    def test_a_conversion_that_comes_after_the_period_still_counts_for_its_click(self):
        decision = self.clicked(NOW)
        self.report(decision, "CONVERSION", NOW + 2 * DAY)  # 10/9
        day7 = self.report_for(window(1)).totals
        self.assertEqual((day7.clicks, day7.conversions, day7.converted_clicks, day7.conversion_rate), (1, 0, 1, 1.0))
        day9 = self.report_for(window(1, D7 + 2 * DAY)).totals
        self.assertEqual((day9.clicks, day9.conversions, day9.conversion_rate), (0, 1, None))  # 클릭이 없는 구간은 정의되지 않는다

    def test_a_click_without_a_conversion_is_in_the_denominator_only(self):
        self.clicked(NOW, subject=A)
        self.report(self.clicked(NOW + HOUR, subject=B), "CONVERSION", NOW + 2 * HOUR)
        totals = self.report_for(window(1)).totals
        self.assertEqual((totals.clicks, totals.converted_clicks, totals.conversion_rate), (2, 1, 0.5))

    def test_a_rejected_or_pending_conversion_does_not_make_its_click_converted(self):
        rejected, pending = self.clicked(NOW, subject=A), self.clicked(NOW + HOUR, subject=B)
        view, _ = records.receive_reaction(rejected.media_id, rejected.decision_id, uuid.uuid4(), "CONVERSION", NOW + DAY, {}, now=NOW + 3 * SEC)  # 보고 시각이 미래 → 거부
        self.assertEqual(records.process_reaction(view.inbox_id, now=NOW + 3 * SEC), "REJECTED")
        records.receive_reaction(pending.media_id, pending.decision_id, uuid.uuid4(), "CONVERSION", NOW + HOUR + 3 * SEC, {}, now=NOW + HOUR + 3 * SEC)  # 아직 판정 전
        totals = self.report_for(window(1)).totals
        self.assertEqual((totals.clicks, totals.conversions, totals.converted_clicks, totals.conversion_rate), (2, 0, 0, 0.0))

    def test_in_a_shared_slot_a_conversion_belongs_to_its_own_viewers_click(self):
        slot, group = self.w.shared_ad()
        decision = records.decide(self.media, slot.slot_id, subject_id=None, now=NOW, rng=Random(1))
        for person in (A, B):
            self.report(decision, "IMPRESSION", NOW + SEC, subject=person)
            self.report(decision, "CLICK", NOW + 2 * SEC, subject=person)
        self.report(decision, "CONVERSION", NOW + 3 * SEC, subject=A)  # 같은 결정, A 만 전환
        totals = self.report_for(window(1), ad_group_id=group.ad_group_id).totals
        self.assertEqual((totals.clicks, totals.conversions, totals.converted_clicks, totals.conversion_rate), (2, 1, 1, 0.5))

    def test_the_rate_never_exceeds_one_and_rows_add_up_to_the_totals(self):
        for n, subject in enumerate((A, B, C)):
            decision = self.clicked(NOW - DAY + n * HOUR, subject=subject)
            if n != 1:
                self.report(decision, "CONVERSION", NOW + (n + 1) * HOUR)  # 이전 날 클릭의 전환이 오늘 들어온다
        report = self.report_for(window(2, D7 - DAY))
        for row in report.rows:
            self.assertLessEqual(row.totals.converted_clicks, row.totals.clicks)
            if row.totals.conversion_rate is not None:
                self.assertLessEqual(row.totals.conversion_rate, 1.0)
        self.assertEqual(sum(r.totals.converted_clicks for r in report.rows), report.totals.converted_clicks)
        self.assertEqual((report.totals.clicks, report.totals.converted_clicks), (3, 2))
        self.assertEqual(report.rows[0].totals.conversion_rate, 2 / 3)  # 10/6 클릭 3개 중 2개가 전환으로 이어졌다
        self.assertEqual(report.rows[1].totals.conversion_rate, None)  # 10/7 은 클릭이 없다(전환만 받았다)

    def test_another_advertisers_clicks_and_conversions_never_enter_the_rate(self):
        other = World()
        decision = records.decide(other.slot.media_id, other.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        self.report(decision, "IMPRESSION", NOW + SEC)
        self.report(decision, "CLICK", NOW + 2 * SEC)
        self.report(decision, "CONVERSION", NOW + 3 * SEC)
        mine = self.report_for(window(1)).totals
        self.assertEqual((mine.clicks, mine.converted_clicks, mine.conversion_rate), (0, 0, None))


@tag("security")
class DailyReportScopeTests(ReportBase):
    def test_other_advertisers_data_never_shows_up(self):
        other = World()
        self.full_funnel(NOW)
        self.impression(NOW + HOUR, world=other)
        self.impression(NOW + 2 * HOUR, world=other, subject=A)
        mine, theirs = self.report_for().totals, records.daily_report(other.adv, *window()).totals
        self.assertEqual((mine.impressions, mine.clicks, mine.spent), (1, 1, 300))  # 노출 294 + 클릭 3 + 전환 3
        self.assertEqual((theirs.impressions, theirs.clicks, theirs.spent), (2, 0, 588))

    def test_campaign_scope_and_ownership(self):
        second = self.w.api.create_campaign(self.w.adv, "두 번째", NOW - DAY, NOW + 10 * DAY, 5000, now=NOW)
        slot2 = self.new_slot("둘째 슬롯")
        group2 = self.w.api.create_ad_group(self.w.adv, second.campaign_id, "그룹2", [slot2.slot_id], bid_amount=400, now=NOW)
        self.w.api.create_creative(self.w.adv, group2.ad_group_id, "광고2", "https://example.com/two", png_file((9, 9, 9)), now=NOW)
        self.impression(NOW)  # 첫 캠페인(입찰 300 → 노출 294)
        self.impression(NOW + HOUR, slot=slot2, subject=A)  # 두 번째 캠페인(입찰 400 → 노출 392)
        first_id = self.w.campaign.campaign_id
        self.assertEqual(self.report_for().totals.spent, 686)
        self.assertEqual(self.report_for(campaign_id=first_id).totals.spent, 294)
        self.assertEqual(self.report_for(campaign_id=second.campaign_id).totals.spent, 392)
        for hidden in (World().campaign.campaign_id, uuid.uuid4()):  # 남의 캠페인은 없는 것과 같다
            with self.assertRaises(Http404):
                self.report_for(campaign_id=hidden)

    def new_slot(self, name):
        return masters.create_slot(self.w.admin, self.media, name, 100, 200, 500, "초기", audience="individual", **SHARES)

    def test_ad_group_scope_reads_the_ledger_and_reconciles_with_the_campaign(self):
        slot2 = self.new_slot("둘째 슬롯")
        group2 = self.w.api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "그룹2", [slot2.slot_id], bid_amount=400, now=NOW)
        self.w.api.create_creative(self.w.adv, group2.ad_group_id, "광고2", "https://example.com/two", png_file((9, 9, 9)), now=NOW)
        self.full_funnel(NOW)  # 광고의 소진액은 모든 유형의 과금이다(6-10c): 노출 294 + 클릭 3 + 전환 3
        self.impression(NOW + DAY, subject=A)
        self.impression(NOW + HOUR, slot=slot2, subject=B)
        g1, g2 = self.report_for(ad_group_id=self.w.group.ad_group_id), self.report_for(ad_group_id=group2.ad_group_id)
        self.assertEqual((g1.totals.impressions, g1.totals.spent, g2.totals.impressions, g2.totals.spent), (2, 594, 1, 392))
        self.assertEqual(self.by_date(g1)[date(2026, 10, 8)], (1, 0, 0, 294))
        whole = self.report_for(campaign_id=self.w.campaign.campaign_id)
        self.assertEqual((whole.totals.impressions, whole.totals.spent), (3, 986))  # 광고그룹 합 = 캠페인 (원장 ↔ 일 소진액)
        for day in whole.rows:
            self.assertEqual(day.totals.spent, self.by_date(g1)[day.date][3] + self.by_date(g2)[day.date][3])

    def test_a_group_must_belong_to_the_campaign_and_to_the_caller(self):
        other = World()
        for scope in (dict(ad_group_id=other.group.ad_group_id), dict(ad_group_id=uuid.uuid4()),
                      dict(campaign_id=self.w.campaign.campaign_id, ad_group_id=other.group.ad_group_id)):
            with self.assertRaises(Http404):
                self.report_for(**scope)
        second = self.w.api.create_campaign(self.w.adv, "두 번째", NOW - DAY, NOW + 10 * DAY, 5000, now=NOW)
        with self.assertRaises(Http404):  # 내 광고그룹이어도 다른 캠페인의 것이면 맞지 않는 쌍이다
            self.report_for(campaign_id=second.campaign_id, ad_group_id=self.w.group.ad_group_id)

    def test_spent_is_what_was_actually_received_when_the_balance_ran_short(self):
        decision = records.decide(self.media, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(self.media, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW + SEC)
        billing.adjust(self.w.admin, self.w.adv.pk, -(50_000 - 10), "잔액 부족 시험", now=NOW)
        self.assertEqual(records.process_reaction(view.inbox_id, now=NOW + SEC), "ACCEPTED")
        self.assertEqual(self.report_for().totals.spent, 10)  # 과금액 294 가 아니라 받은 10
        self.assertEqual(self.report_for(ad_group_id=self.w.group.ad_group_id).totals.spent, 10)

    def test_shared_slot_counts_every_viewer(self):
        slot, group = self.w.shared_ad()
        decision = records.decide(self.media, slot.slot_id, subject_id=None, now=NOW, rng=Random(1))
        for person in (A, B, C):
            self.report(decision, "IMPRESSION", NOW + SEC, subject=person)
        totals = self.report_for(ad_group_id=group.ad_group_id).totals
        self.assertEqual((totals.impressions, totals.spent), (3, 1176))  # 결정은 하나, 과금은 사람마다 한 번(400 × 98% = 392)


@tag("security")
class DailyReportInputTests(ReportBase):
    def test_only_an_active_advertiser_may_ask(self):
        from django.contrib.auth.models import AnonymousUser

        for user in (make_admin(), AnonymousUser()):
            for scope in ({}, {"campaign_id": self.w.campaign.campaign_id}, {"ad_group_id": self.w.group.ad_group_id}):  # 범위를 좁혀도 역할이 먼저다
                with self.assertRaises(Forbidden):
                    records.daily_report(user, *window(), **scope)
        inactive = make_advertiser()
        inactive.is_active = False
        with self.assertRaises(Forbidden):
            records.daily_report(inactive, *window())

    def test_the_window_must_be_aligned_ordered_utc_and_at_most_92_days(self):
        ok = records.daily_report(self.w.adv, D7, D7 + timedelta(days=92))
        self.assertEqual(len(ok.rows), 92)
        bad = {
            "not aligned from": (D7 + 3600 * SEC, D7 + 2 * DAY), "not aligned to": (D7, D7 + DAY + 3600 * SEC),
            "empty": (D7, D7), "backwards": (D7 + DAY, D7), "too long": (D7, D7 + timedelta(days=93)),
            "naive": (datetime(2026, 10, 7), datetime(2026, 10, 9)),
        }
        for label, (start, end) in bad.items():
            with self.subTest(label), self.assertRaises(InvalidRequest) as caught:
                records.daily_report(self.w.adv, start, end)
            self.assertTrue(caught.exception.errors[0]["pointer"] in ("/from", "/to"))


@tag("security")
class DailyReportCostTests(ReportBase):
    def count_queries(self, **scope):
        with CaptureQueriesContext(connection) as queries:
            self.report_for(**scope)
        return len(queries)

    def test_the_number_of_queries_does_not_grow_with_the_data(self):
        self.impression(NOW)
        few = {"owner": self.count_queries(), "campaign": self.count_queries(campaign_id=self.w.campaign.campaign_id)}
        for hours in range(1, 30):  # 반응도 결정도 훨씬 많아진다
            self.full_funnel(NOW + hours * 30 * 60 * SEC, subject=str(uuid.uuid4()))
        many = {"owner": self.count_queries(), "campaign": self.count_queries(campaign_id=self.w.campaign.campaign_id)}
        self.assertEqual(few, many)
        self.assertLessEqual(max(many.values()), 8)

    def test_the_ad_group_scope_costs_one_ledger_query_per_500_reactions_not_one_per_reaction(self):
        for index in range(12):
            self.impression(NOW + index * 60 * SEC, subject=str(uuid.uuid4()))
        with CaptureQueriesContext(connection) as queries:
            report = self.report_for(ad_group_id=self.w.group.ad_group_id)
        self.assertEqual(report.totals.impressions, 12)
        self.assertLessEqual(len(queries), 9)  # 소유 확인 몇 번 + 반응 1 + 원장 1(500건 이하)


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class ReportSnapshotTests(ReportMixin, TransactionTestCase):
    """검토 2-13 후속 P2-2: 보고서를 읽는 도중 다른 연결이 새 퍼널을 인정해도 **분자(전환으로 이어진 클릭)와 분모(클릭)가 같은 데이터 상태**를 본다.

    `READ COMMITTED` 에서는 SELECT 마다 새 스냅샷이므로, 분자·분모를 따로 읽으면 사이에 커밋된 퍼널이 한쪽에만 들어가 전환율이 1 을 넘는다.
    그래서 반응 집계는 **SQL 한 번**이다. 시험은 첫 반응 SELECT 가 끝난 직후 다른 연결(스레드)에서 퍼널 하나를 커밋하게 해 순서를 고정한다.
    """

    def commit_a_funnel_from_another_connection(self):
        errors = []

        def work():
            try:
                self.full_funnel(NOW + 5 * HOUR, subject=B)
            except BaseException as error:  # noqa: BLE001 — 스레드 안의 실패를 시험 실패로 올린다
                errors.append(error)
            finally:
                connection.close()

        thread = threading.Thread(target=work)
        thread.start()
        thread.join(30)
        self.assertEqual(errors, [])
        self.assertFalse(thread.is_alive())

    def test_a_funnel_committed_mid_report_cannot_split_the_numerator_from_the_denominator(self):
        self.full_funnel(NOW, subject=A)  # 보고서가 시작될 때 이미 있는 퍼널
        fired = []

        def after_first_reaction_select(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if "records_reaction" in sql and sql.lstrip().upper().startswith("SELECT") and not fired:
                fired.append(sql)
                self.commit_a_funnel_from_another_connection()  # 첫 반응 조회와 (있다면) 둘째 조회 사이에 새 퍼널이 커밋된다
            return result

        with connection.execute_wrapper(after_first_reaction_select):
            totals = self.report_for(window(1)).totals
        self.assertEqual(len(fired), 1)
        self.assertLessEqual(totals.converted_clicks, totals.clicks)
        self.assertLessEqual(totals.conversion_rate, 1.0)
        self.assertEqual(self.report_for(window(1)).totals.clicks, 2)  # 새 퍼널은 다음 조회에 보인다

    def test_the_reaction_counts_are_one_select(self):
        self.full_funnel(NOW, subject=A)
        with CaptureQueriesContext(connection) as queries:
            self.report_for(window(1))
        reaction_selects = [q["sql"] for q in queries if "records_reaction" in q["sql"]]
        self.assertEqual(len(reaction_selects), 1)
