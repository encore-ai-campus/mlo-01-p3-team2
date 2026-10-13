"""소재 목록(6-9c, 설계 §10 "소재 목록"): 소재는 광고주 소유이고 광고그룹에 연결해 하나를 선택한다. 삭제는 보관이다.

화면은 자기 소재만 보이지만, 위조한 요청이 남의 소재 ID 를 보내도 서비스가 404 로 막는다(위협 T43).
"""
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings, tag

from campaigns import api
from campaigns.models import AdGroupCreative, CampaignStatus
from foundation.api import errors
from tests.concurrency import overlap
from tests.factories import DAY, NOW, World, make_advertiser, png_file


def upload(w, title="새 소재", color=(1, 2, 3), group=None, now=NOW):
    return api.create_creative(w.adv, group, title, "https://example.com/new", png_file(color), now=now)


@tag("security")
class CreativeLibraryTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)

    def second_group(self, campaign_id=None):
        return api.create_ad_group(self.w.adv, campaign_id or self.w.campaign.campaign_id, "둘째 그룹", "IMPRESSION", [self.w.slot.slot_id], bid_amount=30, now=NOW)

    def titles(self):
        return sorted(f.title for f in api.candidate_facts_for_slot(self.w.slot.slot_id))

    def test_a_library_creative_is_reused_by_another_ad_group(self):
        mine = upload(self.w)  # 목록에만 올린다
        self.assertFalse(AdGroupCreative.objects.filter(creative_id=mine.creative_id).exists())
        group = self.second_group()
        self.assertIsNone(group.creative_id)  # 소재가 없는 광고그룹은 후보가 아니다
        self.assertEqual(self.titles(), ["제목"])
        self.assertEqual(api.link_creative(self.w.adv, group.ad_group_id, mine.creative_id, now=NOW).creative_id, mine.creative_id)  # 처음 연결하면 선택
        self.assertEqual(self.titles(), ["새 소재", "제목"])
        api.link_creative(self.w.adv, self.w.group.ad_group_id, mine.creative_id, now=NOW)  # 이미 선택한 소재가 있으면 그대로
        self.assertEqual(api.get_ad_group(self.w.adv, self.w.group.ad_group_id).creative_id, self.w.creative.creative_id)
        (first, second) = api.list_owned_creatives(self.w.adv, now=NOW)
        self.assertEqual([(u.ad_group_name, u.selected) for u in second.uses], [("둘째 그룹", True), ("그룹", False)])
        self.assertEqual((first.creative.title, len(first.uses)), ("제목", 1))

    def test_only_a_linked_creative_can_be_selected(self):
        mine = upload(self.w)
        with self.assertRaises(errors.InvalidRequest) as caught:
            api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"creative_id": mine.creative_id}, now=NOW)
        self.assertEqual(caught.exception.errors[0]["pointer"], "/creative_id")
        api.link_creative(self.w.adv, self.w.group.ad_group_id, mine.creative_id, now=NOW)
        api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"creative_id": mine.creative_id}, now=NOW)
        self.assertEqual(self.titles(), ["새 소재"])  # 결정에 나가는 것은 선택한 소재다

    def test_another_advertisers_or_an_archived_creative_is_404(self):
        other = World(ends_in=None)
        theirs = other.creative.creative_id
        for call in (lambda: api.link_creative(self.w.adv, self.w.group.ad_group_id, theirs, now=NOW),
                     lambda: api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"creative_id": theirs}, now=NOW),
                     lambda: api.update_creative(self.w.adv, theirs, {"title": "x"}, now=NOW),
                     lambda: api.archive_creative(self.w.adv, theirs, now=NOW),
                     lambda: api.get_creative(self.w.adv, theirs),
                     lambda: api.create_ad(self.w.adv, self.w.campaign.campaign_id, self.ad_group(), creative_id=theirs, now=NOW)):
            with self.assertRaises(Http404):
                call()
        self.assertEqual(AdGroupCreative.objects.filter(creative_id=theirs).count(), 1)  # 남의 소재에는 아무것도 붙지 않았다
        self.assertEqual([o.creative.creative_id for o in api.list_owned_creatives(self.w.adv, now=NOW)], [self.w.creative.creative_id])
        archived = upload(self.w)
        api.archive_creative(self.w.adv, archived.creative_id, now=NOW)
        with self.assertRaises(Http404):
            api.link_creative(self.w.adv, self.w.group.ad_group_id, archived.creative_id, now=NOW)
        with self.assertRaises(Http404):
            api.update_creative(self.w.adv, archived.creative_id, {"title": "x"}, now=NOW)
        self.assertTrue(api.get_creative(self.w.adv, archived.creative_id).archived)  # 읽기는 된다(끝난 캠페인의 광고그룹 화면)

    def test_a_creative_linked_to_an_unfinished_campaign_cannot_be_archived(self):
        unselected = upload(self.w)
        api.link_creative(self.w.adv, self.w.group.ad_group_id, unselected.creative_id, now=NOW)  # 선택하지 않은 연결도 막는다
        cid = self.w.campaign.campaign_id
        for status in (None, "PAUSED", "SUSPENDED"):
            if status == "PAUSED":
                api.update_campaign(self.w.adv, cid, {"status": "PAUSED"}, now=NOW)
            elif status == "SUSPENDED":
                api.update_campaign(self.w.adv, cid, {"status": "ACTIVE"}, now=NOW)
                api.suspend_campaign(self.w.admin, cid, "사유", now=NOW)
            for creative in (self.w.creative, unselected):
                with self.subTest(status=status, creative=creative.title), self.assertRaises(errors.Conflict):
                    api.archive_creative(self.w.adv, creative.creative_id, now=NOW)
        api.release_campaign(self.w.admin, cid, now=NOW)
        api.end_campaign(self.w.adv, cid, now=NOW)
        self.assertTrue(api.archive_creative(self.w.adv, unselected.creative_id, now=NOW).archived)
        self.assertTrue(api.archive_creative(self.w.adv, self.w.creative.creative_id, now=NOW).archived)

    def test_a_campaign_past_its_end_time_counts_as_ended(self):
        w = World()  # NOW + 10일에 끝난다
        with self.assertRaises(errors.Conflict):
            api.archive_creative(w.adv, w.creative.creative_id, now=NOW)
        self.assertTrue(api.archive_creative(w.adv, w.creative.creative_id, now=NOW + 10 * DAY).archived)  # 상태는 아직 ACTIVE 여도

    def test_archiving_frees_the_count_but_not_the_image_quota(self):
        spare = upload(self.w, color=(9, 9, 9))
        usage = lambda: api.advertiser_usage(self.w.admin, [self.w.adv.pk])[self.w.adv.pk]  # noqa: E731
        held = usage().image_bytes
        with override_settings(MAX_CREATIVES_PER_ADVERTISER=2):
            with self.assertRaises(api.LimitExceeded):
                upload(self.w, color=(8, 8, 8))
            api.archive_creative(self.w.adv, spare.creative_id, now=NOW)
            self.assertEqual((usage().creatives, usage().image_bytes), (1, held))  # 보관해도 이미지는 보유량에 남는다
            upload(self.w, color=(8, 8, 8))  # 개수는 풀렸다
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=usage().image_bytes):
            with self.assertRaises(api.LimitExceeded):
                upload(self.w, color=(7, 7, 7))  # 보관한 소재의 이미지까지 세어 넘는다

    def test_an_edit_reaches_every_linked_ad_group(self):
        group = self.second_group()
        api.link_creative(self.w.adv, group.ad_group_id, self.w.creative.creative_id, now=NOW)
        api.update_creative(self.w.adv, self.w.creative.creative_id, {"title": "고친 제목"}, now=NOW)
        self.assertEqual(self.titles(), ["고친 제목", "고친 제목"])

    @override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable")
    def test_switching_the_selection_keeps_earlier_images_public_while_the_campaign_lives(self):
        old = self.w.creative.image_name
        new = upload(self.w, group=self.w.group.ad_group_id)
        api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"creative_id": new.creative_id}, now=NOW)
        self.assertTrue(api.is_asset_servable(old, now=NOW))  # 이미 나간 결정이 화면에 남아 있을 수 있다
        self.assertTrue(api.is_asset_servable(new.image_name, now=NOW))
        library_only = upload(self.w, color=(5, 5, 5))
        self.assertFalse(api.is_asset_servable(library_only.image_name, now=NOW))  # 연결된 적 없는 소재의 이미지는 공개하지 않는다
        api.end_campaign(self.w.adv, self.w.campaign.campaign_id, now=NOW)
        self.assertFalse(api.is_asset_servable(old, now=NOW))

    def test_an_image_is_public_only_through_a_link_to_a_living_campaign(self):
        """연결이 여럿이면 **같은 연결**의 캠페인이 살아 있어야 한다 — 한 캠페인의 상태와 다른 캠페인의 기간이 섞이면 안 된다."""
        shared = upload(self.w, color=(6, 6, 6))
        suspended = api.create_campaign(self.w.adv, "중단된 캠페인", NOW - DAY, None, 1000, now=NOW)  # 기간은 끝이 없지만 상태가 중단
        api.link_creative(self.w.adv, self.second_group(suspended.campaign_id).ad_group_id, shared.creative_id, now=NOW)
        api.suspend_campaign(self.w.admin, suspended.campaign_id, "사유", now=NOW)
        paused = api.create_campaign(self.w.adv, "기간 지난 캠페인", NOW - 2 * DAY, NOW + DAY, 1000, now=NOW)  # 상태는 살아 있지만 기간이 끝난다
        api.link_creative(self.w.adv, self.second_group(paused.campaign_id).ad_group_id, shared.creative_id, now=NOW)
        api.update_campaign(self.w.adv, paused.campaign_id, {"status": "PAUSED"}, now=NOW)
        later = NOW + 2 * DAY
        self.assertEqual(api.get_campaign(self.w.adv, paused.campaign_id, now=later).status, CampaignStatus.ENDED)
        self.assertFalse(api.is_asset_servable(shared.image_name, now=later))  # 살아 있는 상태(PAUSED)와 끝나지 않은 기간(중단 쪽)은 서로 다른 연결이다
        self.assertTrue(api.is_asset_servable(shared.image_name, now=NOW))  # 기간이 지나기 전에는 PAUSED 쪽 연결로 공개

    def ad_group(self, **over):
        return {"name": "새 광고", "pricing_unit": "IMPRESSION", "slot_ids": [self.w.slot.slot_id], "bid_amount": 40, **over}

    def test_an_ad_is_made_in_an_existing_campaign_with_a_new_or_reused_creative(self):
        cid = self.w.campaign.campaign_id
        fresh = api.create_ad(self.w.adv, cid, self.ad_group(), creative={"title": "새로", "redirect_url": "https://example.com/a", "image_file": png_file((4, 4, 4))},
                                           now=NOW, request_key="k-new")
        self.assertEqual((fresh.campaign.campaign_id, fresh.ad_group.creative_id, fresh.creative.title), (cid, fresh.creative.creative_id, "새로"))
        reused = api.create_ad(self.w.adv, cid, self.ad_group(name="재사용"), creative_id=self.w.creative.creative_id, now=NOW, request_key="k-reuse")
        self.assertEqual(reused.ad_group.creative_id, self.w.creative.creative_id)
        again = api.create_ad(self.w.adv, cid, self.ad_group(name="재사용"), creative_id=self.w.creative.creative_id, now=NOW, request_key="k-reuse")
        self.assertEqual((again.duplicate, again.ad_group.ad_group_id), (True, reused.ad_group.ad_group_id))  # 같은 키로는 한 번만
        self.assertEqual(api.ad_created_by_key(self.w.adv, "k-new").ad_group.ad_group_id, fresh.ad_group.ad_group_id)
        with self.assertRaises(errors.Conflict):
            api.ad_created_by_key(make_advertiser(), "k-new")  # 남의 키(위조한 폼)
        for creative, creative_id in ((None, None), ({"title": "x"}, self.w.creative.creative_id)):
            with self.assertRaises(errors.InvalidRequest):
                api.create_ad(self.w.adv, cid, self.ad_group(), creative=creative, creative_id=creative_id, now=NOW)

    def test_a_failed_ad_leaves_no_ad_group(self):
        before = api.list_ad_groups(self.w.adv, self.w.campaign.campaign_id)
        with self.assertRaises(errors.InvalidRequest) as caught:
            api.create_ad(self.w.adv, self.w.campaign.campaign_id, self.ad_group(),
                                       creative={"title": "x", "redirect_url": "http://insecure.example", "image_file": png_file()}, now=NOW)
        self.assertEqual(caught.exception.errors[0]["pointer"], "/creative/redirect_url")
        self.assertEqual(api.list_ad_groups(self.w.adv, self.w.campaign.campaign_id), before)
        api.end_campaign(self.w.adv, self.w.campaign.campaign_id, now=NOW)
        with self.assertRaises(api.CampaignEnded):
            api.create_ad(self.w.adv, self.w.campaign.campaign_id, self.ad_group(), creative_id=self.w.creative.creative_id, now=NOW)


