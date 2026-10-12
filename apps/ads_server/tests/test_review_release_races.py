"""외부 검토(3-1c `b396d0d`) P2 두 건의 회귀 시험.

1. 재검토 반려가 이미 처리된 요청을 덮어썼다: 반려는 요청을 잠금 없이 읽고 OPEN 인지 본 뒤 저장했다. 그 사이 다른 반려·해제·기간 종료가 먼저 커밋되면
   이미 닫힌 요청(REJECTED·RELEASED·CLOSED_ENDED)을 늦은 반려가 덮었다. → 반려도 해제·기간 종료·재검토 접수처럼 **캠페인 행을 먼저 잠그고** 요청을 다시 읽는다.
2. 오래된 화면의 해제 버튼이 새 중단과 새 재검토 요청까지 풀었다: 해제 폼이 화면에서 본 중단 회차를 싣지 않았다. → 폼이 중단 시각(회차)과
   대기열에서는 재검토 요청 ID 를 싣고, 서비스가 캠페인 잠금 안에서 대조해 다르면 충돌로 끝낸다.
"""
import re
import threading

from django.test import Client, TestCase, TransactionTestCase, override_settings, tag
from django.urls import reverse

from campaigns import api
from campaigns.models import Campaign, ReviewRequest
from foundation.api import errors
from foundation.models import AuditLog
from tests.concurrency import BLOCKED, WAIT, Worker, pausing_before
from tests.factories import DAY, NOW, World


@tag("security")
class RejectRaceTests(TransactionTestCase):
    """반려가 요청 행을 쓰기 직전에 멈춘 사이 다른 처리를 실행한다. 어느 쪽이 먼저 커밋되든 요청의 닫힌 상태·답변은 **먼저 커밋한 쪽**의 것이어야 한다."""

    def setUp(self):
        self.w = World()
        self.cid = self.w.campaign.campaign_id
        api.suspend_campaign(self.w.admin, self.cid, "사유", now=NOW)
        self.review = api.create_review_request(self.w.adv, self.cid, "고쳤습니다", now=NOW)

    def race(self, other):
        paused, release = threading.Event(), threading.Event()
        reject = lambda: api.reject_review_request(self.w.admin, self.review.review_request_id, "먼저 반려", now=NOW + DAY)  # noqa: E731
        first = Worker(pausing_before("UPDATE", "campaigns_review_request", reject, paused, release))
        first.start()
        self.assertTrue(paused.wait(WAIT), "멈출 지점(재검토 요청 UPDATE)에 이르지 않았다")
        second = Worker(other)
        second.start()
        second.join(BLOCKED)  # 반려가 캠페인 행을 쥐고 있으면 여기서 기다린다
        release.set()
        first.join(WAIT)
        second.join(WAIT)
        self.assertEqual(first.errors, [])
        return second.errors

    def actions_in_commit_order(self):
        return list(AuditLog.objects.filter(target_id=str(self.cid)).order_by("created_at", "pk").values_list("action", flat=True))

    def stored(self):
        return ReviewRequest.objects.get(pk=self.review.review_request_id)

    def test_two_admins_reject_at_once(self):
        errors_ = self.race(lambda: api.reject_review_request(make_second_admin(), self.review.review_request_id, "나중 반려", now=NOW + DAY))
        self.assertEqual([type(e) for e in errors_], [errors.Conflict])  # 나중 쪽은 "이미 처리된 요청"
        self.assertEqual((self.stored().status, self.stored().response_note), ("REJECTED", "먼저 반려"))  # 먼저 저장한 답변이 남는다
        self.assertEqual(self.actions_in_commit_order().count("campaign.review_rejected"), 1)

    def test_reject_versus_release(self):
        self.assertEqual(self.race(lambda: api.release_campaign(self.w.admin, self.cid, now=NOW + DAY)), [])
        order = self.actions_in_commit_order()
        self.assertLess(order.index("campaign.review_rejected"), order.index("campaign.released"))  # 반려가 먼저 커밋됐다
        self.assertEqual(self.stored().status, "REJECTED")  # 해제는 이미 닫힌 요청을 건드리지 않는다
        self.assertEqual(Campaign.objects.get(pk=self.cid).status, "ACTIVE")

    def test_reject_versus_expiry(self):
        self.assertEqual(self.race(lambda: api.end_expired_campaigns(now=NOW + 11 * DAY)), [])
        order = self.actions_in_commit_order()
        self.assertLess(order.index("campaign.review_rejected"), order.index("campaign.expired"))
        self.assertEqual(self.stored().status, "REJECTED")
        self.assertEqual(Campaign.objects.get(pk=self.cid).status, "ENDED")

    def test_a_closed_request_keeps_its_closing_reason(self):
        """경합 없이도: 이미 해제로 닫힌 요청을 반려하면 충돌이고, 닫힌 사유와 답변이 그대로다."""
        api.release_campaign(self.w.admin, self.cid, now=NOW + DAY)
        with self.assertRaises(errors.Conflict):
            api.reject_review_request(self.w.admin, self.review.review_request_id, "늦은 반려", now=NOW + DAY)
        self.assertEqual((self.stored().status, self.stored().response_note), ("RELEASED", ""))


