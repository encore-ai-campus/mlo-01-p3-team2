import io
import threading
import uuid

from django.db import connection
from django.http import Http404
from django.test import Client, TestCase, TransactionTestCase, override_settings, tag

from assets.api import ImageRejected, asset_exists
from campaigns import api
from foundation.errors import Forbidden, InvalidRequest, StaleVersion
from foundation.models import AuditLog
from masters import api as masters
from tests import image_factory
from tests.factories import DAY, NOW, World, make_admin, make_advertiser, make_slot, png_file


class CampaignServiceTests(TestCase):
    def setUp(self):
        self.w = World()

    def test_create_campaign_validation(self):
        adv = self.w.adv
        bad = [
            dict(name=""), dict(name="x" * 101), dict(daily_budget=0), dict(daily_budget=1.5), dict(daily_budget=True), dict(daily_budget=2**53),
            dict(ends_at=NOW - DAY), dict(ends_at=NOW), dict(starts_at=NOW + 20 * DAY),  # 종료가 시작보다 앞/지금 이전
            dict(starts_at=NOW.replace(tzinfo=None)),
        ]
        for kw in bad:
            args = dict(name="새", starts_at=NOW, ends_at=NOW + DAY, daily_budget=100)
            args.update(kw)
            with self.assertRaises(InvalidRequest, msg=kw):
                api.create_campaign(adv, args["name"], args["starts_at"], args["ends_at"], args["daily_budget"], now=NOW)
        self.assertEqual(len(api.list_campaigns(adv, now=NOW)), 1)

    def test_only_advertisers_use_advertiser_functions_and_only_admins_admin_functions(self):
        for actor in (self.w.admin, None):
            with self.assertRaises(Forbidden):
                api.create_campaign(actor, "c", NOW, None, 10, now=NOW)
        cid = self.w.campaign.campaign_id
        for actor in (self.w.adv, make_advertiser(), None):
            with self.assertRaises(Forbidden):
                api.suspend_campaign(actor, cid, "사유", now=NOW)
            with self.assertRaises(Forbidden):
                api.release_campaign(actor, cid, now=NOW)
            with self.assertRaises(Forbidden):
                api.reject_review_request(actor, uuid.uuid4(), "사유", now=NOW)

    def test_campaign_view_shows_ended_when_period_passed_even_if_status_not_updated(self):
        later = NOW + 11 * DAY
        view = api.get_campaign(self.w.adv, self.w.campaign.campaign_id, now=later)
        self.assertEqual((view.status, view.ended_from), ("ENDED", "ACTIVE"))
        self.assertEqual(api.get_campaign(self.w.adv, self.w.campaign.campaign_id, now=NOW).status, "ACTIVE")

    def test_update_campaign_fields_and_pause_resume(self):
        cid, adv = self.w.campaign.campaign_id, self.w.adv
        v = api.update_campaign(adv, cid, {"name": "새 이름", "daily_budget": 777, "status": "PAUSED"}, now=NOW)
        self.assertEqual((v.name, v.daily_budget, v.status), ("새 이름", 777, "PAUSED"))
        self.assertEqual(api.update_campaign(adv, cid, {"status": "PAUSED"}, now=NOW).status, "PAUSED")  # 같은 값은 무변화
        self.assertEqual(api.update_campaign(adv, cid, {"status": "ACTIVE"}, now=NOW).status, "ACTIVE")
        for bad in ({}, {"starts_at": NOW}, {"status": "SUSPENDED"}, {"status": "ENDED"}, {"name": ""}, {"daily_budget": 0}):
            with self.assertRaises(InvalidRequest, msg=bad):
                api.update_campaign(adv, cid, bad, now=NOW)

    def test_ad_group_unit_must_match_slots(self):
        click_slot = make_slot(self.w.admin, unit="CLICK")
        with self.assertRaises(api.UnitMismatch):
            api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "g", "IMPRESSION", [click_slot.slot_id], now=NOW)
        with self.assertRaises(api.UnitMismatch):  # 섞인 목록
            api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "g", "IMPRESSION", [self.w.slot.slot_id, click_slot.slot_id], now=NOW)
        api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "g", "CLICK", [click_slot.slot_id], now=NOW)

    def test_ad_group_slot_validation(self):
        inactive = make_slot(self.w.admin)
        masters.set_slot_active(self.w.admin, inactive.slot_id, False)
        media_off = make_slot(self.w.admin)
        masters.set_media_active(self.w.admin, media_off.media_id, False)
        s = self.w.slot.slot_id
        for slots in ([], [uuid.uuid4()], [inactive.slot_id], [media_off.slot_id], [s, s], ["nope"], "not-a-list"):
            with self.assertRaises(InvalidRequest, msg=slots):
                api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "g", "IMPRESSION", slots, now=NOW)
        with self.assertRaises(InvalidRequest):
            api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "g", "DAILY", [s], now=NOW)
        with self.assertRaises(InvalidRequest):
            api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "g", "IMPRESSION", [s], bid_amount=0, now=NOW)
        self.assertEqual(len(api.list_ad_groups(self.w.adv, self.w.campaign.campaign_id)), 1)  # 실패한 시도는 남지 않는다

    def test_pricing_unit_immutable(self):
        for unit in ("IMPRESSION", "CLICK"):  # 같은 값이어도 항상 거절
            with self.assertRaises(api.UnitImmutable):
                api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"pricing_unit": unit}, now=NOW)

    def test_update_ad_group_replaces_slots_atomically(self):
        other = make_slot(self.w.admin)
        view = api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"slot_ids": [other.slot_id], "name": "이름", "enabled": False}, now=NOW)
        self.assertEqual((view.slot_ids, view.name, view.enabled), ((other.slot_id,), "이름", False))
        click = make_slot(self.w.admin, unit="CLICK")
        with self.assertRaises(api.UnitMismatch):
            api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"name": "바뀌면 안 됨", "slot_ids": [click.slot_id]}, now=NOW)
        after = api.get_ad_group(self.w.adv, self.w.group.ad_group_id)
        self.assertEqual((after.slot_ids, after.name), ((other.slot_id,), "이름"))
        with self.assertRaises(InvalidRequest):
            api.update_ad_group(self.w.adv, self.w.group.ad_group_id, {"enabled": "yes"}, now=NOW)

    def test_bid_out_of_range_is_stored(self):
        """입력은 거절하지 않는다: 정책 10~50 에서 5 도 500 도 저장된다(적용 금액 계산은 engine 몫)."""
        low = api.add_bid(self.w.adv, self.w.group.ad_group_id, 5, expected_version=1, now=NOW)
        high = api.add_bid(self.w.adv, self.w.group.ad_group_id, 500, expected_version=2, now=NOW)
        self.assertEqual((low.bid_version, low.amount, high.bid_version, high.amount), (2, 5, 3, 500))
        self.assertEqual([b.amount for b in api.list_bids(self.w.adv, self.w.group.ad_group_id)], [500, 5, 30])
        self.assertEqual(api.get_ad_group(self.w.adv, self.w.group.ad_group_id).current_bid.amount, 500)

    def test_bid_validation(self):
        for bad in (0, -1, 1.5, True, "30", None, 2**53):
            with self.assertRaises(InvalidRequest, msg=bad):
                api.add_bid(self.w.adv, self.w.group.ad_group_id, bad, expected_version=1, now=NOW)

    def test_bid_stale_version_conflict(self):
        gid = self.w.group.ad_group_id
        api.add_bid(self.w.adv, gid, 40, expected_version=1, now=NOW)
        with self.assertRaises(StaleVersion):
            api.add_bid(self.w.adv, gid, 45, expected_version=1, now=NOW)  # 옛 화면
        with self.assertRaises(StaleVersion):
            api.add_bid(self.w.adv, gid, 45, expected_version=None, now=NOW)  # 첫 입찰이라고 착각
        self.assertEqual([b.bid_version for b in api.list_bids(self.w.adv, gid)], [2, 1])
        empty = api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "빈 그룹", "IMPRESSION", [self.w.slot.slot_id], now=NOW)
        self.assertIsNone(empty.current_bid)
        self.assertEqual(api.add_bid(self.w.adv, empty.ad_group_id, 20, expected_version=None, now=NOW).bid_version, 1)  # 첫 입찰은 None

    def test_quota_limits(self):
        adv, cid = self.w.adv, self.w.campaign.campaign_id
        with override_settings(MAX_CAMPAIGNS_PER_ADVERTISER=1):
            with self.assertRaises(api.LimitExceeded):
                api.create_campaign(adv, "둘째", NOW, None, 10, now=NOW)
            other = make_advertiser()  # 다른 광고주는 자기 몫이 있다
            api.create_campaign(other, "남의 첫째", NOW, None, 10, now=NOW)
        with override_settings(MAX_AD_GROUPS_PER_ADVERTISER=1):
            with self.assertRaises(api.LimitExceeded):
                api.create_ad_group(adv, cid, "둘째", "IMPRESSION", [self.w.slot.slot_id], now=NOW)
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=10, MAX_CREATIVES_PER_AD_GROUP=5):
            with self.assertRaises(api.LimitExceeded):
                api.create_creative(adv, self.w.group.ad_group_id, "t", "https://a.example", png_file(), now=NOW)
        with override_settings(MAX_CREATIVES_PER_ADVERTISER=1, MAX_CREATIVES_PER_AD_GROUP=5):
            with self.assertRaises(api.LimitExceeded):
                api.create_creative(adv, self.w.group.ad_group_id, "t", "https://a.example", png_file(), now=NOW)

    def test_one_creative_per_ad_group_in_v1(self):
        with self.assertRaises(api.LimitExceeded):
            api.create_creative(self.w.adv, self.w.group.ad_group_id, "둘째", "https://a.example", png_file(), now=NOW)
        with override_settings(MAX_CREATIVES_PER_AD_GROUP=2):  # 설정만 올리면 늘어난다
            api.create_creative(self.w.adv, self.w.group.ad_group_id, "둘째", "https://a.example", png_file((1, 2, 3)), now=NOW)
        self.assertEqual(len(api.list_creatives(self.w.adv, self.w.group.ad_group_id)), 2)

    def test_creative_image_validated_and_urls_https_only(self):
        w = World(with_creative=False)
        gid = w.group.ad_group_id
        for bad in (b"just text, not an image", image_factory.other_format_bytes("GIF"), image_factory.SVG_WITH_SCRIPT):
            with self.assertRaises(ImageRejected):
                api.create_creative(w.adv, gid, "t", "https://a.example", io.BytesIO(bad), now=NOW)
        for url in ("http://a.example", "javascript:alert(1)", "https://user:pw@evil.example/x", "https://a.example/ x", "//a.example", "", "https://", None, "https://a.example/" + "x" * 2100):
            with self.assertRaises(InvalidRequest, msg=url):
                api.create_creative(w.adv, gid, "t", url, png_file(), now=NOW)
        for title in ("", " ", "x" * 201, "a‮b"):
            with self.assertRaises(InvalidRequest, msg=title):
                api.create_creative(w.adv, gid, title, "https://a.example", png_file(), now=NOW)
        self.assertEqual(api.list_creatives(w.adv, gid), [])  # 실패한 시도는 남지 않는다
        c = api.create_creative(w.adv, gid, "정상", "https://a.example/path?q=1", png_file(), now=NOW)
        self.assertTrue(asset_exists(c.image_name))
        self.assertTrue(c.image_name.endswith(".png"))

    def test_update_creative_and_replace_image_keeps_old_file(self):
        cid = self.w.creative.creative_id
        v = api.update_creative(self.w.adv, cid, {"title": "새 제목", "redirect_url": "https://b.example", "enabled": False}, now=NOW)
        self.assertEqual((v.title, v.redirect_url, v.enabled), ("새 제목", "https://b.example", False))
        for bad in ({}, {"image_name": "x"}, {"redirect_url": "http://b.example"}, {"enabled": "no"}):
            with self.assertRaises(InvalidRequest, msg=bad):
                api.update_creative(self.w.adv, cid, bad, now=NOW)
        old = self.w.creative.image_name
        new = api.replace_creative_image(self.w.adv, cid, png_file((9, 9, 9)), now=NOW)
        self.assertNotEqual(new.image_name, old)
        self.assertTrue(asset_exists(old) and asset_exists(new.image_name))  # 과거 결정이 참조할 수 있어 지우지 않는다


