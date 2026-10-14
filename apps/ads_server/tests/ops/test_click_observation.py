"""2-8 클릭 관측 `GET /c/{token}`: 실제 URL로 요청해 응답을 계약(C1 v1.1)에 대조한다.

규칙의 원본은 설계 §10 "클릭 출처"와 계약이다: 유효한 토큰은 판정과 무관하게 항상 302(결정에 저장된 `redirect_url`로만), 위조·변조·없는 결정·
광고 없던 결정은 404, 같은 사람의 중복 클릭은 1건, 일괄 슬롯은 `?s=`가 없거나 틀리면 이동만 한다.
"""
import json
import uuid
from unittest import mock

from django.core import signing
from django.db import OperationalError
from django.test import Client, TestCase, TransactionTestCase, override_settings, tag

from masters import api as masters
from records.models import Decision, Reaction
from records.services import click_reaction_id
from serving_api.clicks import SALT
from tests.support.concurrency import run_together
from tests.support.contract_support import Contract, ProviderContractMixin
from tests.support.factories import NOW, SUBJECT, World, media_api
from tests.support.cases import Cases

BASE = "http://testserver"
PATH = "/c/{token}"
DECISION = "0197a5c0-0000-7000-8000-0000000000dd"
OTHER = "0197a5c0-0000-7000-8000-0000000000aa"
THIRD = "0197a5c0-0000-7000-8000-0000000000bb"


class ClickBase(ProviderContractMixin, TestCase):
    contract = Contract("serving")

    def setUp(self):
        self.w, self.key = media_api(self)

    def decide(self, slot=None, **body):
        slot = slot or self.w.slot
        body = {"slot_id": str(slot.slot_id), **({"subject_id": SUBJECT} if slot.audience == "individual" else {}), **body}
        response = self.client.post("/api/media/v1/decisions", data=json.dumps(body), content_type="application/json", HTTP_X_MEDIA_KEY=self.key)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def shared_slot(self):
        return self.w.shared_ad()[0]

    def follow(self, url, **extra):
        return Client().get(url.removeprefix(BASE), **extra)

    def clicks(self):
        return Reaction.objects.filter(type="CLICK", source="server")


@tag("security")
class ClickUrlTests(Cases, ClickBase):
    def case_individual_click_url_is_an_absolute_signed_address_without_a_placeholder(self):
        body = self.decide()
        self.last_decision_id, ad = body["decision_id"], body["ad"]
        self.assertRegex(ad["click_url"], rf"^{BASE}/c/[A-Za-z0-9_\-:.]+$")
        self.assertNotIn("{", ad["click_url"])
        token = ad["click_url"].removeprefix(f"{BASE}/c/")
        self.assertNotIn(SUBJECT, ad["click_url"])
        self.assertEqual(signing.loads(token, salt=SALT), {"d": self.last_decision_id})  # 토큰은 결정 ID뿐 — signing 은 암호화가 아니라 사람의 ID가 URL·로그에 드러나지 않게 싣지 않는다

    def case_shared_click_url_leaves_the_subject_placeholder_for_the_media(self):
        body = self.decide(self.shared_slot())
        self.assertRegex(body["ad"]["click_url"], rf"^{BASE}/c/[A-Za-z0-9_\-:.]+\?s=\{{subject_id\}}$")
        self.assertEqual(body["audience"], "shared")

    def case_each_decision_gets_its_own_token(self):
        self.assertNotEqual(self.decide()["ad"]["click_url"], self.decide()["ad"]["click_url"])

    def test_click_url(self):
        self.run_cases()


