"""서비스 입력 계약(계획 §8.3 3-4a): 같은 검사를 한 곳으로 모아도 오류의 종류·위치·문구·검증 순서가 그대로다.

요청 키(두 번 하면 안 되는 동작), 켜기/끄기 값, 화면이 본 마지막 변경 시각, 관리자의 캠페인 조회.
"""
import uuid

from django.test import TestCase

from billing import api as billing
from campaigns import api as campaigns
from foundation.api import errors
from masters import api as masters
from tests.factories import DAY, NOW, World, png_file

BAD_KEYS = ("", "x" * 65, 123)
KEY_ERROR = [{"pointer": "/request_key", "message": "1~64자 문자열이어야 합니다."}]


class RequestKeyContractTests(TestCase):
    def setUp(self):
        self.w = World()
        self.media = masters.create_media(self.w.admin, "키 매체")

    def entries(self):
        """요청 키를 받는 네 입구. 키 말고는 모두 맞는 값이다."""
        return {
            "issue_media_key": lambda key: masters.issue_media_key(self.w.admin, self.media.media_id, request_key=key),
            "rotate_media_key": lambda key: masters.rotate_media_key(self.w.admin, self.media.media_id, 60, request_key=key),
            "adjust": lambda key: billing.adjust(self.w.admin, self.w.adv.pk, 10, "보정", request_key=key),
            "create_ad": lambda key: campaigns.create_ad(
                self.w.adv, campaign={"name": "새 캠페인", "starts_at": NOW, "ends_at": None, "daily_budget": 1000},
                ad_group={"name": "새 그룹", "pricing_unit": "IMPRESSION", "slot_ids": [self.w.slot.slot_id], "bid_amount": 30},
                creative={"title": "새 제목", "redirect_url": "https://example.com/new", "image_file": png_file()}, now=NOW, request_key=key),
        }

    def test_a_malformed_key_is_refused_with_the_same_problem_everywhere(self):
        for name, call in self.entries().items():
            for key in BAD_KEYS:
                with self.subTest(name, key=key), self.assertRaises(errors.InvalidRequest) as caught:
                    call(key)
                self.assertEqual(caught.exception.errors, KEY_ERROR)

    def test_no_key_and_a_64_character_key_are_accepted(self):
        for name, call in self.entries().items():
            for key in (None, name.ljust(64, "x")):  # 입구마다 다른 키(같은 키는 그 입구의 '이미 처리한 요청'이 된다)
                with self.subTest(name, key=key):
                    self.assertIsNotNone(call(key))

    def test_earlier_checks_fail_first(self):
        cases = {
            "/label": lambda: masters.issue_media_key(self.w.admin, self.media.media_id, label="\x00", request_key=""),
            "/grace_seconds": lambda: masters.rotate_media_key(self.w.admin, self.media.media_id, -1, request_key=""),
            "/note": lambda: billing.adjust(self.w.admin, self.w.adv.pk, 10, "", request_key=""),
            "/amount": lambda: billing.adjust(self.w.admin, self.w.adv.pk, 0, "보정", request_key=""),
        }
        for pointer, call in cases.items():
            with self.subTest(pointer), self.assertRaises(errors.InvalidRequest) as caught:
                call()
            self.assertEqual([e["pointer"] for e in caught.exception.errors], [pointer])

    def test_create_ad_checks_the_key_before_its_parts(self):
        with self.assertRaises(errors.InvalidRequest) as caught:
            campaigns.create_ad(self.w.adv, campaign={"name": ""}, ad_group={}, creative={}, now=NOW, request_key="")
        self.assertEqual(caught.exception.errors, KEY_ERROR)

    def test_ad_created_by_key_answers_none_for_a_malformed_or_unknown_key(self):
        for key in (*BAD_KEYS, None):
            with self.subTest(key=key), self.assertNumQueries(0):  # 형식이 틀린 키는 찾아보지도 않는다
                self.assertIsNone(campaigns.ad_created_by_key(self.w.adv, key))
        self.assertIsNone(campaigns.ad_created_by_key(self.w.adv, "x" * 64))


class EnabledValueContractTests(TestCase):
    def test_enabled_must_be_a_boolean(self):
        w = World()
        with self.assertRaises(errors.InvalidRequest) as caught:
            campaigns.update_ad_group(w.adv, w.group.ad_group_id, {"enabled": "1"}, now=NOW)
        self.assertEqual(caught.exception.errors, [{"pointer": "/enabled", "message": "true 또는 false 여야 합니다."}])


class SeenVersionContractTests(TestCase):
    """화면이 본 마지막 변경 시각과 다르면 409, 같으면 그대로 바꾼다."""

    def setUp(self):
        self.w = World()

    def calls(self, seen):
        w = self.w
        return {
            "수정하세요": [
                lambda: campaigns.update_campaign(w.adv, w.campaign.campaign_id, {"name": "새 이름"}, now=NOW, expected_updated_at=seen(w.campaign)),
                lambda: campaigns.update_ad_group(w.adv, w.group.ad_group_id, {"name": "새 이름"}, now=NOW, expected_updated_at=seen(w.group)),
                lambda: campaigns.update_creative(w.adv, w.creative.creative_id, {"title": "새 제목"}, now=NOW, expected_updated_at=seen(w.creative)),
            ],
            "바꾸세요": [
                lambda: campaigns.replace_creative_image(w.adv, w.creative.creative_id, png_file(color=(10, 200, 10)), now=NOW,
                                                         expected_updated_at=seen(w.creative)),
            ],
        }

    def test_a_stale_form_is_refused_with_its_message(self):
        for verb, calls in self.calls(lambda view: view.updated_at - DAY).items():
            for call in calls:
                with self.subTest(verb), self.assertRaises(errors.StaleVersion) as caught:
                    call()
                self.assertEqual(caught.exception.detail, f"다른 곳에서 먼저 바뀌었습니다. 새로 불러와 다시 {verb}.")

    def test_the_seen_value_or_no_value_passes(self):
        for seen in (lambda view: view.updated_at, lambda view: None):  # 켜기/끄기처럼 바꿀 값이 분명한 동작은 시각을 싣지 않는다
            for calls in self.calls(seen).values():
                for call in calls:
                    with self.subTest(call):
                        self.assertIsNotNone(call())


class AdminCampaignLookupTests(TestCase):
    def test_suspend_and_release_answer_not_found_for_a_missing_or_malformed_id(self):
        w = World()
        calls = {"suspend": lambda cid: campaigns.suspend_campaign(w.admin, cid, "사유", now=NOW),
                 "release": lambda cid: campaigns.release_campaign(w.admin, cid, now=NOW)}
        for name, call in calls.items():
            for cid, message in ((uuid.uuid4(), "캠페인을 찾을 수 없습니다."), ("not-a-uuid", "캠페인을(를) 찾을 수 없습니다.")):
                with self.subTest(name, cid=cid), self.assertRaises(errors.NotFound) as caught:
                    call(cid)
                self.assertEqual(caught.exception.detail, message)
