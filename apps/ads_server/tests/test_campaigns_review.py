import uuid
from datetime import timedelta

from django.db import transaction
from django.test import TestCase, tag

from campaigns import api
from campaigns import transitions as tr
from campaigns.models import Campaign, ReviewRequest
from foundation.errors import Conflict, InvalidRequest
from foundation.models import AuditLog
from tests.factories import DAY, NOW, World


class ReviewRequestTests(TestCase):
    def setUp(self):
        self.w = World()
        self.cid = self.w.campaign.campaign_id

    def suspend(self):
        return api.suspend_campaign(self.w.admin, self.cid, "부적절한 소재", now=NOW)

    def test_review_request_only_when_suspended_and_one_open(self):
        with self.assertRaises(api.NotSuspended):
            api.create_review_request(self.w.adv, self.cid, "아직 안 막힘", now=NOW)
        view = self.suspend()
        self.assertEqual((view.status, view.suspension.reason, view.suspension.open_review_request_id), ("SUSPENDED", "부적절한 소재", None))
        review = api.create_review_request(self.w.adv, self.cid, "제목을 고쳤습니다", now=NOW)
        self.assertEqual((review.status, review.message), ("OPEN", "제목을 고쳤습니다"))
        with self.assertRaises(api.ReviewPending):
            api.create_review_request(self.w.adv, self.cid, "또", now=NOW)
        self.assertEqual(api.get_campaign(self.w.adv, self.cid, now=NOW).suspension.open_review_request_id, review.review_request_id)
        self.assertEqual(ReviewRequest.objects.filter(campaign_id=self.cid).count(), 1)

    def test_review_message_is_optional_and_validated(self):
        self.suspend()
        with self.assertRaises(InvalidRequest):
            api.create_review_request(self.w.adv, self.cid, "x" * 501, now=NOW)
        self.assertEqual(api.create_review_request(self.w.adv, self.cid, now=NOW).message, "")

    def test_reject_keeps_suspension_and_allows_a_new_request(self):
        self.suspend()
        review = api.create_review_request(self.w.adv, self.cid, "고침", now=NOW)
        done = api.reject_review_request(self.w.admin, review.review_request_id, "아직 부족합니다", now=NOW)
        self.assertEqual((done.status, done.response_note), ("REJECTED", "아직 부족합니다"))
        self.assertIsNotNone(done.closed_at)
        self.assertEqual(api.get_campaign(self.w.adv, self.cid, now=NOW).status, "SUSPENDED")  # 정지 유지
        self.assertEqual(api.create_review_request(self.w.adv, self.cid, "다시", now=NOW).status, "OPEN")  # 닫힌 뒤 다시 요청 가능
        with self.assertRaises(Conflict):
            api.reject_review_request(self.w.admin, review.review_request_id, "또", now=NOW)  # 이미 처리됨
        with self.assertRaises(InvalidRequest):
            api.reject_review_request(self.w.admin, api.list_review_requests(self.w.adv, self.cid)[0].review_request_id, " ", now=NOW)

    def test_release_activates_campaign_and_closes_open_request(self):
        self.suspend()
        review = api.create_review_request(self.w.adv, self.cid, "고침", now=NOW)
        view = api.release_campaign(self.w.admin, self.cid, now=NOW)
        self.assertEqual((view.status, view.suspension), ("ACTIVE", None))
        self.assertEqual(ReviewRequest.objects.get(pk=review.review_request_id).status, "RELEASED")
        api.suspend_campaign(self.w.admin, self.cid, "다시", now=NOW)
        self.assertIsNone(api.get_campaign(self.w.adv, self.cid, now=NOW).suspension.open_review_request_id)

    def test_release_without_request_and_when_not_suspended(self):
        with self.assertRaises(api.NotSuspended):
            api.release_campaign(self.w.admin, self.cid, now=NOW)
        self.suspend()
        self.assertEqual(api.release_campaign(self.w.admin, self.cid, now=NOW).status, "ACTIVE")  # 요청 없이도 직접 해제
        with self.assertRaises(api.NotSuspended):
            api.release_campaign(self.w.admin, self.cid, now=NOW)

    def test_suspend_requires_reason_and_a_live_state(self):
        for reason in ("", " ", "x" * 501):
            with self.assertRaises(InvalidRequest, msg=reason):
                api.suspend_campaign(self.w.admin, self.cid, reason, now=NOW)
        self.suspend()
        with self.assertRaises(Conflict):  # 이미 중단됨
            self.suspend()
        with self.assertRaises(Exception) as cm:
            api.suspend_campaign(self.w.admin, uuid.uuid4(), "사유", now=NOW)
        self.assertEqual(cm.exception.status, 404)

    def test_paused_campaign_can_be_suspended_and_release_returns_to_active(self):
        api.update_campaign(self.w.adv, self.cid, {"status": "PAUSED"}, now=NOW)
        self.assertEqual(self.suspend().status, "SUSPENDED")
        self.assertEqual(api.release_campaign(self.w.admin, self.cid, now=NOW).status, "ACTIVE")