@tag("security")
class FollowClickTests(Cases, ClickBase):
    def case_a_valid_click_redirects_to_the_stored_url_and_matches_the_contract(self):
        body = self.decide()
        response = self.follow(body["ad"]["click_url"])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/landing")
        self.assertEqual((response["Cache-Control"], response["Referrer-Policy"]), ("no-store", "no-referrer"))
        self.assertContract(self.contract, PATH, "get", response)
        self.assertNoCookies(response)

    def case_the_click_is_recorded_as_a_server_observed_inbox_row(self):
        body = self.decide()
        self.follow(body["ad"]["click_url"])
        row = self.clicks().get()
        self.assertEqual((str(row.decision_id), row.media_id, row.subject_id, row.source), (body["decision_id"], self.w.slot.media_id, SUBJECT, "server"))
        self.assertEqual(row.reaction_id, click_reaction_id(body["decision_id"], SUBJECT))
        self.assertEqual(row.occurred_at, row.received_at)  # 시각 = 서버 수신
        self.assertEqual(row.raw, {"type": "CLICK", "source": "server", "subject_id": SUBJECT})

    def case_no_media_key_and_no_login_are_needed_and_a_session_changes_nothing(self):
        url = self.decide()["ad"]["click_url"]
        from tests.support.factories import make_advertiser

        logged_in = Client()
        logged_in.force_login(make_advertiser())
        for client in (Client(), logged_in):
            response = client.get(url.removeprefix(BASE))
            self.assertEqual(response.status_code, 302)
            self.assertNoCookies(response)

    def case_the_target_never_comes_from_the_request(self):
        url = self.decide()["ad"]["click_url"]
        for extra in ("?url=https://evil.example", "?next=//evil.example", "?redirect_url=https://evil.example&s=x", "?to=javascript:alert(1)"):
            response = self.follow(url + extra if "?" not in url else url + "&" + extra[1:])
            self.assertEqual(response.status_code, 302, extra)
            self.assertEqual(response["Location"], "https://example.com/landing", extra)

    def case_a_click_on_an_already_served_ad_still_redirects_after_the_slot_is_turned_off(self):
        body = self.decide()
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)  # 이미 낸 광고의 클릭은 판정과 무관하게 이동한다
        self.assertEqual(self.follow(body["ad"]["click_url"])["Location"], "https://example.com/landing")

    def case_the_same_person_clicking_twice_leaves_one_row_and_both_redirect(self):
        url = self.decide()["ad"]["click_url"]
        first = self.follow(url)
        row = self.clicks().get()
        with self.assertNoLogs("records.services", "ERROR"):  # 중복은 오류가 아니다(유일 제약 충돌을 정상 경로로 처리한다)
            second = self.follow(url)
        self.assertEqual((first.status_code, second.status_code), (302, 302))
        self.assertEqual(self.clicks().count(), 1)
        self.assertEqual(self.clicks().get().inbox_id, row.inbox_id)  # 처음 것이 그대로다

    def case_head_and_post_are_405_and_record_nothing(self):
        url = self.decide()["ad"]["click_url"].removeprefix(BASE)
        self.assertEqual(Client().head(url).status_code, 405)  # 링크 미리보기·프리페치가 클릭이 되지 않게
        self.assertEqual(Client().post(url).status_code, 405)
        self.assertEqual(self.clicks().count(), 0)

    def test_follow_click(self):
        self.run_cases()


@tag("security")
class MediaCannotPreemptServerClicksTests(Cases, ClickBase):
    """매체가 서버 관측 클릭의 `reaction_id` 를 미리 접수시켜 그 클릭을 지울 수 없다(검토 2-8 #1).

    서버 클릭과 매체 반응은 같은 `UNIQUE(media_id, reaction_id)` 를 쓴다. 클릭의 ID가 소스에 있는 공개 값(이름공간)으로 계산되면
    매체가 같은 ID로 아무 반응이나 먼저 보낼 수 있고, 그러면 진짜 클릭이 "중복"으로 조용히 버려진다.
    """

    OLD_NAMESPACE = uuid.UUID("6f1d0a52-3c7e-5b0a-9a5e-2d1c4b7e8f90")  # 2-8 최초 구현의 이름공간(소스에 공개되어 있던 값)

    def put(self, decision_id, reaction_id):
        return Client().put(
            f"/api/media/v1/decisions/{decision_id}/reactions/{reaction_id}", data=json.dumps({"type": "IMPRESSION", "occurred_at": "2026-10-07T12:00:00Z"}),
            content_type="application/json", HTTP_X_MEDIA_KEY=self.key,
        )

    def case_a_media_report_with_the_publicly_computable_id_does_not_swallow_the_real_click(self):
        body = self.decide()
        guessed = uuid.uuid5(self.OLD_NAMESPACE, f"{body['decision_id']}/{SUBJECT}")  # 소스를 읽은 매체가 계산할 수 있는 값
        self.assertEqual(self.put(body["decision_id"], guessed).status_code, 201)
        self.assertEqual(self.follow(body["ad"]["click_url"]).status_code, 302)
        self.assertEqual(self.clicks().count(), 1)  # 서버가 관측한 클릭은 그대로 기록된다
        self.assertEqual(Reaction.objects.filter(reaction_id=guessed).get().source, "media")  # 매체의 반응은 따로 남아 있다

    def case_the_click_id_depends_on_the_server_secret(self):
        ids = {click_reaction_id(DECISION, SUBJECT)}
        with override_settings(SECRET_KEY="another-secret-" + "x" * 40):
            ids.add(click_reaction_id(DECISION, SUBJECT))
        self.assertEqual(len(ids), 2)  # 비밀 없이는 계산할 수 없다
        self.assertEqual(click_reaction_id(DECISION, SUBJECT), click_reaction_id(DECISION, SUBJECT))  # 같은 (결정, 사람)은 같은 ID
        self.assertNotEqual(click_reaction_id(DECISION, SUBJECT), click_reaction_id(DECISION, OTHER))

    def case_an_id_collision_with_a_media_row_is_an_error_not_a_silent_duplicate(self):
        """안전망: 어떤 이유로든 같은 ID의 *매체* 행이 있으면 중복 클릭으로 오인해 버리지 않고 오류로 기록한다."""
        body = self.decide()
        fixed = uuid.uuid4()
        self.assertEqual(self.put(body["decision_id"], fixed).status_code, 201)
        with mock.patch("records.services.click_reaction_id", return_value=fixed), self.assertLogs("records.services", "ERROR"):
            response = self.follow(body["ad"]["click_url"])
        self.assertEqual(response.status_code, 302)  # 이동은 한다
        self.assertEqual(self.clicks().count(), 0)

    def test_media_cannot_preempt_server_clicks(self):
        self.run_cases()


