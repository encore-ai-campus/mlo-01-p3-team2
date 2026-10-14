"""폼이 없는 동작(목록·상세의 버튼)의 결과 메시지와 돌아갈 곳(계획 §8.3 3-4a). 성공은 정한 문구 한 줄, 실패는 서비스 오류를 한 줄로 바꾼 것
(`console.errors.message_of`), 없는 대상은 404 — 이 동작들을 한 도우미로 모아도 그대로다."""
import uuid

from django.test import TestCase, tag
from django.urls import reverse

from campaigns import api as campaigns
from console.errors import message_of
from foundation.api import errors, set_advertiser_active
from masters import api as masters
from tests.factories import World


def shown(call):
    """서비스가 낼 오류를 화면이 메시지 한 줄로 보인 것."""
    try:
        call()
    except errors.ApiError as e:
        return message_of(e)
    raise AssertionError("서비스가 거절해야 한다")


class ActionBase(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)  # 기간 끝이 없는 캠페인(서비스는 실제 시계를 쓴다)
        self.cid, self.gid, self.crid = self.w.campaign.campaign_id, self.w.group.ad_group_id, self.w.creative.creative_id

    def post(self, name, args, data, to):
        """POST 하고 돌아갈 곳을 확인한 뒤 그 화면이 보인 메시지 [(종류, 문구)](보인 메시지는 소비되어 다음 요청에 남지 않는다)."""
        r = self.client.post(reverse(name, args=args), data, follow=True)
        self.assertEqual(r.redirect_chain, [(to, 302)])
        return [(m.level_tag, m.message) for m in r.context["messages"]]


@tag("security")
class OperatorActionMessageTests(ActionBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.w.admin)
        self.media_id = self.w.slot.media_id

    def test_media_and_slot_switches_leave_no_message_and_unknown_ids_are_404(self):
        self.assertEqual(self.post("operator:media_active", [self.media_id], {"active": "0"}, reverse("operator:media_list")), [])
        self.assertEqual(self.post("operator:slot_active", [self.w.slot.slot_id], {"active": "0"}, reverse("operator:media_detail", args=[self.media_id])), [])
        for name in ("operator:media_active", "operator:slot_active"):
            with self.subTest(name):
                self.assertEqual(self.client.post(reverse(name, args=[uuid.uuid4()]), {"active": "1"}).status_code, 404)

    def test_key_revoke(self):
        key = masters.issue_media_key(self.w.admin, self.media_id)
        detail = reverse("operator:media_detail", args=[self.media_id])
        self.assertEqual(self.post("operator:key_revoke", [key.key_id], {"media_id": self.media_id}, detail), [("success", "키를 폐기했습니다.")])
        self.assertEqual(self.client.post(reverse("operator:key_revoke", args=[uuid.uuid4()]), {"media_id": self.media_id}).status_code, 404)

    def test_suspend_reject_and_release(self):
        monitor, queue = reverse("operator:campaign_monitor"), reverse("operator:review_queue")
        self.assertEqual(self.post("operator:campaign_suspend", [self.cid], {"reason": "부적절한 이동 주소", "back": "reviews"}, queue),
                         [("success", "캠페인을 중단했습니다. 광고주 화면에 사유가 보입니다.")])
        twice = shown(lambda: campaigns.suspend_campaign(self.w.admin, self.cid, "또"))
        self.assertEqual(self.post("operator:campaign_suspend", [self.cid], {"reason": "또"}, monitor), [("error", twice)])

        review = campaigns.create_review_request(self.w.adv, self.cid, "고쳤습니다")
        no_note = shown(lambda: campaigns.reject_review_request(self.w.admin, review.review_request_id, ""))
        self.assertEqual(self.post("operator:review_reject", [review.review_request_id], {"note": ""}, queue), [("error", no_note)])
        self.assertEqual(self.post("operator:review_reject", [review.review_request_id], {"note": "그대로입니다"}, queue),
                         [("success", "재검토 요청을 반려했습니다. 중단은 그대로입니다.")])

        seen = {"suspended_at": campaigns.get_campaign(self.w.adv, self.cid).suspension.suspended_at.isoformat()}
        self.assertEqual(self.post("operator:campaign_release", [self.cid], {**seen, "back": "campaigns"}, monitor),
                         [("success", "중단을 해제했습니다. 열린 재검토 요청은 해제로 닫혔습니다.")])
        not_suspended = shown(lambda: campaigns.release_campaign(self.w.admin, self.cid))
        self.assertEqual(self.post("operator:campaign_release", [self.cid], {**seen, "back": "reviews"}, queue), [("error", not_suspended)])

    def test_advertiser_activation(self):
        uid = self.w.adv.pk
        detail = reverse("operator:advertiser_detail", args=[uid])
        already = shown(lambda: set_advertiser_active(self.w.admin, uid, True))
        self.assertEqual(self.post("operator:advertiser_active", [uid], {"active": "1"}, detail), [("error", already)])
        self.assertEqual(self.post("operator:advertiser_active", [uid], {"active": "0", "reason": "남용"}, detail),
                         [("success", "계정을 비활성화했습니다. 로그인할 수 없고 광고도 나가지 않습니다.")])
        self.assertEqual(self.post("operator:advertiser_active", [uid], {"active": "1"}, detail), [("success", "계정을 다시 활성화했습니다. 광고가 다시 나갑니다.")])