@tag("security")
class SuspendedStateTests(TestCase):
    def test_suspended_blocks_advertiser_status_change_but_allows_other_edits(self):
        w = World()
        cid = w.campaign.campaign_id
        api.suspend_campaign(w.admin, cid, "사유", now=NOW)
        for status in ("ACTIVE", "PAUSED"):
            with self.assertRaises(api.CampaignSuspended, msg=status):
                api.update_campaign(w.adv, cid, {"status": status}, now=NOW)
        with self.assertRaises(api.CampaignSuspended):
            api.end_campaign(w.adv, cid, now=NOW)
        # 고쳐서 다시 집행할 수 있도록 그 밖의 수정은 허용한다
        api.update_campaign(w.adv, cid, {"name": "고침", "daily_budget": 10}, now=NOW)
        api.add_bid(w.adv, w.group.ad_group_id, 40, expected_version=1, now=NOW)
        api.update_creative(w.adv, w.creative.creative_id, {"title": "고친 제목"}, now=NOW)
        self.assertEqual(api.get_campaign(w.adv, cid, now=NOW).status, "SUSPENDED")
        with self.assertRaises(api.CampaignSuspended):  # 이름과 상태를 함께 보내면 전부 취소
            api.update_campaign(w.adv, cid, {"name": "취소돼야 함", "status": "ACTIVE"}, now=NOW)
        self.assertEqual(api.get_campaign(w.adv, cid, now=NOW).name, "고침")

    def test_review_and_suspension_actions_are_audited(self):
        w = World()
        cid = w.campaign.campaign_id
        api.suspend_campaign(w.admin, cid, "사유", now=NOW)
        review = api.create_review_request(w.adv, cid, "고침", now=NOW)
        api.reject_review_request(w.admin, review.review_request_id, "반려 사유", now=NOW)
        api.release_campaign(w.admin, cid, now=NOW)
        seen = list(AuditLog.objects.filter(action__startswith="campaign.").values_list("action", flat=True))
        for action in ("campaign.suspended", "campaign.review_requested", "campaign.review_rejected", "campaign.released"):
            self.assertIn(action, seen)
        self.assertEqual(AuditLog.objects.get(action="campaign.review_rejected").actor_id, w.admin.pk)


class ReviewClosingTests(TestCase):
    def setUp(self):
        self.w = World()
        self.cid = self.w.campaign.campaign_id
        api.suspend_campaign(self.w.admin, self.cid, "검토", now=NOW)
        api.create_review_request(self.w.adv, self.cid, "확인 부탁", now=NOW)

    def closed(self):
        (review,) = api.list_review_requests(self.w.adv, self.cid)
        return review.status, review.closed_at, review.response_note

    def test_release_closes_the_open_review_at_that_moment(self):
        api.release_campaign(self.w.admin, self.cid, now=NOW + DAY)
        self.assertEqual(self.closed(), ("RELEASED", NOW + DAY, ""))

    def test_ending_a_suspended_campaign_closes_only_the_open_review_at_that_moment(self):
        (rejected,) = api.list_review_requests(self.w.adv, self.cid)
        api.reject_review_request(self.w.admin, rejected.review_request_id, "아직 아닙니다", now=NOW)
        api.create_review_request(self.w.adv, self.cid, "다시 확인 부탁", now=NOW + timedelta(hours=1))
        with transaction.atomic():
            tr.apply(Campaign.objects.select_for_update().get(pk=self.cid), "expire", tr.SYSTEM, NOW + DAY)
        reviews = [(r.status, r.closed_at, r.response_note) for r in api.list_review_requests(self.w.adv, self.cid)]
        self.assertEqual(reviews, [("CLOSED_ENDED", NOW + DAY, ""), ("REJECTED", NOW, "아직 아닙니다")])  # 이미 닫힌 요청은 그대로
