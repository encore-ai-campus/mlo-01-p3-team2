"""Step 3-1c 관리자 화면: 광고 모니터링(소재 썸네일·이동 주소 도메인·광고주), 중단(사유 필수)·해제, 재검토 대기 목록(해제/반려+답변), 관리자 전용 이미지 경로."""
import uuid

from django.test import TestCase, override_settings, tag
from django.urls import reverse

from campaigns import api as campaigns
from foundation.api import errors
from foundation.models import AuditLog
from tests.factories import DAY, NOW, World, make_admin, make_advertiser, png_file


class MonitoringServiceTests(TestCase):
    def setUp(self):
        self.w = World()
        self.later = campaigns.create_campaign(self.w.adv, "나중 캠페인", NOW, None, 1000, now=NOW + DAY)

    def test_newest_change_first_including_creative_changes(self):
        names = [i.campaign.name for i in campaigns.monitoring_list(self.w.admin, now=NOW + 3 * DAY)]
        self.assertEqual(names, ["나중 캠페인", "캠페인"])
        campaigns.update_creative(self.w.adv, self.w.creative.creative_id, {"redirect_url": "https://changed.example/"}, now=NOW + 2 * DAY)
        items = campaigns.monitoring_list(self.w.admin, now=NOW + 3 * DAY)
        self.assertEqual([i.campaign.name for i in items], ["캠페인", "나중 캠페인"])  # 소재의 이동 주소가 바뀌면 위로(피싱 주소 바꿔치기를 놓치지 않게)
        self.assertEqual(items[0].creatives[0].redirect_url, "https://changed.example/")
        self.assertEqual(items[1].creatives, ())

    def test_review_queue_and_admin_only(self):
        campaigns.suspend_campaign(self.w.admin, self.w.campaign.campaign_id, "부적절한 소재", now=NOW)
        review = campaigns.create_review_request(self.w.adv, self.w.campaign.campaign_id, "고쳤습니다", now=NOW)
        (item,) = campaigns.open_review_queue(self.w.admin, now=NOW)
        self.assertEqual((item.review.review_request_id, item.campaign.suspension.reason), (review.review_request_id, "부적절한 소재"))
        for call in (lambda a: campaigns.monitoring_list(a), lambda a: campaigns.open_review_queue(a)):
            with self.assertRaises(errors.Forbidden):
                call(self.w.adv)


class OperatorBase(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)  # 기간 끝이 없는 캠페인(실제 시각으로 시험해도 끝나지 않는다)
        self.client.force_login(self.w.admin)
        self.monitor = reverse("operator:campaign_monitor")
        self.cid = self.w.campaign.campaign_id

    def suspend(self, reason="부적절한 이동 주소", back="campaigns"):
        return self.client.post(reverse("operator:campaign_suspend", args=[self.cid]), {"reason": reason, "back": back})

    def release(self, back="campaigns", **extra):
        """화면이 싣는 대로: 지금 중단의 회차(중단 시각)와, 대기열이면 재검토 요청."""
        suspension = campaigns.get_campaign(self.w.adv, self.cid).suspension
        data = {"back": back, "suspended_at": suspension.suspended_at.isoformat() if suspension else "", **extra}
        return self.client.post(reverse("operator:campaign_release", args=[self.cid]), data)