@tag("security")
class InvalidTokenTests(Cases, ClickBase):
    def case_forged_tampered_and_foreign_tokens_are_404_and_record_nothing(self):
        body = self.decide()
        token = body["ad"]["click_url"].removeprefix(f"{BASE}/c/")
        payload = {"d": body["decision_id"]}
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        other_payload = signing.dumps({"d": str(uuid.uuid4())}, salt=SALT)  # 서명은 맞지만 없는 결정
        bad = {
            "tampered signature": tampered,
            "truncated": token[:20],
            "garbage": "not-a-token",
            "other salt": signing.dumps(payload, salt="some.other.salt"),
            "unsigned payload": signing.b64_encode(json.dumps(payload).encode()).decode(),
            "too long": "A" * 513,
            "wrong payload type": signing.dumps(["x"], salt=SALT),
            "missing key": signing.dumps({"s": body["decision_id"]}, salt=SALT),
            "decision not a uuid": signing.dumps({"d": "lobby"}, salt=SALT),
            "decision not a string": signing.dumps({"d": 5}, salt=SALT),
            "unknown decision": other_payload,
        }
        for label, value in bad.items():
            response = Client().get(f"/c/{value}")
            self.assertEqual(response.status_code, 404, label)
            self.assertContract(self.contract, PATH, "get", response)
            self.assertNoCookies(response)
        self.assertEqual(self.clicks().count(), 0)

    def case_a_decision_without_an_ad_is_404(self):
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        no_ad = Decision.objects.get(pk=self.decide()["decision_id"])
        self.assertIsNone(no_ad.creative_id)
        token = signing.dumps({"d": str(no_ad.decision_id)}, salt=SALT)  # 광고가 없으면 click_url 이 응답에 없으므로 직접 서명해 본다
        self.assertEqual(Client().get(f"/c/{token}").status_code, 404)
        self.assertEqual(self.clicks().count(), 0)

    def case_no_ad_response_has_no_click_url(self):
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        self.assertIsNone(self.decide()["ad"])

    def test_invalid_token(self):
        self.run_cases()


