"""캠페인 행 잠금을 둘러싼 경쟁(외부 검토 회귀 시험): 광고주 전체 상한·광고그룹 쓰기·기간 종료·재검토 반려와 해제.

실제 MySQL 연결을 스레드마다 하나씩 쓰고, 한쪽이 행을 쓰기 직전(SQL 훅, `tests/concurrency.py`)에 멈춘 사이 다른 쪽을 실행해 순서를 고정한다.
"""
import re

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings, tag
from django.urls import reverse

from assets.api import validate_image
from campaigns import api
from campaigns.models import Campaign, Creative, CreativeImage, ReviewRequest
from foundation.api import errors
from foundation.models import AuditLog
from tests.concurrency import overlap
from tests.factories import DAY, NOW, World, make_admin, png_file

EXPIRE_AT = NOW + 11 * DAY  # World 의 캠페인은 NOW + 10일에 끝난다
EXTENDED = NOW + 16 * DAY


@tag("security")
class QuotaRaceTests(TransactionTestCase):
    """외부 검토(41d2288) P2: 광고주 전체 상한과 요청 키의 경쟁.

    1. 서로 다른 캠페인의 동시 쓰기가 광고주 전체 상한(캠페인 수·이미지 보유량)을 넘겼다 — 캠페인마다 잠그면 함께 줄을 서지 않는다.
       → 만들기·이미지 교체는 광고주 잠금 행(`AdvertiserQuota`)을 가장 먼저 잡고, 잠금 안에서 상한을 다시 센다.
    2. 성공한 요청 키의 겹친 재전송이 상한 오류(409)로 끝났다 — 첫 조회와 앞선 요청의 커밋 사이의 틈.
       → 같은 잠금 안에서 키를 다시 본다.
    실제 MySQL 연결 두 개로, 한쪽이 쓰기 직전(상한 확인 뒤)에 멈춘 사이 다른 쪽을 실행한다.
    """

    def setUp(self):
        self.w = World(ends_in=None)

    def ad(self, key, color):
        return lambda: api.create_ad(
            self.w.adv,
            campaign={"name": f"광고 {key}", "starts_at": NOW, "ends_at": None, "daily_budget": 1000},
            ad_group={"name": "그룹", "pricing_unit": "IMPRESSION", "slot_ids": [self.w.slot.slot_id], "bid_amount": 30},
            creative={"title": "제목", "redirect_url": "https://example.com/", "image_file": png_file(color)},
            request_key=key,
        )

    def overlap(self, first, verb, table, second):
        """`first` 가 `table` 에 쓰기 직전(상한 확인 뒤)에 멈춘 사이 `second` 를 보낸다. 둘째는 광고주 잠금에서 기다려야 한다."""
        a, b = overlap(self, first, verb, table, second)
        self.assertEqual(a.errors, [])
        return b

    @override_settings(MAX_CAMPAIGNS_PER_ADVERTISER=2)  # 이미 1개
    def test_two_new_ads_with_different_keys_do_not_pass_the_campaign_limit(self):
        second = self.overlap(self.ad("k1", (1, 1, 1)), "INSERT", "campaigns_campaign", self.ad("k2", (2, 2, 2)))
        self.assertEqual([type(e) for e in second.errors], [api.LimitExceeded])
        self.assertEqual(Campaign.objects.filter(owner=self.w.adv).count(), 2)

    @override_settings(MAX_CAMPAIGNS_PER_ADVERTISER=2)
    def test_an_overlapping_resubmission_of_the_same_key_finds_the_first_ad_not_the_limit(self):
        second = self.overlap(self.ad("same", (1, 1, 1)), "INSERT", "campaigns_campaign", self.ad("same", (1, 1, 1)))
        self.assertEqual(second.errors, [])
        self.assertTrue(second.result.duplicate)
        self.assertEqual(Campaign.objects.filter(owner=self.w.adv).count(), 2)

    def test_two_image_replacements_in_different_campaigns_do_not_pass_the_upload_quota(self):
        other = api.create_campaign(self.w.adv, "둘째", NOW, None, 1000)
        group = api.create_ad_group(self.w.adv, other.campaign_id, "그룹", "IMPRESSION", [self.w.slot.slot_id], bid_amount=30)
        creative = api.create_creative(self.w.adv, group.ad_group_id, "제목", "https://example.com/", png_file((9, 9, 9)))
        held = sum(dict(CreativeImage.objects.filter(creative__owner=self.w.adv).values_list("image_name", "image_bytes")).values())
        a_bytes, b_bytes = (len(validate_image(png_file(c)).data) for c in ((3, 3, 3), (4, 4, 4)))
        limit = held + max(a_bytes, b_bytes) + min(a_bytes, b_bytes) - 1  # 하나씩은 들어가지만 둘 다는 안 들어간다
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=limit):
            second = self.overlap(lambda: api.replace_creative_image(self.w.adv, self.w.creative.creative_id, png_file((3, 3, 3))),
                                  "UPDATE", "campaigns_creative",
                                  lambda: api.replace_creative_image(self.w.adv, creative.creative_id, png_file((4, 4, 4))))
        self.assertEqual([type(e) for e in second.errors], [api.LimitExceeded])
        now_held = sum(dict(CreativeImage.objects.filter(creative__owner=self.w.adv).values_list("image_name", "image_bytes")).values())
        self.assertLessEqual(now_held, limit)


