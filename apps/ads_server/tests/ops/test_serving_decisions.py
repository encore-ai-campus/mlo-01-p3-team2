"""2-3 결정 API: 실제 URL(`/api/media/v1/...`)에 요청하고 **응답을 계약(C1)에 대조**한다. DRD D-1~D-3 의 계약 테스트 포함."""
import json
import uuid
from unittest import mock

from django.db import OperationalError
from django.test import Client, TestCase, TransactionTestCase, override_settings, tag

from masters import api as masters
from records.models import Decision
from tests.support.contract_support import Contract, ProviderContractMixin
from tests.support.factories import NOW, World, media_api

BASE = "/api/media/v1"
SUBJECT = str(uuid.uuid4())


class DecisionApiMixin(ProviderContractMixin):
    contract = Contract("serving")

    def setUp(self):
        self.w, self.key = media_api(self)

    def post(self, body=None, key="USE", raw=None, content_type="application/json", **extra):
        if body is None and raw is None:
            body = {"slot_id": str(self.w.slot.slot_id), "subject_id": SUBJECT}
        data = raw if raw is not None else json.dumps(body)
        headers = dict(extra)
        if key == "USE":
            key = self.key
        if key is not None:
            headers["HTTP_X_MEDIA_KEY"] = key
        return self.client.post(f"{BASE}/decisions", data=data, content_type=content_type, **headers)

    def get(self, path, key="USE"):
        headers = {"HTTP_X_MEDIA_KEY": self.key if key == "USE" else key} if key is not None else {}
        return self.client.get(f"{BASE}{path}", **headers)


class DecisionApiBase(DecisionApiMixin, TestCase):
    pass