@tag("security")
class AdvertiserActionMessageTests(ActionBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.w.adv)
        self.group_page, self.campaign_page = reverse("ad_group_detail", args=[self.gid]), reverse("campaign_detail", args=[self.cid])

    def test_ad_group_switch(self):
        self.assertEqual(self.post("ad_group_enabled", [self.gid], {"enabled": "0"}, self.group_page), [("success", "광고를 껐습니다.")])
        self.assertEqual(self.post("ad_group_enabled", [self.gid], {"enabled": "1"}, self.group_page), [("success", "광고를 켰습니다.")])
        campaigns.end_campaign(self.w.adv, self.cid)
        ended_group = shown(lambda: campaigns.update_ad_group(self.w.adv, self.gid, {"enabled": True}))
        self.assertEqual(self.post("ad_group_enabled", [self.gid], {"enabled": "1"}, self.group_page), [("error", ended_group)])

    def test_campaign_status_review_and_end(self):
        self.assertEqual(self.post("campaign_status", [self.cid], {"status": "PAUSED", "back": "list"}, reverse("campaign_list")), [("success", "캠페인을 껐습니다.")])
        self.assertEqual(self.post("campaign_status", [self.cid], {"status": "ACTIVE"}, self.campaign_page), [("success", "캠페인을 켰습니다.")])
        not_suspended = shown(lambda: campaigns.create_review_request(self.w.adv, self.cid, ""))
        self.assertEqual(self.post("campaign_review", [self.cid], {"message": ""}, self.campaign_page), [("error", not_suspended)])

        campaigns.suspend_campaign(self.w.admin, self.cid, "사유")
        suspended = shown(lambda: campaigns.update_campaign(self.w.adv, self.cid, {"status": "PAUSED"}))
        self.assertEqual(self.post("campaign_status", [self.cid], {"status": "PAUSED"}, self.campaign_page), [("error", suspended)])
        self.assertEqual(self.post("campaign_review", [self.cid], {"message": "고쳤습니다"}, self.campaign_page),
                         [("success", "재검토를 요청했습니다. 관리자가 확인하면 결과가 여기와 대시보드에 보입니다.")])
        cannot_end = shown(lambda: campaigns.end_campaign(self.w.adv, self.cid))  # 중단 중에는 끝낼 수 없다
        self.assertEqual(self.post("campaign_end", [self.cid], {}, self.campaign_page), [("error", cannot_end)])

        campaigns.release_campaign(self.w.admin, self.cid)
        self.assertEqual(self.post("campaign_end", [self.cid], {}, self.campaign_page), [("success", "캠페인을 끝냈습니다. 되돌릴 수 없습니다.")])
