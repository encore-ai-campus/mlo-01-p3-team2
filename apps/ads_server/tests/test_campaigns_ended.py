from datetime import timedelta

from django.test import TestCase, tag

from campaigns import api
from campaigns.models import Campaign, ReviewRequest
from foundation.errors import InvalidRequest
from tests.factories import DAY, NOW, World, make_advertiser, png_file

LATER = NOW + 11 * DAY  # World 의 캠페인은 NOW + 10일에 끝난다


@tag("security")
class ExpireTests(TestCase):
    def test_end_expired_moves_all_three_states(self):
        w = World()
        paused = api.create_campaign(w.adv, "일시 중지", NOW - DAY, NOW + DAY, 100, now=NOW)
        api.update_campaign(w.adv, paused.campaign_id, {"status": "PAUSED"}, now=NOW)
        suspended = api.create_campaign(w.adv, "중단", NOW - DAY, NOW + DAY, 100, now=NOW)
        api.suspend_campaign(w.admin, suspended.campaign_id, "사유", now=NOW)
        active = api.create_campaign(w.adv, "집행", NOW - DAY, NOW + DAY, 100, now=NOW)
        self.assertEqual(api.end_expired_campaigns(now=NOW + 2 * DAY), 3)
        got = {c.name: c for c in api.list_campaigns(w.adv, now=NOW + 2 * DAY)}
        self.assertEqual([(got[n].status, got[n].ended_from) for n in ("집행", "일시 중지", "중단")],
                         [("ENDED", "ACTIVE"), ("ENDED", "PAUSED"), ("ENDED", "SUSPENDED")])
        self.assertEqual(Campaign.objects.get(pk=active.campaign_id).status, "ENDED")  # 표시값이 아니라 저장된 상태
        self.assertEqual(Campaign.objects.get(pk=w.campaign.campaign_id).status, "ACTIVE")  # 아직 안 끝난 캠페인은 불변

    def test_end_expired_is_idempotent_and_conditional(self):
        w = World()
        self.assertEqual(api.end_expired_campaigns(now=NOW), 0)  # 끝난 것이 없으면 아무것도 안 함
        self.assertEqual(api.end_expired_campaigns(now=LATER), 1)
        self.assertEqual(api.end_expired_campaigns(now=LATER), 0)  # 두 번째는 무변화
        self.assertEqual(api.end_expired_campaigns(now=LATER + DAY), 0)
        c = Campaign.objects.get(pk=w.campaign.campaign_id)
        self.assertEqual((c.status, c.ended_from), ("ENDED", "ACTIVE"))
        from foundation.models import AuditLog

        self.assertEqual(AuditLog.objects.filter(action="campaign.expired").count(), 1)  # 한 번만 기록

    def test_end_closes_open_review_request(self):
        w = World()
        api.suspend_campaign(w.admin, w.campaign.campaign_id, "사유", now=NOW)
        review = api.create_review_request(w.adv, w.campaign.campaign_id, "고쳤습니다", now=NOW)
        api.end_expired_campaigns(now=LATER)
        self.assertEqual(api.list_review_requests(w.adv, w.campaign.campaign_id)[0].status, "CLOSED_ENDED")
        self.assertIsNotNone(ReviewRequest.objects.get(pk=review.review_request_id).closed_at)
        with self.assertRaises(api.CampaignEnded):
            api.release_campaign(w.admin, w.campaign.campaign_id, now=LATER)  # 종료된 캠페인은 해제할 수 없다
        with self.assertRaises(api.CampaignEnded):
            api.reject_review_request(w.admin, review.review_request_id, "사유", now=LATER)

    def test_expire_before_extend_and_extend_before_expire(self):
        w = World()
        cid = w.campaign.campaign_id
        api.update_campaign(w.adv, cid, {"ends_at": LATER + 5 * DAY}, now=NOW + 9 * DAY)  # 연장이 먼저 커밋
        self.assertEqual(api.end_expired_campaigns(now=LATER), 0)  # 전환은 건너뜀
        self.assertEqual(Campaign.objects.get(pk=cid).status, "ACTIVE")
        api.end_expired_campaigns(now=LATER + 6 * DAY)  # 전환이 먼저
        with self.assertRaises(api.CampaignEnded):
            api.update_campaign(w.adv, cid, {"ends_at": LATER + 30 * DAY}, now=LATER + 6 * DAY)  # 연장은 거절