@tag("security")
class ImageHoldingTests(TestCase):
    """이전 이미지는 지우지 않으므로, 교체를 반복해도 광고주가 **보유한 파일 총량**이 상한을 넘지 못한다."""

    def distinct_images(self, n):
        return [png_file((i * 9 % 256, i * 17 % 256, 100 + i)) for i in range(1, n + 1)]

    def held_bytes(self, user):
        from campaigns.models import CreativeImage

        return sum(dict(CreativeImage.objects.filter(creative__ad_group__campaign__owner=user).values_list("image_name", "image_bytes")).values())

    def test_repeated_image_replacement_cannot_bypass_the_quota(self):
        w = World()
        limit = w.creative.image_bytes + w.creative.image_bytes // 2  # 현재 이미지 + 절반
        accepted = 0
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=limit):
            for image in self.distinct_images(6):
                try:
                    api.replace_creative_image(w.adv, w.creative.creative_id, image, now=NOW)
                    accepted += 1
                except api.LimitExceeded:
                    pass
        self.assertEqual(accepted, 0)  # 첫 교체부터 (현재 + 새 이미지) 가 상한을 넘는다
        self.assertLessEqual(self.held_bytes(w.adv), limit)

    def test_replacements_up_to_the_limit_then_rejected_and_rejected_uploads_leave_no_file(self):
        w = World()
        size = w.creative.image_bytes
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=size * 3 + size // 2):
            results = []
            for image in self.distinct_images(6):
                try:
                    api.replace_creative_image(w.adv, w.creative.creative_id, image, now=NOW)
                    results.append("ok")
                except api.LimitExceeded:
                    results.append("limit")
        self.assertIn("limit", results)
        self.assertLessEqual(self.held_bytes(w.adv), size * 3 + size // 2)  # 보유량은 어떤 순서로도 상한을 넘지 않는다
        current = api.get_creative(w.adv, w.creative.creative_id)
        rejected_name = None
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=self.held_bytes(w.adv)):
            from assets.api import validate_image

            probe = png_file((250, 1, 2))
            image = validate_image(probe)
            probe.seek(0)
            with self.assertRaises(api.LimitExceeded):
                api.replace_creative_image(w.adv, w.creative.creative_id, probe, now=NOW)
            rejected_name = image.name
        self.assertFalse(asset_exists(rejected_name))  # 거절된 업로드는 파일을 남기지 않는다
        self.assertEqual(api.get_creative(w.adv, w.creative.creative_id).image_name, current.image_name)

    def test_reuploading_a_file_already_held_adds_nothing(self):
        w = World()
        limit = w.creative.image_bytes  # 딱 현재 이미지 하나만큼
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=limit):
            same = api.replace_creative_image(w.adv, w.creative.creative_id, png_file(), now=NOW)  # World 와 같은 이미지
        self.assertEqual(same.image_name, w.creative.image_name)
        self.assertEqual(self.held_bytes(w.adv), limit)

    def test_other_advertisers_quota_is_independent(self):
        w, other = World(), World()
        with override_settings(MAX_UPLOAD_BYTES_PER_ADVERTISER=w.creative.image_bytes):
            with self.assertRaises(api.LimitExceeded):
                api.replace_creative_image(w.adv, w.creative.creative_id, png_file((7, 7, 7)), now=NOW)
            self.assertIsNotNone(api.replace_creative_image(other.adv, other.creative.creative_id, png_file(), now=NOW))  # 같은 이미지는 그대로

    def test_old_image_stays_servable_after_replacement_until_the_campaign_stops(self):
        """과거 결정의 이미지 URL 이 교체 직후 404 가 되면 매체의 광고가 깨진다. 단 중단·종료는 이전 이미지에도 적용된다."""
        from records import api as records

        w = World()
        decision = records.decide(w.slot.media_id, w.slot.slot_id, now=NOW)
        old_url_name = decision.chosen.image_name
        api.replace_creative_image(w.adv, w.creative.creative_id, png_file((1, 200, 3)), now=NOW)
        new_name = api.get_creative(w.adv, w.creative.creative_id).image_name
        self.assertNotEqual(old_url_name, new_name)
        with override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable"):
            client = Client()
            for name in (old_url_name, new_name):
                self.assertEqual(client.get(f"/assets/{name}").status_code, 200, name)  # 과거 결정의 URL 도 열린다
            api.suspend_campaign(w.admin, w.campaign.campaign_id, "부적절")
            for name in (old_url_name, new_name):
                self.assertEqual(client.get(f"/assets/{name}").status_code, 404, name)  # 중단은 이전 이미지에도
            api.release_campaign(w.admin, w.campaign.campaign_id)
            self.assertEqual(client.get(f"/assets/{old_url_name}").status_code, 200)
            api.end_campaign(w.adv, w.campaign.campaign_id)
            for name in (old_url_name, new_name):
                self.assertEqual(client.get(f"/assets/{name}").status_code, 404, name)
        self.assertFalse(api.is_asset_servable(old_url_name, now=NOW + 11 * DAY))