@tag("security")
class CreateDecisionTests(DecisionApiBase):
    def test_created_decision_matches_the_contract_and_is_stored_before_the_id_is_returned(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        self.assertContract(self.contract, "/decisions", "post", response)
        body = response.json()
        self.assertEqual(response["Location"], f"{BASE}/decisions/{body['decision_id']}")
        stored = Decision.objects.get(pk=body["decision_id"])  # 응답의 ID 는 이미 저장된 결정이다
        self.assertEqual((str(stored.slot_id), stored.subject_id, stored.decided_at), (body["slot_id"], SUBJECT, NOW))
        self.assertEqual(body["slot_name"], self.w.slot.name)
        self.assertEqual(body["decided_at"], "2026-10-07T12:00:00.000Z")
        self.assertEqual(body["ad"]["creative_id"], str(self.w.creative.creative_id))
        self.assertEqual((body["ad"]["title"], body["ad"]["redirect_url"]), ("제목", "https://example.com/landing"))
        self.assertTrue(body["ad"]["image_url"].endswith(f"/assets/{self.w.creative.image_name}"))

    def test_no_eligible_ad_is_201_with_null_ad_and_is_recorded(self):
        w = World(with_creative=False)
        key = masters.issue_media_key(w.admin, w.slot.media_id).key
        response = self.post({"slot_id": str(w.slot.slot_id), "subject_id": SUBJECT}, key=key)
        self.assertEqual(response.status_code, 201)
        self.assertContract(self.contract, "/decisions", "post", response)
        self.assertIsNone(response.json()["ad"])
        self.assertEqual(Decision.objects.filter(media_id=w.slot.media_id, creative_id__isnull=True).count(), 1)

    def test_inactive_slot_of_an_active_media_is_201_null_ad_and_recorded(self):
        """DRD D-1: 광고가 있어도(후보가 있어도) 꺼진 슬롯은 광고 없음으로 기록한다."""
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        response = self.post()
        self.assertEqual(response.status_code, 201)
        self.assertContract(self.contract, "/decisions", "post", response)
        self.assertIsNone(response.json()["ad"])
        stored = Decision.objects.get(pk=response.json()["decision_id"])
        self.assertEqual((stored.creative_id, stored.candidate_count, stored.trace.get("slot_inactive")), (None, 0, True))

    def test_missing_and_other_media_slots_are_404_and_look_identical(self):
        other = World()
        bodies = set()
        for slot_id in (other.slot.slot_id, uuid.uuid4()):
            response = self.post({"slot_id": str(slot_id), "subject_id": SUBJECT})
            self.assertEqual(response.status_code, 404)
            self.assertContract(self.contract, "/decisions", "post", response)
            bodies.add(response.json()["detail"])
        self.assertEqual(len(bodies), 1)  # 남의 슬롯이 존재하는지 알리지 않는다
        self.assertEqual(Decision.objects.count(), 0)

    def test_inactive_media_is_403_and_nothing_is_recorded(self):
        masters.set_media_active(self.w.admin, self.w.slot.media_id, False)
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(Decision.objects.count(), 0)

    def test_bad_key_is_401_and_nothing_is_recorded(self):
        for key in (None, "nope"):
            response = self.post(key=key)
            self.assertEqual(response.status_code, 401)
            self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(Decision.objects.count(), 0)

    def test_storage_failure_is_503_and_no_decision_id_leaves_the_server(self):
        with mock.patch.object(Decision._default_manager, "create", side_effect=OperationalError("disk I/O error")):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertContract(self.contract, "/decisions", "post", response)
        self.assertNotIn("decision_id", response.json())
        self.assertNotIn("Location", response.headers)
        self.assertEqual(Decision.objects.count(), 0)
        self.assertEqual(self.post().status_code, 201)  # 복구되면 다음 요청은 정상

    def test_a_failure_after_the_insert_still_means_nothing_was_saved(self):
        """응답을 만드는 중(슬롯 이름 조회)에 저장소가 실패하면 503 이고 결정도 남지 않는다 — 커밋 전의 실패는 되돌린다(커밋 응답이 끊긴 503 만 결과를 모른다)."""
        with mock.patch("serving_api.views.masters.slot_names", side_effect=OperationalError("database is locked")):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertContract(self.contract, "/decisions", "post", response)
        self.assertNotIn("Location", response.headers)
        self.assertEqual(Decision.objects.count(), 0)

    def test_each_request_makes_a_new_decision(self):
        first, second = self.post().json(), self.post().json()
        self.assertNotEqual(first["decision_id"], second["decision_id"])
        self.assertEqual(Decision.objects.count(), 2)

    def test_wrong_method_is_405(self):
        self.assertEqual(self.client.get(f"{BASE}/decisions", HTTP_X_MEDIA_KEY=self.key).status_code, 405)


@tag("security")
class CommittedDecisionTests(DecisionApiMixin, TransactionTestCase):
    """savepoint 가 아니라 **실제 커밋**으로: 응답 단계의 실패가 이미 커밋된 결정을 남기지 않는다."""

    def test_a_failure_while_building_the_response_leaves_no_committed_decision(self):
        with mock.patch("serving_api.views.masters.slot_names", side_effect=OperationalError("database is locked")):
            response = self.post()
        self.assertEqual((response.status_code, "Location" in response.headers), (503, False))
        self.assertEqual(Decision.objects.count(), 0)
        ok = self.post()
        self.assertEqual((ok.status_code, Decision.objects.count()), (201, 1))  # 복구되면 정상


@tag("security")
class DecisionContextTests(DecisionApiBase):
    """DRD D-2: 매체 `context` 는 **저장만** 하고, 계약의 크기·깊이·키 제한을 지킨다."""

    def request(self, context):
        return self.post({"slot_id": str(self.w.slot.slot_id), "subject_id": SUBJECT, "context": context})

    def test_context_is_stored_as_given_and_defaults_to_empty(self):
        context = {"scene": "lobby", "tags": ["a", {"b": 1}], "한글": "값"}
        stored = Decision.objects.get(pk=self.request(context).json()["decision_id"])
        self.assertEqual(stored.context, context)
        self.assertEqual(Decision.objects.get(pk=self.post().json()["decision_id"]).context, {})

    def test_context_never_changes_the_selection(self):
        a, b = self.request({"x": 1}).json(), self.request({"y": [1, 2]}).json()
        strip = lambda ad: {k: v for k, v in ad.items() if k != "click_url"}  # 클릭 주소는 결정마다 다른 서명 토큰이다
        self.assertEqual(strip(a["ad"]), strip(b["ad"]))  # 수집만 한다

    def test_limits_are_inclusive_at_the_boundary_and_rejected_just_beyond(self):
        deep_ok = {"a": {"b": {"c": {"d": 1}}}}  # 깊이 4(context 자신이 1)
        deep_bad = {"a": {"b": {"c": {"d": {"e": 1}}}}}
        many_ok = {f"k{i}": 1 for i in range(50)}
        many_bad = {f"k{i}": 1 for i in range(51)}
        for ok in (deep_ok, many_ok, {"s": "x" * 3000}):
            self.assertEqual(self.request(ok).status_code, 201, str(ok)[:40])
        for bad in (deep_bad, many_bad, {"s": "x" * 5000}):
            response = self.request(bad)
            self.assertEqual(response.status_code, 400, str(bad)[:40])
            self.assertEqual(response.json()["code"], "invalid_request")
            self.assertEqual(response.json()["errors"][0]["pointer"], "/context")
            self.assertContract(self.contract, "/decisions", "post", response)

    def test_size_limit_counts_bytes_not_characters(self):
        self.assertEqual(self.request({"s": "한" * 1300}).status_code, 201)  # 3900 바이트 + 구조 < 4096: 글자 수(1300)가 아니라 바이트로 센다
        response = self.request({"s": "한" * 1400})  # 4200 바이트
        self.assertEqual((response.status_code, response.json()["code"]), (400, "invalid_request"))
        self.assertEqual(self.request({"s": "a" * 1400}).status_code, 201)  # 같은 글자 수라도 ASCII 는 1400 바이트라 통과

    def test_direct_identifier_keys_are_forbidden_at_any_depth_and_any_case(self):
        for context in (
            {"username": "kim"}, {"Email": "a@b.c"}, {"a": {"b": {"password": "x"}}}, {"list": [{"nickname": "n"}]},
            {"login_id": 1}, {"password_hash": "h"},
        ):
            response = self.request(context)
            self.assertEqual(response.status_code, 400, context)
            self.assertEqual(response.json()["code"], "forbidden_context_key")
            self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(Decision.objects.count(), 0)
        self.assertEqual(self.request({"username_hint": "ok", "mail": "ok"}).status_code, 201)  # 정확히 같은 키만 막는다

    def test_unpaired_surrogates_are_400_not_500_in_keys_values_and_nested_values(self):
        """JSON 이스케이프(`\\ud800`)는 문법상 유효해 디코더가 받는다. UTF-8 로 저장할 수 없으므로 경계에서 400 으로 거절한다."""
        for label, raw in {
            "high value": '{"s": "\\ud800"}', "low value": '{"s": "\\udfff"}', "key": '{"\\ud800": 1}',
            "nested value": '{"a": [{"b": "x\\udc00y"}]}', "nested key": '{"a": {"\\ud83d": 1}}', "reversed pair": '{"s": "\\ude00\\ud83d"}',
        }.items():
            body = '{"slot_id": "%s", "subject_id": "%s", "context": %s}' % (self.w.slot.slot_id, SUBJECT, raw)
            response = self.post(raw=body)
            self.assertEqual(response.status_code, 400, label)
            self.assertEqual(response.json()["code"], "invalid_request", label)
            self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(Decision.objects.count(), 0)

    def test_valid_surrogate_pairs_and_emoji_are_kept(self):
        body = '{"slot_id": "%s", "subject_id": "%s", "context": {"e": "\\ud83d\\ude00 😀", "😀": 1}}' % (self.w.slot.slot_id, SUBJECT)
        response = self.post(raw=body)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decision.objects.get().context, {"e": "😀 😀", "😀": 1})

    def test_numbers_outside_the_safe_range_are_400_and_nothing_is_stored(self):
        """6-2c(외부 검토 7c4714b P2): 10^400 은 MySQL 저장 오류(3140)가 503 이 되어 같은 요청이 끝없이 재시도됐고, 2^64 를 넘는 정수는 조용히 실수로 바뀌어 저장됐다.
        이제 저장 전에 400 이고, 범위 안의 값은 되읽어도 같다."""
        for raw in ("1" + "0" * 400, "-1" + "0" * 400, "18446744073709551617", "9007199254740992", "[1e300]"):
            body = '{"slot_id": "%s", "subject_id": "%s", "context": {"n": %s}}' % (self.w.slot.slot_id, SUBJECT, raw)
            response = self.post(raw=body)
            self.assertEqual((response.status_code, response.json()["code"]), (400, "invalid_request"), raw[:30])
            self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(Decision.objects.count(), 0)
        context = {"max": 2**53 - 1, "min": -(2**53 - 1), "nested": [{"x": 1.5}, -0.25], "big_as_text": "18446744073709551617"}
        stored = Decision.objects.get(pk=self.request(context).json()["decision_id"])
        self.assertEqual(stored.context, context)

    def test_context_must_be_an_object(self):
        for bad in ([], "x", 1, None, True):
            self.assertEqual(self.request(bad).status_code, 400, bad)