@tag("security")
class DbPredicatesAgreeWithEngineTests(TestCase):
    """DB 조건식(`expire_due`·`is_asset_servable`)은 engine 의 `is_expired` 를 쿼리로 다시 쓴 것이다. 경계에서 어긋나지 않게 대조한다."""

    def test_db_predicates_agree_with_is_expired(self):
        from engine.api import is_expired

        for offset in (timedelta(seconds=-1), timedelta(0), timedelta(seconds=1), None):
            w = World(ends_in=None)
            ends_at = None if offset is None else NOW + offset
            Campaign.objects.filter(pk=w.campaign.campaign_id).update(ends_at=ends_at)
            expected = is_expired(ends_at, NOW)
            self.assertEqual(not api.is_asset_servable(w.creative.image_name, now=NOW), expected, offset)
            changed = api.end_expired_campaigns(now=NOW)
            self.assertEqual(Campaign.objects.get(pk=w.campaign.campaign_id).status == "ENDED", expected, offset)
            self.assertEqual(changed >= (1 if expected else 0), True)
            Campaign.objects.filter(pk=w.campaign.campaign_id).update(status="ENDED", ends_at=NOW - timedelta(days=1))  # 다음 반복에 영향 없게


@tag("security")
class EndedGuardTests(TestCase):
    def writes(self, w, now):
        cid, gid, crid = w.campaign.campaign_id, w.group.ad_group_id, w.creative.creative_id
        return {
            "update_campaign": lambda: api.update_campaign(w.adv, cid, {"name": "x"}, now=now),
            "resume": lambda: api.update_campaign(w.adv, cid, {"status": "ACTIVE"}, now=now),
            "extend": lambda: api.update_campaign(w.adv, cid, {"ends_at": now + 30 * DAY}, now=now),
            "remove_end": lambda: api.update_campaign(w.adv, cid, {"ends_at": None}, now=now),
            "end": lambda: api.end_campaign(w.adv, cid, now=now),
            "create_ad_group": lambda: api.create_ad_group(w.adv, cid, "g", "IMPRESSION", [w.slot.slot_id], now=now),
            "update_ad_group": lambda: api.update_ad_group(w.adv, gid, {"enabled": False}, now=now),
            "add_bid": lambda: api.add_bid(w.adv, gid, 990, expected_version=1, now=now),
            "create_creative": lambda: api.create_creative(w.adv, gid, "t", "https://a.example", png_file(), now=now),
            "link_creative": lambda: api.link_creative(w.adv, gid, crid, now=now),
            "select_creative": lambda: api.update_ad_group(w.adv, gid, {"creative_id": crid}, now=now),
            "review_request": lambda: api.create_review_request(w.adv, cid, "m", now=now),
            "suspend": lambda: api.suspend_campaign(w.admin, cid, "사유", now=now),
            "release": lambda: api.release_campaign(w.admin, cid, now=now),
        }

    def check_all_rejected(self, w, now):
        for name, call in self.writes(w, now).items():
            with self.assertRaises(api.CampaignEnded, msg=name):
                call()

    def test_edit_rejected_when_expired_but_status_still_active(self):
        """전환 작업이 아직 안 돈 구간: 저장된 상태는 ACTIVE 지만 기간이 지났으면 어떤 쓰기도 거절한다(되살리기 방지)."""
        w = World()
        self.assertEqual(Campaign.objects.get(pk=w.campaign.campaign_id).status, "ACTIVE")
        self.check_all_rejected(w, LATER)
        self.assertEqual(Campaign.objects.get(pk=w.campaign.campaign_id).ends_at, NOW + 10 * DAY)  # 아무것도 바뀌지 않았다

    def test_ended_blocks_all_writes_below_but_reads_work(self):
        w = World()
        api.end_campaign(w.adv, w.campaign.campaign_id, now=NOW)
        self.check_all_rejected(w, NOW)
        self.assertEqual(api.get_campaign(w.adv, w.campaign.campaign_id, now=NOW).status, "ENDED")
        self.assertEqual(len(api.list_bids(w.adv, w.group.ad_group_id)), 1)
        self.assertEqual(api.get_ad_group(w.adv, w.group.ad_group_id).current_bid.amount, 300)
        self.assertEqual(api.get_creative(w.adv, w.creative.creative_id).title, "제목")
        self.assertEqual(api.candidate_facts_for_slot(w.slot.slot_id), [])  # 저장된 상태가 ENDED 라 구조상 후보가 아니다
        # 소재는 캠페인 밖에 있다 — 고치면 그 소재를 쓰는 다른 광고그룹에 다음 결정부터 적용된다(6-9c). 과거 결정은 스냅샷이라 그대로다
        self.assertEqual(api.update_creative(w.adv, w.creative.creative_id, {"title": "끝난 뒤 고침"}, now=NOW).title, "끝난 뒤 고침")

    def test_early_end_sets_ends_at_now_and_is_irreversible(self):
        w = World()
        v = api.end_campaign(w.adv, w.campaign.campaign_id, now=NOW)
        self.assertEqual((v.status, v.ended_from, v.ends_at), ("ENDED", "ACTIVE", NOW))
        with self.assertRaises(api.CampaignEnded):
            api.end_campaign(w.adv, w.campaign.campaign_id, now=NOW)  # 재시도도 ended
        with self.assertRaises(api.CampaignEnded):
            api.update_campaign(w.adv, w.campaign.campaign_id, {"status": "ACTIVE"}, now=NOW)  # 되살릴 수 없다

    def test_early_end_from_paused_and_before_start(self):
        w = World()
        api.update_campaign(w.adv, w.campaign.campaign_id, {"status": "PAUSED"}, now=NOW)
        self.assertEqual(api.end_campaign(w.adv, w.campaign.campaign_id, now=NOW).ended_from, "PAUSED")
        future = api.create_campaign(w.adv, "미래", NOW + DAY, NOW + 5 * DAY, 100, now=NOW)
        v = api.end_campaign(w.adv, future.campaign_id, now=NOW)
        self.assertEqual((v.status, v.ends_at), ("ENDED", NOW + DAY))  # 시작 전이면 시작 시각으로 확정

    def test_ends_at_must_be_in_future_and_after_start(self):
        w = World()
        cid, adv = w.campaign.campaign_id, w.adv
        for bad in (NOW - DAY, NOW, w.campaign.starts_at, w.campaign.starts_at - DAY):
            with self.assertRaises(InvalidRequest, msg=bad):
                api.update_campaign(adv, cid, {"ends_at": bad}, now=NOW)
        self.assertEqual(api.update_campaign(adv, cid, {"ends_at": NOW + timedelta(seconds=1)}, now=NOW).ends_at, NOW + timedelta(seconds=1))  # 줄이기(미래)
        self.assertEqual(api.update_campaign(adv, cid, {"ends_at": NOW + 50 * DAY}, now=NOW).ends_at, NOW + 50 * DAY)  # 늘리기
        self.assertIsNone(api.update_campaign(adv, cid, {"ends_at": None}, now=NOW).ends_at)  # 기간 제한 없음

    def test_other_advertisers_unaffected(self):
        w, other = World(), World()
        api.end_campaign(w.adv, w.campaign.campaign_id, now=NOW)
        api.update_campaign(other.adv, other.campaign.campaign_id, {"name": "계속 됨"}, now=NOW)
        self.assertEqual(make_advertiser().pk != w.adv.pk, True)