@tag("security")
class AdGroupWriteRaceTests(TransactionTestCase):
    """Step 3-2d: 광고그룹·입찰·소재를 바꾸는 동작은 캠페인 행 → 그 행 순서로 잠그고 다시 읽는다.

    잠그지 않고 읽은 객체를 통째로 저장하면 (1) 그 사이 다른 탭의 변경을 되돌리고(예: 제목 수정이 방금 교체한 이미지를 옛 이미지로) (2) 그 사이 끝난 캠페인에도 썼다.
    실제 MySQL 연결 두 개로, 한쪽이 행을 쓰기 직전에 멈춘 사이 다른 쪽을 실행한다.
    """

    def setUp(self):
        self.w = World(ends_in=None)
        self.cid = self.w.campaign.campaign_id

    def race(self, first, table, second, verb="UPDATE"):
        return overlap(self, first, verb, table, second)  # 둘째는 캠페인 행 잠금에서 기다린다

    def order(self):
        return list(AuditLog.objects.filter(action__in=["creative.updated", "creative.image_replaced", "ad_group.updated", "bid.added", "campaign.ended_early"])
                    .order_by("created_at", "pk").values_list("action", flat=True))

    def test_a_title_edit_does_not_revert_an_image_replaced_in_between(self):
        creative = self.w.creative.creative_id
        a, b = self.race(lambda: api.update_creative(self.w.adv, creative, {"title": "새 제목"}), "campaigns_creative",
                         lambda: api.replace_creative_image(self.w.adv, creative, png_file((1, 2, 3))))
        self.assertEqual((a.errors, b.errors), ([], []))
        row = Creative.objects.get(pk=creative)
        self.assertEqual((row.title, row.image_name), ("새 제목", b.result.image_name))  # 둘 다 남는다

    def test_a_group_edit_and_ending_the_campaign_queue_up(self):
        a, b = self.race(lambda: api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"enabled": False}), "campaigns_ad_group",
                         lambda: api.end_campaign(self.w.adv, self.cid))
        self.assertEqual((a.errors, b.errors), ([], []))
        self.assertEqual(self.order(), ["ad_group.updated", "campaign.ended_early"])  # 끝난 뒤에 쓴 변경이 없다

    def test_a_new_bid_and_ending_the_campaign_queue_up(self):
        a, b = self.race(lambda: api.add_bid(self.w.adv, self.w.group.ad_group_id, 40, expected_version=1), "campaigns_bid",
                         lambda: api.end_campaign(self.w.adv, self.cid), verb="INSERT")
        self.assertEqual((a.errors, b.errors), ([], []))
        self.assertEqual(self.order(), ["bid.added", "campaign.ended_early"])