@tag("security")
class DecisionRequestValidationTests(DecisionApiBase):
    def test_invalid_bodies_are_400_with_pointers_and_nothing_is_recorded(self):
        slot = str(self.w.slot.slot_id)
        cases = {
            "no subject": ({"slot_id": slot}, "/subject_id"),
            "no slot": ({"subject_id": SUBJECT}, "/slot_id"),
            "slot not uuid": ({"slot_id": "lobby-banner", "subject_id": SUBJECT}, "/slot_id"),
            "subject not uuid": ({"slot_id": slot, "subject_id": "learner-1"}, "/subject_id"),
            "subject number": ({"slot_id": slot, "subject_id": 5}, "/subject_id"),
            "hex without hyphens": ({"slot_id": slot.replace("-", ""), "subject_id": SUBJECT}, "/slot_id"),
            "extra property": ({"slot_id": slot, "subject_id": SUBJECT, "name": "x"}, "/name"),
        }
        for label, (body, pointer) in cases.items():
            response = self.post(body)
            self.assertEqual(response.status_code, 400, label)
            self.assertIn(pointer, [e["pointer"] for e in response.json()["errors"]], label)
            self.assertContract(self.contract, "/decisions", "post", response)
        self.assertEqual(Decision.objects.count(), 0)

    def test_all_problems_are_reported_together(self):
        response = self.post({"slot_id": "x", "subject_id": "y", "extra": 1})
        self.assertEqual(sorted(e["pointer"] for e in response.json()["errors"]), ["/extra", "/slot_id", "/subject_id"])

    def test_malformed_json_wrong_type_and_oversize(self):
        for label, kwargs, status in (
            ("broken json", dict(raw="{nope"), 400),
            ("not an object", dict(raw="[1]"), 400),
            ("wrong content type", dict(raw="x", content_type="text/plain"), 415),
            ("too large", dict(raw=json.dumps({"slot_id": str(self.w.slot.slot_id), "subject_id": SUBJECT, "context": {"s": "x" * 20000}})), 413),
        ):
            response = self.post(**kwargs)
            self.assertEqual(response.status_code, status, label)
            self.assertContract(self.contract, "/decisions", "post", response)

    def test_uppercase_uuid_is_accepted_like_the_contract_pattern(self):
        response = self.post({"slot_id": str(self.w.slot.slot_id).upper(), "subject_id": SUBJECT.upper()})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decision.objects.get().subject_id, SUBJECT)  # 소문자 표기로 저장