class InputHardeningTests(TestCase):
    def setUp(self):
        self.w = World(with_creative=False)

    def create(self, url):
        return api.create_creative(self.w.adv, self.w.group.ad_group_id, "t", url, png_file(), now=NOW)

    def test_malformed_urls_are_input_errors_not_exceptions(self):
        for url in ("https://[", "https://example.com:bogus/", "https://example.com:99999/", "https://example.com:0/", "https://[::1", "https://exa mple.com", "https://", "https:///path"):
            with self.assertRaises(InvalidRequest, msg=url):
                self.create(url)
        self.assertEqual(api.list_creatives(self.w.adv, self.w.group.ad_group_id), [])  # 실패한 시도는 남지 않는다
        c = self.create("https://example.com:8443/path")
        self.assertEqual(c.redirect_url, "https://example.com:8443/path")

    def test_bad_url_on_update_changes_nothing(self):
        c = self.create("https://example.com/ok")
        for url in ("https://[", "https://example.com:bogus/", "https://example.com:99999/"):
            with self.assertRaises(InvalidRequest, msg=url):
                api.update_creative(self.w.adv, c.creative_id, {"title": "바뀌면 안 됨", "redirect_url": url}, now=NOW)
        after = api.get_creative(self.w.adv, c.creative_id)
        self.assertEqual((after.title, after.redirect_url), ("t", "https://example.com/ok"))

    def test_out_of_range_datetimes_are_input_errors(self):
        from datetime import datetime, timedelta, timezone

        too_early = datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))  # UTC 로 바꾸면 표현 범위를 벗어난다
        too_late = datetime.max.replace(tzinfo=timezone(timedelta(hours=-9)))
        for bad in (too_early, too_late):
            with self.assertRaises(InvalidRequest, msg=bad):
                api.create_campaign(self.w.adv, "시각 시험", bad, None, 100, now=NOW)
            with self.assertRaises(InvalidRequest, msg=bad):
                api.update_campaign(self.w.adv, self.w.campaign.campaign_id, {"ends_at": bad}, now=NOW)
        self.assertEqual(len(api.list_campaigns(self.w.adv, now=NOW)), 1)  # 만들어지거나 바뀐 것이 없다