@tag("security")
class ExpireVersusExtendTests(TransactionTestCase):
    """기간 종료(`end_expired_campaigns`)와 연장·중단 등 캠페인 행을 쓰는 동작의 경쟁 (외부 검토: expire_due 가 행을 잠그지 않는다).

    정지 중인 캠페인을 광고주가 연장하는 시점과 기간 종료가 겹치면, 끝나지 않은 캠페인의 재검토 요청이 닫히고 "기간 종료" 감사 로그가 남을 수 있었다
    (그리고 연장이 먼저 읽고 나중에 저장하면 이미 끝난 캠페인이 되살아난다 — `ENDED` 에서 나가는 전이는 없다).
    둘 중 어느 쪽이 먼저든 결과는 **하나의 일관된 상태**여야 한다: (a) 끝났다 = 상태 `ENDED`·재검토 요청 `CLOSED_ENDED`·감사 1건·연장은 `CampaignEnded` 로 거절
    (b) 연장됐다 = 상태·재검토 요청 그대로·연장된 종료 시각·감사 0건.
    실제 연결을 스레드마다 하나씩 쓰고, 한쪽이 캠페인 행을 쓰기 직전(훅)에 멈춘 사이 다른 쪽을 실행해 순서를 고정한다.
    """

    def setUp(self):
        self.w = World()
        self.cid = self.w.campaign.campaign_id
        api.suspend_campaign(self.w.admin, self.cid, "사유", now=NOW)
        self.review = api.create_review_request(self.w.adv, self.cid, "고쳤습니다", now=NOW)

    def expire(self):
        return api.end_expired_campaigns(now=EXPIRE_AT)

    def extend(self):
        return api.update_campaign(self.w.adv, self.cid, {"ends_at": EXTENDED}, now=NOW + 9 * DAY)

    def writer(self, name):
        """캠페인 행을 읽고 저장하는 동작들. 기간 종료(`EXPIRE_AT`)보다 앞선 시각으로 부른다."""
        before = NOW + 9 * DAY
        return {
            "extend": self.extend,
            "release": lambda: api.release_campaign(self.w.admin, self.cid, now=before),
            "suspend": lambda: api.suspend_campaign(self.w.admin, self.cid, "다시", now=before),
            "end": lambda: api.end_campaign(self.w.adv, self.cid, now=before),
        }[name]

    def race(self, paused_side, writer="extend"):
        """`paused_side`("expire"|"writer")가 캠페인 행을 쓰기 직전에 멈춘 사이 다른 쪽을 시작하고, 막혀 있든 끝났든 재개해 둘 다 마친다. 쓰기 쪽의 오류 목록을 돌려준다."""
        works = (self.expire, self.writer(writer)) if paused_side == "expire" else (self.writer(writer), self.expire)
        # 첫째가 행을 쥐고 있으면 둘째는 기다린다 — 끝났든 막혔든 재개 뒤에 합쳐진다
        first, second = overlap(self, works[0], "UPDATE", "campaigns_campaign", works[1], waits=False)
        expire, written = (first, second) if paused_side == "expire" else (second, first)
        self.assertEqual(expire.errors, [])
        return written.errors

    def assert_one_consistent_state(self, extend_errors):
        c = Campaign.objects.get(pk=self.cid)
        review = ReviewRequest.objects.get(pk=self.review.review_request_id)
        expired_audits = AuditLog.objects.filter(action="campaign.expired").count()
        if c.status == "ENDED":
            self.assertEqual((review.status, expired_audits), ("CLOSED_ENDED", 1))
            self.assertEqual([type(e) for e in extend_errors], [api.CampaignEnded])  # 끝난 캠페인의 연장은 거절됐다
            self.assertNotEqual(c.ends_at, EXTENDED)
        else:
            self.assertEqual((c.status, c.ends_at, review.status, expired_audits), ("SUSPENDED", EXTENDED, "OPEN", 0))
            self.assertEqual(extend_errors, [])

    def test_extension_committing_between_expire_s_read_and_write(self):
        """검토 재현: 기간 종료가 대상을 읽은 뒤 연장이 커밋되면, 끝나지 않은 캠페인의 재검토 요청이 닫히고 '기간 종료' 감사가 남았다."""
        self.assert_one_consistent_state(self.race("expire"))

    def test_expire_committing_between_extension_s_read_and_save(self):
        """연장이 캠페인을 읽은 뒤 기간 종료가 커밋되면, 연장이 전체 행을 저장해 끝난 캠페인을 되살렸다."""
        self.assert_one_consistent_state(self.race("writer"))

    def test_release_saving_after_expire_does_not_revive_the_campaign(self):
        """해제가 캠페인을 읽은 뒤 기간 종료가 커밋되면, 해제가 전체 행을 저장해 기간이 지난 캠페인이 `ACTIVE` 로 돌아갔다. 어느 순서든 끝은 `ENDED`."""
        errors = self.race("writer", "release")
        self.assertEqual(Campaign.objects.get(pk=self.cid).status, "ENDED")
        self.assertIn([type(e) for e in errors], ([], [api.CampaignEnded]))

    def test_suspend_saving_after_expire_does_not_revive_the_campaign(self):
        api.release_campaign(self.w.admin, self.cid, now=NOW + DAY)
        errors = self.race("writer", "suspend")
        self.assertEqual(Campaign.objects.get(pk=self.cid).status, "ENDED")
        self.assertIn([type(e) for e in errors], ([], [api.CampaignEnded]))

    def test_early_end_racing_expire_is_recorded_once(self):
        """광고주의 조기 종료와 기간 종료가 겹치면 종료 사유는 하나만 남는다(`ended_early` 와 `expired` 가 둘 다 생기지 않는다)."""
        api.release_campaign(self.w.admin, self.cid, now=NOW + DAY)
        self.race("writer", "end")
        ended = AuditLog.objects.filter(action__in=["campaign.ended_early", "campaign.expired"]).count()
        self.assertEqual(ended, 1)
        self.assertEqual(Campaign.objects.get(pk=self.cid).status, "ENDED")

    def test_expire_racing_a_new_review_request_leaves_no_open_request_on_an_ended_campaign(self):
        """재검토 요청 접수가 캠페인을 읽은 뒤 기간 종료가 커밋되면, 끝난 캠페인에 열린 요청이 생겼다."""
        api.reject_review_request(self.w.admin, self.review.review_request_id, "아직 아닙니다", now=NOW + DAY)  # 기존 요청을 닫아 새 요청을 받을 수 있게
        _create, expire = overlap(self, lambda: api.create_review_request(self.w.adv, self.cid, "다시", now=NOW + 9 * DAY), "INSERT", "campaigns_review_request",
                                  self.expire, waits=False)
        self.assertEqual(expire.errors, [])
        self.assertEqual(Campaign.objects.get(pk=self.cid).status, "ENDED")
        self.assertEqual(ReviewRequest.objects.filter(campaign_id=self.cid, status="OPEN").count(), 0)

    def test_expire_locks_rows_by_primary_key_not_by_secondary_index(self):
        """교착 방지(전체 시험을 돌릴 때 1213 으로 드러났다): 잠금 조회가 `ends_at`·`status` 보조 색인을 타면, 색인 레코드를 먼저 잡은 기간 종료와 기본 키 행을 먼저 잡고 색인 열을 바꾸는
        쓰기 쪽이 서로를 기다린다. 잠금 조회의 조건은 기본 키뿐이어야 한다."""
        locking = []

        def hook(execute, sql, params, many, context):
            if "FOR UPDATE" in sql and "campaigns_campaign" in sql:
                locking.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(hook):
            self.assertEqual(self.expire(), 1)
        self.assertEqual(len(locking), 1)
        where = locking[0].split("WHERE", 1)[1]
        self.assertIn("campaign_id", where)
        self.assertNotIn("ends_at", where)
        self.assertNotIn("status", where)