@tag("security")
class SharedSlotClickTests(Cases, ClickBase):
    def setUp(self):
        super().setUp()
        self.slot = self.shared_slot()
        self.body = self.decide(self.slot)
        self.template = self.body["ad"]["click_url"]

    def click_as(self, person):
        return self.follow(self.template.replace("{subject_id}", person))

    def case_each_person_is_recorded_once_with_their_own_reaction(self):
        for person in (SUBJECT, OTHER, SUBJECT, THIRD, OTHER):
            self.assertEqual(self.click_as(person).status_code, 302)
        rows = {r.subject_id: r for r in self.clicks()}
        self.assertEqual(sorted(rows), sorted([SUBJECT, OTHER, THIRD]))
        self.assertEqual(len({r.reaction_id for r in rows.values()}), 3)
        self.assertEqual({r.decision_id for r in rows.values()}, {uuid.UUID(self.body["decision_id"])})
        self.assertEqual(rows[OTHER].reaction_id, click_reaction_id(self.body["decision_id"], OTHER))

    def case_a_missing_or_malformed_viewer_redirects_without_recording(self):
        base = self.template.split("?", 1)[0]
        for url in (base, base + "?s=", base + "?s=not-a-uuid", base + "?s={subject_id}", base + f"?s={SUBJECT}x", base + "?s=" + SUBJECT.replace("-", "")):
            response = self.follow(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertEqual(response["Location"], "https://example.com/board", url)
            self.assertContract(self.contract, PATH, "get", response)
        self.assertEqual(self.clicks().count(), 0)

    def case_an_uppercase_viewer_is_the_same_person(self):
        self.click_as(SUBJECT.upper())
        self.click_as(SUBJECT)
        self.assertEqual(list(self.clicks().values_list("subject_id", flat=True)), [SUBJECT])

    def case_an_individual_slot_ignores_the_query_viewer(self):
        url = self.decide()["ad"]["click_url"]
        self.follow(f"{url}?s={OTHER}")
        self.assertEqual(list(self.clicks().values_list("subject_id", flat=True)), [SUBJECT])  # 사람은 결정의 값이다

    def test_shared_slot_click(self):
        self.run_cases()


@tag("security")
class ClickFailureTests(Cases, ClickBase):
    def case_a_recording_failure_does_not_stop_the_redirect_and_is_logged(self):
        url = self.decide()["ad"]["click_url"]
        with mock.patch("records.services._record_click", side_effect=RuntimeError("boom")), self.assertLogs("records.services", "ERROR") as logs:
            response = self.follow(url)
        self.assertEqual((response.status_code, response["Location"]), (302, "https://example.com/landing"))
        self.assertIn("클릭 기록 실패", logs.output[0])
        self.assertEqual(self.clicks().count(), 0)
        self.assertEqual(self.follow(url).status_code, 302)  # 복구되면 같은 주소가 다시 기록된다
        self.assertEqual(self.clicks().count(), 1)

    def case_a_failure_before_the_target_is_known_is_503_with_retry_after(self):
        url = self.decide()["ad"]["click_url"]
        with mock.patch("serving_api.clicks.records.observe_click", side_effect=OperationalError("database is locked")):
            response = self.follow(url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "1")
        self.assertContract(self.contract, PATH, "get", response)

    def case_processing_after_the_click_never_breaks_the_redirect(self):
        url = self.decide()["ad"]["click_url"]
        with mock.patch("records.processing.process_reaction", side_effect=RuntimeError("boom")):
            self.assertEqual(self.follow(url).status_code, 302)  # 기록은 됐고 처리는 재처리 몫
        self.assertEqual(self.clicks().get().status, "RECEIVED")

    def test_click_failure(self):
        self.run_cases()


@tag("security")
class ConcurrentClickTests(ProviderContractMixin, TransactionTestCase):
    """같은 사람의 클릭이 동시에 여러 번 와도 행은 하나를 넘지 않고 500 이 없다(유일 제약이 한쪽만 통과시킨다)."""

    contract = Contract("serving")

    def test_simultaneous_clicks_of_one_person_leave_at_most_one_row_and_never_fail(self):
        w = World()
        key = masters.issue_media_key(w.admin, w.slot.media_id).key
        with mock.patch("records.services._now", lambda now=None: now or NOW):
            body = Client().post("/api/media/v1/decisions", data=json.dumps({"slot_id": str(w.slot.slot_id), "subject_id": SUBJECT}),
                                 content_type="application/json", HTTP_X_MEDIA_KEY=key).json()
        path = body["ad"]["click_url"].removeprefix(BASE)
        statuses, errors = run_together([lambda: Client().get(path).status_code] * 10, timeout=60)  # 재시도하지 않는다: 정상 경쟁에서 503 이 나면 안 된다
        self.assertEqual((statuses, errors), ([302] * 10, []))
        self.assertLessEqual(Reaction.objects.filter(source="server").count(), 1)
        Client().get(path)  # 동시 경합에서 기록이 밀렸어도 다음 클릭이 채운다
        self.assertEqual(Reaction.objects.filter(source="server").count(), 1)