@tag("security")
class CampaignOwnershipTests(TestCase):
    def test_other_users_objects_are_404(self):
        w = World()
        intruder = make_advertiser()
        cid, gid, crid = w.campaign.campaign_id, w.group.ad_group_id, w.creative.creative_id
        calls = [
            lambda: api.get_campaign(intruder, cid, now=NOW),
            lambda: api.update_campaign(intruder, cid, {"name": "x"}, now=NOW),
            lambda: api.end_campaign(intruder, cid, now=NOW),
            lambda: api.create_review_request(intruder, cid, "m", now=NOW),
            lambda: api.list_review_requests(intruder, cid),
            lambda: api.list_ad_groups(intruder, cid),
            lambda: api.create_ad_group(intruder, cid, "g", "IMPRESSION", [w.slot.slot_id], now=NOW),
            lambda: api.get_ad_group(intruder, gid),
            lambda: api.update_ad_group(intruder, gid, {"name": "x"}, now=NOW),
            lambda: api.add_bid(intruder, gid, 99, expected_version=1, now=NOW),
            lambda: api.list_bids(intruder, gid),
            lambda: api.create_creative(intruder, gid, "t", "https://a.example", png_file(), now=NOW),
            lambda: api.list_creatives(intruder, gid),
            lambda: api.get_creative(intruder, crid),
            lambda: api.update_creative(intruder, crid, {"title": "x"}, now=NOW),
            lambda: api.replace_creative_image(intruder, crid, png_file(), now=NOW),
        ]
        for call in calls:
            with self.assertRaises(Http404):
                call()
        for call in (lambda: api.get_campaign(w.adv, "not-a-uuid", now=NOW), lambda: api.get_creative(w.adv, uuid.uuid4())):
            with self.assertRaises(Http404):  # 형식이 틀린 ID·없는 ID 도 같은 404
                call()
        self.assertEqual(api.list_campaigns(intruder, now=NOW), [])
        self.assertEqual(api.get_campaign(w.adv, cid, now=NOW).name, "캠페인")  # 주인의 데이터는 그대로
        self.assertEqual(api.get_ad_group(w.adv, gid).current_bid.amount, 30)