@tag("security")
class LinkArchiveRaceTests(TransactionTestCase):
    """연결과 보관이 겹치면 **소재 행 잠금**에서 줄을 선다 — 보관된 소재는 연결되지 않고, 연결된 소재는 보관되지 않는다(설계 §10 "캠페인 행 잠금 규약")."""

    def setUp(self):
        self.w = World(ends_in=None)
        self.mine = upload(self.w)

    def link(self):
        return api.link_creative(self.w.adv, self.w.group.ad_group_id, self.mine.creative_id)

    def archive(self):
        return api.archive_creative(self.w.adv, self.mine.creative_id)

    def test_a_link_waiting_behind_an_archive_is_refused(self):
        first, second = overlap(self, self.archive, "UPDATE", "campaigns_creative", self.link)  # 둘째는 소재 행 잠금에서 기다린다
        self.assertEqual((first.errors, [type(e) for e in second.errors]), ([], [errors.NotFound]))
        self.assertFalse(AdGroupCreative.objects.filter(creative_id=self.mine.creative_id).exists())

    def test_an_archive_waiting_behind_a_link_is_refused(self):
        first, second = overlap(self, self.link, "INSERT", "campaigns_ad_group_creative", self.archive)
        self.assertEqual((first.errors, [type(e) for e in second.errors]), ([], [errors.Conflict]))
        self.assertFalse(api.get_creative(self.w.adv, self.mine.creative_id).archived)
