"""Step 3-2d: 광고그룹·입찰·소재를 바꾸는 동작은 캠페인 행 → 그 행 순서로 잠그고 다시 읽는다.

잠그지 않고 읽은 객체를 통째로 저장하면 (1) 그 사이 다른 탭의 변경을 되돌리고(예: 제목 수정이 방금 교체한 이미지를 옛 이미지로) (2) 그 사이 끝난 캠페인에도 썼다.
실제 MySQL 연결 두 개로, 한쪽이 행을 쓰기 직전에 멈춘 사이 다른 쪽을 실행한다.
"""
import threading

from django.test import TransactionTestCase, tag

from campaigns import api as campaigns
from campaigns.models import Creative
from foundation.models import AuditLog
from tests.concurrency import BLOCKED, WAIT, Worker, pausing_before
from tests.factories import World, png_file


@tag("security")
class AdGroupWriteRaceTests(TransactionTestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.cid = self.w.campaign.campaign_id

    def race(self, first, table, second, verb="UPDATE"):
        paused, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        a = Worker(pausing_before(verb, table, first, paused, release))
        a.start()
        self.assertTrue(paused.wait(WAIT), f"첫 동작이 {table} {verb} 에 이르지 않았다")
        b = Worker(second)
        b.start()
        b.join(BLOCKED)
        self.assertTrue(b.is_alive(), "둘째 동작이 잠금을 기다리지 않았다")  # 캠페인 행 잠금에서
        release.set()
        a.join(WAIT)
        b.join(WAIT)
        return a, b

    def order(self):
        return list(AuditLog.objects.filter(action__in=["creative.updated", "creative.image_replaced", "ad_group.updated", "bid.added", "campaign.ended_early"])
                    .order_by("created_at", "pk").values_list("action", flat=True))

    def test_a_title_edit_does_not_revert_an_image_replaced_in_between(self):
        creative = self.w.creative.creative_id
        a, b = self.race(lambda: campaigns.update_creative(self.w.adv, creative, {"title": "새 제목"}), "campaigns_creative",
                         lambda: campaigns.replace_creative_image(self.w.adv, creative, png_file((1, 2, 3))))
        self.assertEqual((a.errors, b.errors), ([], []))
        row = Creative.objects.get(pk=creative)
        self.assertEqual((row.title, row.image_name), ("새 제목", b.result.image_name))  # 둘 다 남는다

    def test_a_group_edit_and_ending_the_campaign_queue_up(self):
        a, b = self.race(lambda: campaigns.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"enabled": False}), "campaigns_ad_group",
                         lambda: campaigns.end_campaign(self.w.adv, self.cid))
        self.assertEqual((a.errors, b.errors), ([], []))
        self.assertEqual(self.order(), ["ad_group.updated", "campaign.ended_early"])  # 끝난 뒤에 쓴 변경이 없다

    def test_a_new_bid_and_ending_the_campaign_queue_up(self):
        a, b = self.race(lambda: campaigns.add_bid(self.w.adv, self.w.group.ad_group_id, 40, expected_version=1), "campaigns_bid",
                         lambda: campaigns.end_campaign(self.w.adv, self.cid), verb="INSERT")
        self.assertEqual((a.errors, b.errors), ([], []))
        self.assertEqual(self.order(), ["bid.added", "campaign.ended_early"])
