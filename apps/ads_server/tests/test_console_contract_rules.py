"""Step 3 종료 점검: C6(`console.openapi.yaml`)는 V1 에서 API 로 구현하지 않지만 **서비스가 지킬 규칙의 원본**이다(설계 §6.6, 계획 3-2).

계약의 값 목록과 칸의 한계를 서비스에 직접 대어 본다 — 계약만 바꾸거나 서비스만 바꾸면 실패한다. 화면 폼의 한계는 보지 않는다(화면은 서비스를 따른다).
"""
from django.core.exceptions import ValidationError
from django.test import TestCase, tag

from billing.api import register_advertiser
from billing.models import EntryType
from campaigns import api as campaigns
from campaigns.models import CampaignStatus, ReviewStatus
from foundation.api import MAX_AMOUNT, change_password, errors, update_profile
from masters.models import Audience, PricingUnit
from tests.contract_support import Contract
from tests.factories import NOW, PW, World


@tag("security")
class ConsoleContractRuleTests(TestCase):
    contract = Contract("console")

    def schema(self, name):
        return self.contract.spec["components"]["schemas"][name]

    def test_value_lists_and_amounts_match_the_models(self):
        for schema, choices in (("PricingUnit", PricingUnit), ("CampaignStatus", CampaignStatus), ("LedgerType", EntryType), ("Audience", Audience),
                                ("ReviewRequestStatus", ReviewStatus)):
            self.assertEqual(set(self.schema(schema)["enum"]), set(choices.values), schema)
        self.assertEqual(self.schema("Money")["maximum"], MAX_AMOUNT)

    def test_text_limits_match_the_services(self):
        """칸마다 계약의 `maxLength` 글자는 받고, 하나 넘거나 `minLength` 에 못 미치면 거절한다(400 — 서비스의 `InvalidRequest`, 계정 서비스는 `ValidationError`)."""
        w = World(ends_in=None)
        suspended = campaigns.create_campaign(w.adv, "중단된 캠페인", NOW, None, 1000, now=NOW)
        campaigns.suspend_campaign(w.admin, suspended.campaign_id, "사유", now=NOW)
        url, password = "https://example.com/", {"current": PW}

        def change(new):
            change_password(w.adv, password["current"], new)
            password["current"] = new
        cases = {
            ("CampaignCreate", "name"): lambda v: campaigns.create_campaign(w.adv, v, NOW, None, 1000, now=NOW),
            ("CampaignUpdate", "name"): lambda v: campaigns.update_campaign(w.adv, w.campaign.campaign_id, {"name": v}, now=NOW),
            ("AdGroupCreate", "name"): lambda v: campaigns.create_ad_group(w.adv, w.campaign.campaign_id, v, "IMPRESSION", [w.slot.slot_id], now=NOW),
            ("CreativeUpdate", "title"): lambda v: campaigns.update_creative(w.adv, w.creative.creative_id, {"title": v}, now=NOW),
            ("CreativeUpdate", "redirect_url"): lambda v: campaigns.update_creative(w.adv, w.creative.creative_id, {"redirect_url": url + v[len(url):]}, now=NOW),
            ("ReviewRequestCreate", "message"): lambda v: campaigns.create_review_request(w.adv, suspended.campaign_id, v, now=NOW),
            ("ProfileUpdate", "nickname"): lambda v: update_profile(w.adv, nickname=v),
            ("ProfileUpdate", "class_label"): lambda v: update_profile(w.adv, class_label=v),
            ("SignupRequest", "password"): lambda v: register_advertiser(f"pw_{len(v)}", v, "닉네임", "1반"),
            ("PasswordChange", "new_password"): change,
        }
        for (schema, field), call in cases.items():
            limits = self.schema(schema)["properties"][field]
            low, high = limits.get("minLength", 0), limits["maxLength"]
            text = lambda n: (PW * n)[:n] if "password" in field else "가" * n  # 비밀번호 검증기(흔한 비밀번호·숫자만)를 지나는 글자
            with self.subTest(f"{schema}.{field} = {high}자"):
                call(text(high))
            for bad in [high + 1] + ([low - 1] if low >= 1 else []):
                with self.subTest(f"{schema}.{field} = {bad}자"), self.assertRaises((errors.InvalidRequest, ValidationError)):
                    call(text(bad))
        self.assertEqual(len(cases), 10)
