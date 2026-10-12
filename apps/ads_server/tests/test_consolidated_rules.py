"""여러 곳에 있던 같은 규칙(계획 6-4a, 리팩터링 4차): 한 곳으로 모아도 결과가 그대로다.

기존 시험이 잡지 못하던 쪽만 둔다 — 키 목록의 활성 표시, 원장 커서, 그날 과금 합계·소진 집계의 경계, 캠페인 종료 시각, 재검토 요청 닫기,
광고그룹을 만든 결과의 게재 위치, 이벤트 누락 확인이 MongoDB 에 묻는 조건.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from billing import api as billing
from campaigns import api as campaigns
from campaigns import transitions as tr
from campaigns.models import Campaign
from events import api as events
from events.models import EventOutbox
from foundation.api import errors
from masters import api as masters
from masters.models import MediaKey
from tests.factories import DAY, NOW, World, make_admin, make_advertiser, make_slot

ENDS_AT_ERROR = [{"pointer": "/ends_at", "message": "종료 시각은 시작보다 뒤이고 지금보다 뒤여야 합니다."}]


def at(y, mo, d, h=0):
    return datetime(y, mo, d, h, tzinfo=timezone.utc)


class KeyListActiveTests(TestCase):
    def test_revoked_keys_and_keys_at_their_expiry_are_not_active(self):
        admin = make_admin()
        media = masters.create_media(admin, "키 목록")
        live, expiring, revoked = (masters.issue_media_key(admin, media.media_id, now=NOW) for _ in range(3))
        MediaKey.objects.filter(key_id=expiring.key_id).update(expires_at=NOW)
        masters.revoke_media_key(admin, revoked.key_id, now=NOW)

        def active(now):
            return {k.key_id: k.active for k in masters.list_media_keys(admin, media.media_id, now=now)}
        self.assertEqual(active(NOW), {live.key_id: True, expiring.key_id: False, revoked.key_id: False})  # 인증과 같은 경계: 만료 시각에 닿으면 무효
        self.assertTrue(active(NOW - timedelta(microseconds=1))[expiring.key_id])


class LedgerAndSpendTests(TestCase):
    def setUp(self):
        self.adv, self.other = make_advertiser(), make_advertiser()
        with override_settings(SIGNUP_GRANT_POINTS=1_000_000):
            billing.grant_signup(self.adv, now=at(2026, 10, 1))
            billing.grant_signup(self.other, now=at(2026, 10, 1))
        self.camp = uuid.uuid4()
        self.first = billing.charge_for_reaction(self.adv.pk, self.camp, "IMPRESSION", "IMPRESSION", 10, "r1", now=at(2026, 10, 7, 12))
        billing.charge_for_reaction(self.adv.pk, self.camp, "IMPRESSION", "IMPRESSION", 20, "r2", now=at(2026, 10, 8))  # 예산 일 시작 시각 그대로
        billing.charge_for_reaction(self.other.pk, uuid.uuid4(), "IMPRESSION", "IMPRESSION", 40, "r3", now=at(2026, 10, 8, 1))  # 다른 광고주

    def test_spent_today_counts_the_start_of_the_day_and_only_this_wallet(self):
        self.assertEqual(billing.get_wallet(self.adv, now=at(2026, 10, 8, 2)).spent_today, 20)

    def test_spend_totals_exclude_the_end_day(self):
        self.assertEqual(billing.spend_by_day([self.camp], date(2026, 10, 7), date(2026, 10, 8)), {date(2026, 10, 7): 10})
        self.assertEqual(billing.spend_by_campaign([self.camp], date(2026, 10, 7), date(2026, 10, 8)), {self.camp: 10})

    def test_a_boolean_cursor_reads_the_first_page(self):
        self.assertEqual(billing.list_ledger(self.adv, before=True), billing.list_ledger(self.adv))

    def test_the_same_key_safety_net_answers_like_a_repeated_charge(self):
        repeated = billing.charge_for_reaction(self.adv.pk, self.camp, "IMPRESSION", "IMPRESSION", 10, "r1", now=at(2026, 10, 9))
        with mock.patch("billing.services._charge", side_effect=IntegrityError("동시에 같은 키")):  # 먼저 넣은 쪽이 유일 제약을 차지한 경우
            raced = billing.charge_for_reaction(self.adv.pk, self.camp, "IMPRESSION", "IMPRESSION", 10, "r1", now=at(2026, 10, 9))
        expected = (self.first.entry, 10, 0, True)
        self.assertEqual((repeated.entry, repeated.charged, repeated.shortfall, repeated.duplicate), expected)
        self.assertEqual((raced.entry, raced.charged, raced.shortfall, raced.duplicate), expected)


class CampaignEndsAtTests(TestCase):
    def setUp(self):
        self.adv = make_advertiser()

    def test_create_refuses_an_end_in_the_past_even_after_the_start(self):
        with self.assertRaises(errors.InvalidRequest) as caught:
            campaigns.create_campaign(self.adv, "지난 캠페인", NOW - 2 * DAY, NOW - DAY, 1000, now=NOW)
        self.assertEqual(caught.exception.errors, ENDS_AT_ERROR)

    def test_update_refuses_an_end_before_a_future_start(self):
        c = campaigns.create_campaign(self.adv, "다음 주 캠페인", NOW + 5 * DAY, None, 1000, now=NOW)
        with self.assertRaises(errors.InvalidRequest) as caught:
            campaigns.update_campaign(self.adv, c.campaign_id, {"ends_at": NOW + DAY}, now=NOW)
        self.assertEqual(caught.exception.errors, ENDS_AT_ERROR)


class ReviewClosingTests(TestCase):
    def setUp(self):
        self.w = World()
        self.cid = self.w.campaign.campaign_id
        campaigns.suspend_campaign(self.w.admin, self.cid, "검토", now=NOW)
        campaigns.create_review_request(self.w.adv, self.cid, "확인 부탁", now=NOW)

    def closed(self):
        (review,) = campaigns.list_review_requests(self.w.adv, self.cid)
        return review.status, review.closed_at, review.response_note

    def test_release_closes_the_open_review_at_that_moment(self):
        campaigns.release_campaign(self.w.admin, self.cid, now=NOW + DAY)
        self.assertEqual(self.closed(), ("RELEASED", NOW + DAY, ""))

    def test_ending_a_suspended_campaign_closes_only_the_open_review_at_that_moment(self):
        (rejected,) = campaigns.list_review_requests(self.w.adv, self.cid)
        campaigns.reject_review_request(self.w.admin, rejected.review_request_id, "아직 아닙니다", now=NOW)
        campaigns.create_review_request(self.w.adv, self.cid, "다시 확인 부탁", now=NOW + timedelta(hours=1))
        with transaction.atomic():
            tr.apply(Campaign.objects.select_for_update().get(pk=self.cid), "expire", tr.SYSTEM, NOW + DAY)
        reviews = [(r.status, r.closed_at, r.response_note) for r in campaigns.list_review_requests(self.w.adv, self.cid)]
        self.assertEqual(reviews, [("CLOSED_ENDED", NOW + DAY, ""), ("REJECTED", NOW, "아직 아닙니다")])  # 이미 닫힌 요청은 그대로


class AdGroupCreatedSlotsTests(TestCase):
    def test_the_created_group_reports_its_slots_like_a_later_read(self):
        w = World()
        second = make_slot(w.admin)
        group = campaigns.create_ad_group(w.adv, w.campaign.campaign_id, "둘째 그룹", "IMPRESSION", [second.slot_id, w.slot.slot_id], now=NOW)
        self.assertEqual(group.slot_ids, tuple(sorted([w.slot.slot_id, second.slot_id], key=str)))
        self.assertEqual(group.slot_ids, campaigns.get_ad_group(w.adv, group.ad_group_id).slot_ids)


class MissingEventIdsTests(TestCase):
    def test_ids_all_found_in_the_outbox_do_not_touch_mongodb(self):
        rows = EventOutbox.objects.bulk_create([
            EventOutbox(event_id=uuid.uuid4(), event_name="ad.decision", schema_version=1, aggregate_id=uuid.uuid4(), payload={}, created_at=NOW)
            for _ in range(3)
        ])
        with mock.patch("events.store.collection", side_effect=AssertionError("MongoDB 에 묻지 않아야 한다")):
            self.assertEqual(events.missing_event_ids([r.event_id for r in rows], chunk=2), [])