@tag("security")
class RejectRaceTests(TransactionTestCase):
    """외부 검토(3-1c `b396d0d`) P2 두 건의 회귀 시험.

    1. 재검토 반려가 이미 처리된 요청을 덮어썼다: 반려는 요청을 잠금 없이 읽고 OPEN 인지 본 뒤 저장했다. 그 사이 다른 반려·해제·기간 종료가 먼저 커밋되면
       이미 닫힌 요청(REJECTED·RELEASED·CLOSED_ENDED)을 늦은 반려가 덮었다. → 반려도 해제·기간 종료·재검토 접수처럼 **캠페인 행을 먼저 잠그고** 요청을 다시 읽는다.
    2. 오래된 화면의 해제 버튼이 새 중단과 새 재검토 요청까지 풀었다: 해제 폼이 화면에서 본 중단 회차를 싣지 않았다. → 폼이 중단 시각(회차)과
       대기열에서는 재검토 요청 ID 를 싣고, 서비스가 캠페인 잠금 안에서 대조해 다르면 충돌로 끝낸다.

    반려가 요청 행을 쓰기 직전에 멈춘 사이 다른 처리를 실행한다. 어느 쪽이 먼저 커밋되든 요청의 닫힌 상태·답변은 **먼저 커밋한 쪽**의 것이어야 한다."""

    def setUp(self):
        self.w = World()
        self.cid = self.w.campaign.campaign_id
        api.suspend_campaign(self.w.admin, self.cid, "사유", now=NOW)
        self.review = api.create_review_request(self.w.adv, self.cid, "고쳤습니다", now=NOW)

    def race(self, other):
        reject = lambda: api.reject_review_request(self.w.admin, self.review.review_request_id, "먼저 반려", now=NOW + DAY)  # noqa: E731
        first, second = overlap(self, reject, "UPDATE", "campaigns_review_request", other, waits=False)  # 반려가 캠페인 행을 쥐고 있으면 둘째는 기다린다
        self.assertEqual(first.errors, [])
        return second.errors

    def actions_in_commit_order(self):
        return list(AuditLog.objects.filter(target_id=str(self.cid)).order_by("created_at", "pk").values_list("action", flat=True))

    def stored(self):
        return ReviewRequest.objects.get(pk=self.review.review_request_id)

    def test_two_admins_reject_at_once(self):
        errors_ = self.race(lambda: api.reject_review_request(make_admin(), self.review.review_request_id, "나중 반려", now=NOW + DAY))
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