class CandidateFactsTests(TestCase):
    def test_candidate_facts_single_query_and_structure_only(self):
        w = World()
        slot_id = w.slot.slot_id
        second = World()  # 같은 슬롯을 고르지 않는 다른 광고주
        def group(name, **kw):
            return api.create_ad_group(w.adv, w.campaign.campaign_id, name, "IMPRESSION", [slot_id], **kw, now=NOW)
        group("소재 없는 그룹", bid_amount=45)  # 같은 슬롯·입찰이 있어도 소재가 없으면 후보가 아니다
        with self.assertNumQueries(1):
            facts = api.candidate_facts_for_slot(slot_id)
        self.assertEqual(len(facts), 1)  # 소재까지 갖춘 광고그룹은 World 의 것 하나
        f = facts[0]
        self.assertEqual((f.ad_group_id, f.bid_amount, f.bid_version, f.campaign_status, f.ad_group_enabled), (w.group.ad_group_id, 30, 1, "ACTIVE", True))
        self.assertEqual((f.owner_id, f.period_start, f.period_end, f.daily_budget), (w.adv.pk, NOW - DAY, NOW + 10 * DAY, 5000))
        self.assertEqual((f.title, f.redirect_url, f.image_name), ("제목", "https://example.com/landing", w.creative.image_name))
        self.assertEqual(api.candidate_facts_for_slot(second.slot.slot_id)[0].ad_group_id, second.group.ad_group_id)  # 슬롯별로 다르다
        self.assertEqual(api.candidate_facts_for_slot(uuid.uuid4()), [])

    def test_latest_bid_is_used_and_structural_exclusions(self):
        w = World()
        api.add_bid(w.adv, w.group.ad_group_id, 77, expected_version=1, now=NOW)
        self.assertEqual(api.candidate_facts_for_slot(w.slot.slot_id)[0].bid_amount, 77)  # 최대 버전
        for change, view in (
            (lambda: api.update_ad_group(w.adv, w.group.ad_group_id, {"enabled": False}, now=NOW), "광고그룹 꺼짐"),
            (lambda: api.update_ad_group(w.adv, w.group.ad_group_id, {"enabled": True}, now=NOW), None),
            (lambda: api.update_creative(w.adv, w.creative.creative_id, {"enabled": False}, now=NOW), "소재 꺼짐"),
            (lambda: api.update_creative(w.adv, w.creative.creative_id, {"enabled": True}, now=NOW), None),
            (lambda: api.update_campaign(w.adv, w.campaign.campaign_id, {"status": "PAUSED"}, now=NOW), "캠페인 일시 중지"),
            (lambda: api.update_campaign(w.adv, w.campaign.campaign_id, {"status": "ACTIVE"}, now=NOW), None),
            (lambda: api.suspend_campaign(w.admin, w.campaign.campaign_id, "사유", now=NOW), "관리자 중단"),
            (lambda: api.release_campaign(w.admin, w.campaign.campaign_id, now=NOW), None),
        ):
            change()
            self.assertEqual(len(api.candidate_facts_for_slot(w.slot.slot_id)), 0 if view else 1, view)

    def test_group_without_bid_or_creative_is_not_a_candidate(self):
        w = World(with_creative=False)
        self.assertEqual(api.candidate_facts_for_slot(w.slot.slot_id), [])  # 소재 없음
        api.create_creative(w.adv, w.group.ad_group_id, "t", "https://a.example", png_file(), now=NOW)
        self.assertEqual(len(api.candidate_facts_for_slot(w.slot.slot_id)), 1)
        nobid = api.create_ad_group(w.adv, w.campaign.campaign_id, "입찰 없음", "IMPRESSION", [w.slot.slot_id], now=NOW)
        self.assertEqual(len(api.candidate_facts_for_slot(w.slot.slot_id)), 1)  # 입찰 없는 그룹은 소재가 있어도 빠진다

    def test_expired_but_not_yet_ended_campaign_is_still_returned_for_engine_to_judge(self):
        w = World()
        self.assertEqual(len(api.candidate_facts_for_slot(w.slot.slot_id)), 1)  # 기간 판정은 조회에 넣지 않는다(engine 한 곳)


