"""소재 목록(6-9c, 설계 §10 "소재 목록"): 소재는 광고주 소유이고 광고그룹에 연결해 하나를 선택한다. 삭제는 보관이다.

화면은 자기 소재만 보이지만, 위조한 요청이 남의 소재 ID 를 보내도 서비스가 404 로 막는다(위협 T43).
"""
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings, tag

from campaigns import api
from campaigns.models import AdGroupCreative, CampaignStatus
from foundation.api import errors
from foundation.models import AuditLog
from tests.support.concurrency import overlap
from tests.support.factories import DAY, NOW, World, make_advertiser, png_file
from tests.support.cases import Cases


def upload(w, title="새 소재", color=(1, 2, 3), group=None, now=NOW):
    return api.create_creative(w.adv, group, title, "https://example.com/new", png_file(color), now=now)


@tag("security")
class CreativeLibraryTests(Cases, TestCase):
    def setUp(self):
        self.w = World(ends_in=None)

    def second_group(self, campaign_id=None):
        return api.create_ad_group(self.w.adv, campaign_id or self.w.campaign.campaign_id, "둘째 그룹", [self.w.slot.slot_id], bid_amount=300, now=NOW)

    def titles(self):
        return sorted(f.title for f in api.candidate_facts_for_slot(self.w.slot.slot_id))

    def case_a_link_that_also_selects_is_recorded_and_moves_the_seen_time(self):
        """R3·R4(6-13b): 선택된 소재가 없는 광고에 연결하면 함께 선택된다(명시적 선택이든 아니든). 감사 기록의 `selected` 는 그 결과를 남기고,
        광고의 변경 시각도 올라 화면이 본 시각 대조(옛 탭의 이름 바꾸기)가 이 변경을 본다. 이미 선택된 소재가 있으면 연결만, 이미 나가는 소재를 다시 골라도 — 시각 그대로."""
        later, mine = NOW + DAY, upload(self.w)
        for select in (False, True):
            group = self.second_group()
            returned = api.link_creative(self.w.adv, group.ad_group_id, mine.creative_id, now=later, select=select)
            after = api.get_ad_group(self.w.adv, group.ad_group_id)
            self.assertEqual(returned.updated_at, later, select)
            self.assertEqual((after.creative_id, after.updated_at), (mine.creative_id, later), select)
            with self.assertRaises(errors.StaleVersion):
                api.update_ad_group(self.w.adv, group.ad_group_id, {"name": "옛 탭"}, expected_updated_at=group.updated_at)
            self.assertTrue(self.linked(group)["selected"], select)
        group = self.second_group()
        upload(self.w, "새로 연결", (5, 5, 5), group=group.ad_group_id, now=later)  # 새 소재를 올려 연결하는 길(광고 만들기)도 같다
        self.assertEqual(api.get_ad_group(self.w.adv, group.ad_group_id).updated_at, later)
        api.link_creative(self.w.adv, self.w.group.ad_group_id, self.w.creative.creative_id, now=later, select=True)  # 이미 나가는 소재를 다시 고름 — 바뀐 것 없음
        api.link_creative(self.w.adv, self.w.group.ad_group_id, mine.creative_id, now=later)
        self.assertEqual(api.get_ad_group(self.w.adv, self.w.group.ad_group_id).updated_at, self.w.group.updated_at)
        self.assertFalse(self.linked(self.w.group)["selected"])

    def linked(self, group):
        return AuditLog.objects.filter(action="creative.linked", detail__ad_group_id=str(group.ad_group_id)).order_by("log_id").last().detail

    def case_a_library_creative_is_reused_by_another_ad_group(self):
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

    def case_a_creative_is_selected_only_through_the_link(self):
        """R17(6-13e, 사용자 결정): 소재를 고르는 길은 연결 하나다(`select=True`). 광고그룹 수정은 소재를 받지 않는다."""
        mine = upload(self.w)
        with self.assertRaises(errors.InvalidRequest) as caught:
            api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"creative_id": mine.creative_id}, now=NOW)
        self.assertEqual(caught.exception.errors[0]["pointer"], "/")  # 모르는 필드
        api.link_creative(self.w.adv, self.w.group.ad_group_id, mine.creative_id, now=NOW)
        self.assertEqual(self.titles(), ["제목"])  # 연결만 — 이미 선택한 소재가 있으면 그대로
        api.link_creative(self.w.adv, self.w.group.ad_group_id, mine.creative_id, now=NOW, select=True)
        self.assertEqual(self.titles(), ["새 소재"])  # 결정에 나가는 것은 선택한 소재다

    def case_choosing_an_unlinked_creative_links_and_selects_it_in_one_go(self):
        """광고 상세의 "이미지"(6-11): 내 이미지 중 하나를 고르면 아직 연결되지 않았어도 같은 트랜잭션에서 연결하고 선택한다. 끝난 캠페인이면 둘 다 하지 않는다."""
        mine = api.create_creative(self.w.adv, None, "목록의 소재", "https://example.com/2", png_file((9, 9, 9)), now=NOW)
        view = api.link_creative(self.w.adv, self.w.group.ad_group_id, mine.creative_id, now=NOW, select=True)
        self.assertEqual(view.creative_id, mine.creative_id)
        self.assertEqual(AdGroupCreative.objects.filter(ad_group_id=self.w.group.ad_group_id, creative_id=mine.creative_id).count(), 1)
        api.link_creative(self.w.adv, self.w.group.ad_group_id, self.w.creative.creative_id, now=NOW, select=True)  # 이미 연결된 것은 선택만
        self.assertEqual((api.get_ad_group(self.w.adv, self.w.group.ad_group_id).creative_id, AdGroupCreative.objects.filter(ad_group_id=self.w.group.ad_group_id).count()),
                         (self.w.creative.creative_id, 2))
        other = api.create_creative(self.w.adv, None, "늦은 소재", "https://example.com/3", png_file((8, 8, 8)), now=NOW)
        api.end_campaign(self.w.adv, self.w.campaign.campaign_id, now=NOW)
        with self.assertRaises(api.CampaignEnded):
            api.link_creative(self.w.adv, self.w.group.ad_group_id, other.creative_id, now=NOW, select=True)
        self.assertFalse(AdGroupCreative.objects.filter(creative_id=other.creative_id).exists())

    def case_another_advertisers_or_an_archived_creative_is_404(self):
        other = World(ends_in=None)
        theirs = other.creative.creative_id
        for call in (lambda: api.link_creative(self.w.adv, self.w.group.ad_group_id, theirs, now=NOW),
                     lambda: api.link_creative(self.w.adv, self.w.group.ad_group_id, theirs, now=NOW, select=True),
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

    def case_a_creative_linked_to_an_unfinished_campaign_cannot_be_archived(self):
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

    def case_a_campaign_past_its_end_time_counts_as_ended(self):
        w = World()  # NOW + 10일에 끝난다
        with self.assertRaises(errors.Conflict):
            api.archive_creative(w.adv, w.creative.creative_id, now=NOW)
        self.assertTrue(api.archive_creative(w.adv, w.creative.creative_id, now=NOW + 10 * DAY).archived)  # 상태는 아직 ACTIVE 여도

    def case_archiving_frees_the_count_but_not_the_image_quota(self):
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

    def case_an_edit_reaches_every_linked_ad_group(self):
        group = self.second_group()
        api.link_creative(self.w.adv, group.ad_group_id, self.w.creative.creative_id, now=NOW)
        api.update_creative(self.w.adv, self.w.creative.creative_id, {"title": "고친 제목"}, now=NOW)
        self.assertEqual(self.titles(), ["고친 제목", "고친 제목"])

    @override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable")
    def case_switching_the_selection_keeps_earlier_images_public_while_the_campaign_lives(self):
        old = self.w.creative.image_name
        new = upload(self.w, group=self.w.group.ad_group_id)
        api.link_creative(self.w.adv, self.w.group.ad_group_id, new.creative_id, now=NOW, select=True)
        self.assertTrue(api.is_asset_servable(old, now=NOW))  # 이미 나간 결정이 화면에 남아 있을 수 있다
        self.assertTrue(api.is_asset_servable(new.image_name, now=NOW))
        library_only = upload(self.w, color=(5, 5, 5))
        self.assertFalse(api.is_asset_servable(library_only.image_name, now=NOW))  # 연결된 적 없는 소재의 이미지는 공개하지 않는다
        api.end_campaign(self.w.adv, self.w.campaign.campaign_id, now=NOW)
        self.assertFalse(api.is_asset_servable(old, now=NOW))

    def case_an_image_is_public_only_through_a_link_to_a_living_campaign(self):
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
        return {"name": "새 광고", "slot_ids": [self.w.slot.slot_id], "bid_amount": 400, **over}

    def case_an_ad_is_made_in_an_existing_campaign_with_a_new_or_reused_creative(self):
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

    def case_a_repeated_key_answers_with_the_campaign_as_of_the_given_time(self):
        """R5(6-13b): 같은 키의 다시 보냄은 받은 `now` 기준의 캠페인으로 답한다(실제 시계가 아니라) — 처음 응답과 같다."""
        short = api.create_campaign(self.w.adv, "짧은 캠페인", NOW - DAY, NOW + DAY, 1000, now=NOW)  # 실제 시계로는 이미 끝났다
        make = lambda: api.create_ad(self.w.adv, short.campaign_id, self.ad_group(), creative_id=self.w.creative.creative_id, now=NOW, request_key="k-short")
        first, again = make(), make()
        self.assertEqual((again.duplicate, again.campaign), (True, first.campaign))
        self.assertEqual(api.ad_created_by_key(self.w.adv, "k-short", now=NOW).campaign, first.campaign)

    def case_only_an_advertiser_may_create_an_ad_whatever_the_input(self):
        """R9(6-13b): 역할 검사가 입력 검사·요청 키 조회보다 먼저다 — 광고주가 아니면 입력과 상관없이 403."""
        cid = self.w.campaign.campaign_id
        api.create_ad(self.w.adv, cid, self.ad_group(), creative_id=self.w.creative.creative_id, now=NOW, request_key="k-taken")
        for kwargs in ({}, {"creative_id": self.w.creative.creative_id, "request_key": "k-taken"}):  # 소재 없음(400 이던 것)·남의 키(409 이던 것)
            with self.assertRaises(errors.Forbidden):
                api.create_ad(self.w.admin, cid, self.ad_group(), now=NOW, **kwargs)

    def test_creative_library(self):
        self.run_cases()


@tag("security")
class LinkArchiveRaceTests(Cases, TransactionTestCase):
    """연결과 보관이 겹치면 **소재 행 잠금**에서 줄을 선다 — 보관된 소재는 연결되지 않고, 연결된 소재는 보관되지 않는다(설계 §10 "캠페인 행 잠금 규약")."""

    def setUp(self):
        self.w = World(ends_in=None)
        self.mine = upload(self.w)

    def link(self):
        return api.link_creative(self.w.adv, self.w.group.ad_group_id, self.mine.creative_id)

    def archive(self):
        return api.archive_creative(self.w.adv, self.mine.creative_id)

    def case_a_link_waiting_behind_an_archive_is_refused(self):
        first, second = overlap(self, self.archive, "UPDATE", "campaigns_creative", self.link)  # 둘째는 소재 행 잠금에서 기다린다
        self.assertEqual((first.errors, [type(e) for e in second.errors]), ([], [errors.NotFound]))
        self.assertFalse(AdGroupCreative.objects.filter(creative_id=self.mine.creative_id).exists())

    def case_an_archive_waiting_behind_a_link_is_refused(self):
        first, second = overlap(self, self.link, "INSERT", "campaigns_ad_group_creative", self.archive)
        self.assertEqual((first.errors, [type(e) for e in second.errors]), ([], [errors.Conflict]))
        self.assertFalse(api.get_creative(self.w.adv, self.mine.creative_id).archived)

    def test_link_archive_race(self):
        self.run_cases()