def make_second_admin():
    from tests.factories import make_admin

    return make_admin()


@tag("security")
class StaleReleaseTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.cid = self.w.campaign.campaign_id
        api.suspend_campaign(self.w.admin, self.cid, "첫 중단")
        self.first_review = api.create_review_request(self.w.adv, self.cid, "첫 요청")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.w.admin)

    def form_fields(self, url, action):
        """화면에서 그 해제 폼의 실제 필드를 뽑는다(CSRF 포함)."""
        html = self.client.get(url).content.decode()
        form = re.search(rf'<form[^>]*action="{re.escape(action)}"[^>]*>(.*?)</form>', html, re.S).group(1)
        return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', form))

    def resuspend_with_a_new_request(self):
        """다른 관리자가 해제한 뒤, 소재를 보고 새 사유로 다시 중단하고 광고주가 새 요청을 보낸다."""
        api.release_campaign(self.w.admin, self.cid)
        api.suspend_campaign(self.w.admin, self.cid, "새 중단")
        return api.create_review_request(self.w.adv, self.cid, "새 요청")

    def assert_new_suspension_kept(self, response, new_review):
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response["Location"]), "다른 곳에서 먼저 바뀌었습니다")
        view = api.get_campaign(self.w.adv, self.cid)
        self.assertEqual((view.status, view.suspension.reason), ("SUSPENDED", "새 중단"))
        self.assertEqual(ReviewRequest.objects.get(pk=new_review.review_request_id).status, "OPEN")

    @override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable")
    def test_stale_release_from_the_review_queue_is_refused(self):
        action = reverse("operator:campaign_release", args=[self.cid])
        fields = self.form_fields(reverse("operator:review_queue"), action)
        self.assertIn("review_request_id", fields)
        self.assertIn("suspended_at", fields)
        new_review = self.resuspend_with_a_new_request()
        self.assert_new_suspension_kept(self.client.post(action, fields), new_review)
        self.assertEqual(Client().get(reverse("asset", args=[self.w.creative.image_name])).status_code, 404)  # 공개 이미지도 닫힌 채

    def test_stale_release_from_the_monitor_is_refused(self):
        action = reverse("operator:campaign_release", args=[self.cid])
        fields = self.form_fields(reverse("operator:campaign_monitor"), action)
        new_review = self.resuspend_with_a_new_request()
        self.assert_new_suspension_kept(self.client.post(action, fields), new_review)

    def test_a_fresh_form_still_releases(self):
        action = reverse("operator:campaign_release", args=[self.cid])
        self.assertEqual(self.client.post(action, self.form_fields(reverse("operator:review_queue"), action)).status_code, 302)
        self.assertEqual(api.get_campaign(self.w.adv, self.cid).status, "ACTIVE")

    def test_service_compares_the_suspension_and_the_request(self):
        seen = api.get_campaign(self.w.adv, self.cid).suspension
        new_review = self.resuspend_with_a_new_request()
        with self.assertRaises(errors.StaleVersion):
            api.release_campaign(self.w.admin, self.cid, expected_suspended_at=seen.suspended_at)
        with self.assertRaises(errors.StaleVersion):
            api.release_campaign(self.w.admin, self.cid, review_request_id=self.first_review.review_request_id)
        self.assertEqual(api.get_campaign(self.w.adv, self.cid).status, "SUSPENDED")
        current = api.get_campaign(self.w.adv, self.cid).suspension
        api.release_campaign(self.w.admin, self.cid, expected_suspended_at=current.suspended_at, review_request_id=new_review.review_request_id)
        self.assertEqual(api.get_campaign(self.w.adv, self.cid).status, "ACTIVE")

    def test_suspend_form_asks_for_confirmation(self):
        """외부 검토 P3: 계획 3-1c 의 중단 확인 창(정적 confirm.js 가 data-confirm 을 읽는다)."""
        api.release_campaign(self.w.admin, self.cid)
        html = self.client.get(reverse("operator:campaign_monitor")).content.decode()
        form = re.search(r'<form[^>]*action="[^"]*/suspend"[^>]*>', html).group(0)
        self.assertIn("data-confirm=", form)