@tag("security")
class CampaignMonitorPageTests(OperatorBase):
    def test_list_shows_thumbnail_domain_and_advertiser(self):
        campaigns.update_creative(self.w.adv, self.w.creative.creative_id, {"title": "<script>x</script>"}, now=NOW)
        html = self.client.get(self.monitor).content.decode()
        self.assertIn(reverse("operator:asset", args=[self.w.creative.image_name]), html)  # 관리자 전용 경로의 썸네일
        self.assertIn("<strong>example.com</strong>", html)  # 이동 주소의 도메인을 눈에 띄게
        self.assertIn('rel="noopener noreferrer nofollow"', html)
        self.assertIn(f"{self.w.adv.nickname}({self.w.adv.class_label})", html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)
        self.assertNotIn("<script>x</script>", html)

    def test_suspend_needs_a_reason_and_is_seen_by_the_advertiser_at_once(self):
        self.assertRedirects(self.suspend(reason="  "), self.monitor)
        self.assertEqual(campaigns.get_campaign(self.w.adv, self.cid).status, "ACTIVE")  # 사유 없이 중단 불가
        self.assertContains(self.client.get(self.monitor), "중단 사유")  # 무엇이 잘못됐는지 알린다
        self.assertRedirects(self.suspend(), self.monitor)
        view = campaigns.get_campaign(self.w.adv, self.cid)
        self.assertEqual((view.status, view.suspension.reason), ("SUSPENDED", "부적절한 이동 주소"))  # 광고주 쪽 상태가 바로 바뀐다
        self.assertTrue(AuditLog.objects.filter(action="campaign.suspended", actor_id=self.w.admin.pk).exists())

    @override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable")  # 운영·개발 설정과 같게(시험 설정은 꺼 둔다)
    def test_suspended_creatives_still_show_to_admins_only(self):
        self.suspend()
        name = self.w.creative.image_name
        self.assertEqual(self.client.get(reverse("asset", args=[name])).status_code, 404)  # 공개 경로는 막힌다
        r = self.client.get(reverse("operator:asset", args=[name]))
        self.assertEqual(r.status_code, 200)  # 관리자는 중단 중에도 썸네일을 본다
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", r["Cache-Control"])  # 관리자 화면의 응답은 남기지 않는다
        self.assertIn(reverse("operator:asset", args=[name]), self.client.get(self.monitor).content.decode())

    def test_admin_asset_path_rejects_odd_names_and_non_admins(self):
        base = reverse("operator:asset", args=["x"])[:-1]
        for odd in ("..%2Fsettings.py", "..%5C..%5Cmanage.py", "%2E%2E", "abc.png", self.w.creative.image_name.upper()):
            self.assertEqual(self.client.get(base + odd).status_code, 404, odd)
        self.assertEqual(self.client.get(base + "0" * 64 + ".png").status_code, 404)  # 형식은 맞지만 없는 파일
        self.client.force_login(make_advertiser())
        self.assertEqual(self.client.get(reverse("operator:asset", args=[self.w.creative.image_name])).status_code, 404)
        self.assertEqual(self.client.get(self.monitor).status_code, 404)
        self.assertEqual(self.suspend().status_code, 404)

    def test_release(self):
        self.suspend()
        seen = campaigns.get_campaign(self.w.adv, self.cid).suspension.suspended_at.isoformat()
        self.assertRedirects(self.release(), self.monitor)
        self.assertEqual(campaigns.get_campaign(self.w.adv, self.cid).status, "ACTIVE")
        self.client.post(reverse("operator:campaign_release", args=[self.cid]), {"back": "campaigns", "suspended_at": seen})  # 이미 풀린 캠페인
        self.assertContains(self.client.get(self.monitor), "중단된 캠페인이 아닙니다")
        self.client.post(reverse("operator:campaign_release", args=[self.cid]), {"back": "campaigns"})  # 중단 회차가 없는 요청
        self.assertContains(self.client.get(self.monitor), "새로 불러와 다시 시도하세요")
        self.assertEqual(self.client.post(reverse("operator:campaign_release", args=[uuid.uuid4()]), {"suspended_at": seen}).status_code, 404)

    def test_back_only_goes_to_known_pages(self):
        self.assertRedirects(self.suspend(back="https://evil.example/"), self.monitor)  # 모르는 값은 목록으로(열린 리다이렉트 없음)


@tag("security")
class ReviewQueuePageTests(OperatorBase):
    def setUp(self):
        super().setUp()
        self.suspend()
        self.review = campaigns.create_review_request(self.w.adv, self.cid, "<b>고쳤습니다</b>")
        self.queue = reverse("operator:review_queue")

    def test_queue_lists_open_requests_with_the_reason(self):
        html = self.client.get(self.queue).content.decode()
        self.assertIn("&lt;b&gt;고쳤습니다&lt;/b&gt;", html)
        self.assertIn("부적절한 이동 주소", html)
        self.assertIn(reverse("operator:asset", args=[self.w.creative.image_name]), html)

    def test_release_from_the_queue_closes_the_request(self):
        r = self.release(back="reviews", review_request_id=str(self.review.review_request_id))
        self.assertRedirects(r, self.queue)
        self.assertEqual(campaigns.list_review_requests(self.w.adv, self.cid)[0].status, "RELEASED")
        self.assertNotIn("고쳤습니다", self.client.get(self.queue).content.decode())

    def test_reject_needs_a_note_and_keeps_the_suspension(self):
        url = reverse("operator:review_reject", args=[self.review.review_request_id])
        self.assertRedirects(self.client.post(url, {"note": ""}), self.queue)
        self.assertEqual(campaigns.list_review_requests(self.w.adv, self.cid)[0].status, "OPEN")
        self.assertRedirects(self.client.post(url, {"note": "이동 주소가 여전히 같습니다"}), self.queue)
        review = campaigns.list_review_requests(self.w.adv, self.cid)[0]
        self.assertEqual((review.status, review.response_note), ("REJECTED", "이동 주소가 여전히 같습니다"))
        self.assertEqual(campaigns.get_campaign(self.w.adv, self.cid).status, "SUSPENDED")

    def test_admin_index_links(self):
        html = self.client.get(reverse("admin:index")).content.decode()
        self.assertIn(self.queue, html)
        self.assertIn(self.monitor, html)
