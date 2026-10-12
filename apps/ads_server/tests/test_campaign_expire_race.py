"""기간 종료(`end_expired_campaigns`)와 연장·중단 등 캠페인 행을 쓰는 동작의 경쟁 (외부 검토: expire_due 가 행을 잠그지 않는다).

정지 중인 캠페인을 광고주가 연장하는 시점과 기간 종료가 겹치면, 끝나지 않은 캠페인의 재검토 요청이 닫히고 "기간 종료" 감사 로그가 남을 수 있었다
(그리고 연장이 먼저 읽고 나중에 저장하면 이미 끝난 캠페인이 되살아난다 — `ENDED` 에서 나가는 전이는 없다).
둘 중 어느 쪽이 먼저든 결과는 **하나의 일관된 상태**여야 한다: (a) 끝났다 = 상태 `ENDED`·재검토 요청 `CLOSED_ENDED`·감사 1건·연장은 `CampaignEnded` 로 거절
(b) 연장됐다 = 상태·재검토 요청 그대로·연장된 종료 시각·감사 0건.
실제 연결을 스레드마다 하나씩 쓰고, 한쪽이 캠페인 행을 쓰기 직전(훅)에 멈춘 사이 다른 쪽을 실행해 순서를 고정한다.
"""
import threading

from django.db import connection
from django.test import TransactionTestCase, tag

from campaigns import api
from campaigns.models import Campaign, ReviewRequest
from foundation.models import AuditLog
from tests.concurrency import BLOCKED, WAIT, Worker, pausing_before
from tests.factories import DAY, NOW, World

EXPIRE_AT = NOW + 11 * DAY  # World 의 캠페인은 NOW + 10일에 끝난다
EXTENDED = NOW + 16 * DAY




@tag("security")
class ExpireVersusExtendTests(TransactionTestCase):
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
        paused, release = threading.Event(), threading.Event()
        works = (self.expire, self.writer(writer)) if paused_side == "expire" else (self.writer(writer), self.expire)
        first = Worker(pausing_before("UPDATE", "campaigns_campaign", works[0], paused, release))
        first.start()
        self.assertTrue(paused.wait(WAIT), "멈출 지점(캠페인 행 UPDATE)에 이르지 않았다")
        second = Worker(works[1])
        second.start()
        second.join(BLOCKED)  # 첫째가 행을 쥐고 있으면 여기서 기다린다 — 끝났든 막혔든 재개 뒤에 합쳐진다
        release.set()
        first.join(WAIT)
        second.join(WAIT)
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
        paused, release = threading.Event(), threading.Event()
        create = Worker(pausing_before("INSERT", "campaigns_review_request", lambda: api.create_review_request(self.w.adv, self.cid, "다시", now=NOW + 9 * DAY), paused, release))
        create.start()
        self.assertTrue(paused.wait(WAIT))
        expire = Worker(self.expire)
        expire.start()
        expire.join(BLOCKED)
        release.set()
        create.join(WAIT)
        expire.join(WAIT)
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