@tag("security")
class GetDecisionTests(DecisionApiBase):
    def test_owner_reads_the_same_decision_and_it_matches_the_contract(self):
        created = self.post().json()
        response = self.get(f"/decisions/{created['decision_id']}")
        self.assertEqual(response.status_code, 200)
        self.assertContract(self.contract, "/decisions/{decision_id}", "get", response)
        self.assertEqual(response.json(), created)
        self.assertEqual(self.get(f"/decisions/{created['decision_id'].upper()}").status_code, 200)

    def test_other_media_missing_and_malformed_ids_are_404_and_look_identical(self):
        created = self.post().json()
        other = World()
        other_key = masters.issue_media_key(other.admin, other.slot.media_id).key
        details = set()
        for path, key in ((f"/decisions/{created['decision_id']}", other_key), (f"/decisions/{uuid.uuid4()}", "USE"), ("/decisions/not-a-uuid", "USE")):
            response = self.get(path, key=key)
            self.assertEqual(response.status_code, 404, path)
            self.assertContract(self.contract, "/decisions/{decision_id}", "get", response)
            details.add(response.json()["detail"])
        self.assertEqual(len(details), 1)

    def test_only_the_contract_uuid_format_is_accepted_on_reads(self):
        """계약 `Uuid` 는 하이픈 포함 36자다. 32자리·중괄호·urn 표기는 같은 결정이어도 '없는 것'과 같은 404 다."""
        created = self.post().json()
        did = created["decision_id"]
        details = {self.get(f"/decisions/{uuid.uuid4()}").json()["detail"]}
        for label, form in {"no hyphens": did.replace("-", ""), "braces": "{" + did + "}", "urn": "urn:uuid:" + did}.items():
            response = self.get(f"/decisions/{form}")
            self.assertEqual(response.status_code, 404, label)
            self.assertContract(self.contract, "/decisions/{decision_id}", "get", response)
            details.add(response.json()["detail"])
        self.assertEqual(len(details), 1)  # 어떤 이유로 못 찾았는지 알리지 않는다
        self.assertEqual(self.get(f"/decisions/{did}").status_code, 200)

    def test_auth_applies_to_reads_too(self):
        created = self.post().json()
        self.assertEqual(self.get(f"/decisions/{created['decision_id']}", key=None).status_code, 401)
        masters.set_media_active(self.w.admin, self.w.slot.media_id, False)
        self.assertEqual(self.get(f"/decisions/{created['decision_id']}").status_code, 403)

    def test_slot_name_is_looked_up_at_response_time_and_not_stored(self):
        """DRD D-3: 이름은 바뀔 수 있는 표시용 정보라 결정에 저장하지 않고 응답을 만들 때 붙인다."""
        self.assertNotIn("slot_name", {f.name for f in Decision._meta.get_fields()})
        created = self.post().json()
        from masters.models import Slot

        Slot.objects.filter(pk=self.w.slot.slot_id).update(name="새 이름")
        self.assertEqual(self.get(f"/decisions/{created['decision_id']}").json()["slot_name"], "새 이름")
        self.assertEqual(self.get(f"/decisions/{created['decision_id']}").json()["slot_id"], created["slot_id"])  # 식별은 ID


@tag("security")
class HealthAndLimitTests(DecisionApiBase):
    def test_health_needs_no_key_touches_no_storage_and_matches_the_contract(self):
        with self.assertNumQueries(0):
            response = Client().get(f"{BASE}/health")
        self.assertEqual((response.status_code, response.json()), (200, {"status": "ok"}))
        self.assertContract(self.contract, "/health", "get", response)
        self.assertEqual(Client().post(f"{BASE}/health").status_code, 405)

    @override_settings(MEDIA_RATE_LIMITS={"decisions": (1, 2), "reactions": (4, 5), "reads": (1, 2)})
    def test_the_real_endpoint_is_rate_limited_with_a_contract_conforming_429(self):
        statuses = [self.post().status_code for _ in range(2)]
        blocked = self.post()
        self.assertEqual(statuses, [201, 201])
        self.assertEqual(blocked.status_code, 429)
        self.assertContract(self.contract, "/decisions", "post", blocked)
        self.assertEqual(Decision.objects.count(), 2)  # 막힌 요청은 결정을 만들지 않는다