@tag("security")
class AssetServableTests(TestCase):
    def test_is_asset_servable_by_campaign_state(self):
        w = World()
        name, cid = w.creative.image_name, w.campaign.campaign_id
        self.assertTrue(api.is_asset_servable(name, now=NOW))
        api.update_campaign(w.adv, cid, {"status": "PAUSED"}, now=NOW)
        self.assertTrue(api.is_asset_servable(name, now=NOW))  # 일시 중지는 미리보기를 위해 서빙
        api.update_campaign(w.adv, cid, {"status": "ACTIVE"}, now=NOW)
        api.suspend_campaign(w.admin, cid, "부적절", now=NOW)
        self.assertFalse(api.is_asset_servable(name, now=NOW))
        api.release_campaign(w.admin, cid, now=NOW)
        self.assertTrue(api.is_asset_servable(name, now=NOW))
        self.assertFalse(api.is_asset_servable(name, now=NOW + 11 * DAY))  # 상태 갱신 전이라도 기간이 지나면 막힘
        api.end_campaign(w.adv, cid, now=NOW)
        self.assertFalse(api.is_asset_servable(name, now=NOW))
        self.assertFalse(api.is_asset_servable("0" * 64 + ".png", now=NOW))  # 등록되지 않은 이름

    def test_suspended_campaign_image_is_404_over_http(self):
        w = World()
        name = w.creative.image_name
        with override_settings(ASSET_SERVABLE_CHECK="campaigns.api.is_asset_servable"):
            client = Client()
            self.assertEqual(client.get(f"/assets/{name}").status_code, 200)
            api.suspend_campaign(w.admin, w.campaign.campaign_id, "부적절")
            self.assertEqual(client.get(f"/assets/{name}").status_code, 404)  # 중단 즉시
            api.release_campaign(w.admin, w.campaign.campaign_id)
            self.assertEqual(client.get(f"/assets/{name}").status_code, 200)


class AuditTests(TestCase):
    def test_advertiser_and_admin_actions_are_audited(self):
        w = World()
        api.update_campaign(w.adv, w.campaign.campaign_id, {"name": "바뀐 이름"}, now=NOW)
        api.suspend_campaign(w.admin, w.campaign.campaign_id, "사유", now=NOW)
        seen = set(AuditLog.objects.values_list("action", flat=True))
        self.assertLessEqual({"campaign.created", "ad_group.created", "creative.created", "campaign.updated", "campaign.suspended"}, seen)
        entry = AuditLog.objects.get(action="campaign.suspended")
        self.assertEqual((entry.actor_id, entry.detail["reason"]), (w.admin.pk, "사유"))


class ConcurrentBidTests(TransactionTestCase):
    def test_concurrent_bids_with_same_expected_version_only_one_wins(self):
        w = World()
        barrier, results = threading.Barrier(2), []

        def worker(amount):
            try:
                barrier.wait(timeout=5)
                api.add_bid(w.adv, w.group.ad_group_id, amount, expected_version=1, now=NOW)
                results.append("ok")
            except Exception as e:  # noqa: BLE001
                results.append(type(e).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(a,)) for a in (31, 32)]
        [t.start() for t in threads]
        [t.join(timeout=15) for t in threads]
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual([b.bid_version for b in api.list_bids(w.adv, w.group.ad_group_id)], [2, 1])
