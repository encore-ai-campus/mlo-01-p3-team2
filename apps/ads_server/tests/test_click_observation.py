"""2-8 클릭 관측 `GET /c/{token}`: 실제 URL로 요청해 응답을 계약(C1 v1.1)에 대조한다.

규칙의 원본은 설계 §10 "클릭 출처"와 계약이다: 유효한 토큰은 판정과 무관하게 항상 302(결정에 저장된 `redirect_url`로만), 위조·변조·없는 결정·
광고 없던 결정은 404, 같은 사람의 중복 클릭은 1건, 일괄 슬롯은 `?s=`가 없거나 틀리면 이동만 한다.
"""
import json
import threading
import time
import uuid
from unittest import mock

from django.core import signing
from django.db import OperationalError, connection
from django.test import Client, TestCase, TransactionTestCase, tag

from masters import api as masters
from records.models import Decision, Reaction
from records.services import click_reaction_id
from serving_api.clicks import SALT
from serving_api.throttle import buckets
from tests.contract_support import Contract, ProviderContractMixin
from tests.factories import NOW, SUBJECT, World, png_file

BASE = "http://testserver"
PATH = "/c/{token}"
OTHER = "0197a5c0-0000-7000-8000-0000000000aa"
THIRD = "0197a5c0-0000-7000-8000-0000000000bb"


class ClickBase(ProviderContractMixin, TestCase):
    contract = Contract("serving")

    def setUp(self):
        buckets.reset()
        self.addCleanup(buckets.reset)
        self.w = World()
        self.key = masters.issue_media_key(self.w.admin, self.w.slot.media_id).key
        self.client = Client()
        patcher = mock.patch("records.services._now", lambda now=None: now or NOW)  # 후보 광고의 기간(NOW 기준)이 맞도록 시각을 고정한다
        patcher.start()
        self.addCleanup(patcher.stop)

    def decide(self, slot=None, **body):
        slot = slot or self.w.slot
        body = {"slot_id": str(slot.slot_id), **({"subject_id": SUBJECT} if slot.audience == "individual" else {}), **body}
        response = self.client.post("/api/media/v1/decisions", data=json.dumps(body), content_type="application/json", HTTP_X_MEDIA_KEY=self.key)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def shared_slot(self):
        slot = masters.create_slot(self.w.admin, self.w.slot.media_id, "전광판", "IMPRESSION", 10, 20, 50, "초기", audience="shared")
        group = self.w.api.create_ad_group(self.w.adv, self.w.campaign.campaign_id, "일괄 그룹", "IMPRESSION", [slot.slot_id], bid_amount=40, now=NOW)
        self.w.api.create_creative(self.w.adv, group.ad_group_id, "전광판 광고", "https://example.com/board", png_file((7, 7, 7)), now=NOW)
        return slot

    def follow(self, url, **extra):
        return Client().get(url.removeprefix(BASE), **extra)

    def clicks(self):
        return Reaction.objects.filter(type="CLICK", source="server")


@tag("security")
class ClickUrlTests(ClickBase):
    def test_individual_click_url_is_an_absolute_signed_address_without_a_placeholder(self):
        ad = self.decide()["ad"]
        self.assertRegex(ad["click_url"], rf"^{BASE}/c/[A-Za-z0-9_\-:.]+$")
        self.assertNotIn("{", ad["click_url"])
        self.assertNotIn(SUBJECT, ad["click_url"])  # 사람의 ID가 주소에 평문으로 드러나지 않는다(서명된 토큰 안에만 있다)

    def test_shared_click_url_leaves_the_subject_placeholder_for_the_media(self):
        body = self.decide(self.shared_slot())
        self.assertRegex(body["ad"]["click_url"], rf"^{BASE}/c/[A-Za-z0-9_\-:.]+\?s=\{{subject_id\}}$")
        self.assertEqual(body["audience"], "shared")

    def test_each_decision_gets_its_own_token(self):
        self.assertNotEqual(self.decide()["ad"]["click_url"], self.decide()["ad"]["click_url"])


@tag("security")
class FollowClickTests(ClickBase):
    def test_a_valid_click_redirects_to_the_stored_url_and_matches_the_contract(self):
        body = self.decide()
        response = self.follow(body["ad"]["click_url"])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/landing")
        self.assertEqual((response["Cache-Control"], response["Referrer-Policy"]), ("no-store", "no-referrer"))
        self.assertContract(self.contract, PATH, "get", response)
        self.assertNoCookies(response)

    def test_the_click_is_recorded_as_a_server_observed_inbox_row(self):
        body = self.decide()
        self.follow(body["ad"]["click_url"])
        row = self.clicks().get()
        self.assertEqual((str(row.decision_id), row.media_id, row.subject_id, row.source), (body["decision_id"], self.w.slot.media_id, SUBJECT, "server"))
        self.assertEqual(row.reaction_id, click_reaction_id(body["decision_id"], SUBJECT))
        self.assertEqual(row.occurred_at, row.received_at)  # 시각 = 서버 수신
        self.assertEqual(row.raw, {"type": "CLICK", "source": "server", "subject_id": SUBJECT})

    def test_no_media_key_and_no_login_are_needed_and_a_session_changes_nothing(self):
        url = self.decide()["ad"]["click_url"]
        from tests.factories import make_advertiser

        logged_in = Client()
        logged_in.force_login(make_advertiser())
        for client in (Client(), logged_in):
            response = client.get(url.removeprefix(BASE))
            self.assertEqual(response.status_code, 302)
            self.assertNoCookies(response)

    def test_the_target_never_comes_from_the_request(self):
        url = self.decide()["ad"]["click_url"]
        for extra in ("?url=https://evil.example", "?next=//evil.example", "?redirect_url=https://evil.example&s=x", "?to=javascript:alert(1)"):
            response = self.follow(url + extra if "?" not in url else url + "&" + extra[1:])
            self.assertEqual(response.status_code, 302, extra)
            self.assertEqual(response["Location"], "https://example.com/landing", extra)

    def test_a_click_on_an_already_served_ad_still_redirects_after_the_slot_is_turned_off(self):
        body = self.decide()
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)  # 이미 낸 광고의 클릭은 판정과 무관하게 이동한다
        self.assertEqual(self.follow(body["ad"]["click_url"])["Location"], "https://example.com/landing")

    def test_the_same_person_clicking_twice_leaves_one_row_and_both_redirect(self):
        url = self.decide()["ad"]["click_url"]
        first = self.follow(url)
        row = self.clicks().get()
        with self.assertNoLogs("records.services", "ERROR"):  # 중복은 오류가 아니다(유일 제약 충돌을 정상 경로로 처리한다)
            second = self.follow(url)
        self.assertEqual((first.status_code, second.status_code), (302, 302))
        self.assertEqual(self.clicks().count(), 1)
        self.assertEqual(self.clicks().get().inbox_id, row.inbox_id)  # 처음 것이 그대로다

    def test_head_and_post_are_405_and_record_nothing(self):
        url = self.decide()["ad"]["click_url"].removeprefix(BASE)
        self.assertEqual(Client().head(url).status_code, 405)  # 링크 미리보기·프리페치가 클릭이 되지 않게
        self.assertEqual(Client().post(url).status_code, 405)
        self.assertEqual(self.clicks().count(), 0)


@tag("security")
class InvalidTokenTests(ClickBase):
    def test_forged_tampered_and_foreign_tokens_are_404_and_record_nothing(self):
        body = self.decide()
        token = body["ad"]["click_url"].removeprefix(f"{BASE}/c/")
        payload = {"d": body["decision_id"], "s": SUBJECT}
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        other_payload = signing.dumps({"d": str(uuid.uuid4()), "s": SUBJECT}, salt=SALT)  # 서명은 맞지만 없는 결정
        bad = {
            "tampered signature": tampered,
            "truncated": token[:20],
            "garbage": "not-a-token",
            "other salt": signing.dumps(payload, salt="some.other.salt"),
            "unsigned payload": signing.b64_encode(json.dumps(payload).encode()).decode(),
            "too long": "A" * 513,
            "wrong payload type": signing.dumps(["x"], salt=SALT),
            "missing key": signing.dumps({"d": body["decision_id"]}, salt=SALT),
            "decision not a uuid": signing.dumps({"d": "lobby", "s": None}, salt=SALT),
            "subject not a string": signing.dumps({"d": body["decision_id"], "s": 5}, salt=SALT),
            "unknown decision": other_payload,
        }
        for label, value in bad.items():
            response = Client().get(f"/c/{value}")
            self.assertEqual(response.status_code, 404, label)
            self.assertContract(self.contract, PATH, "get", response)
            self.assertNoCookies(response)
        self.assertEqual(self.clicks().count(), 0)

    def test_an_individual_token_signed_for_another_person_is_404(self):
        body = self.decide()
        forged = signing.dumps({"d": body["decision_id"], "s": OTHER}, salt=SALT)  # 서명은 유효하지만 결정의 사람과 다르다
        self.assertEqual(Client().get(f"/c/{forged}").status_code, 404)
        self.assertEqual(self.clicks().count(), 0)

    def test_a_decision_without_an_ad_is_404(self):
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        no_ad = Decision.objects.get(pk=self.decide()["decision_id"])
        self.assertIsNone(no_ad.creative_id)
        token = signing.dumps({"d": str(no_ad.decision_id), "s": SUBJECT}, salt=SALT)  # 광고가 없으면 click_url 이 응답에 없으므로 직접 서명해 본다
        self.assertEqual(Client().get(f"/c/{token}").status_code, 404)
        self.assertEqual(self.clicks().count(), 0)

    def test_no_ad_response_has_no_click_url(self):
        masters.set_slot_active(self.w.admin, self.w.slot.slot_id, False)
        self.assertIsNone(self.decide()["ad"])


@tag("security")
class SharedSlotClickTests(ClickBase):
    def setUp(self):
        super().setUp()
        self.slot = self.shared_slot()
        self.body = self.decide(self.slot)
        self.template = self.body["ad"]["click_url"]

    def click_as(self, person):
        return self.follow(self.template.replace("{subject_id}", person))

    def test_each_person_is_recorded_once_with_their_own_reaction(self):
        for person in (SUBJECT, OTHER, SUBJECT, THIRD, OTHER):
            self.assertEqual(self.click_as(person).status_code, 302)
        rows = {r.subject_id: r for r in self.clicks()}
        self.assertEqual(sorted(rows), sorted([SUBJECT, OTHER, THIRD]))
        self.assertEqual(len({r.reaction_id for r in rows.values()}), 3)
        self.assertEqual({r.decision_id for r in rows.values()}, {uuid.UUID(self.body["decision_id"])})
        self.assertEqual(rows[OTHER].reaction_id, click_reaction_id(self.body["decision_id"], OTHER))

    def test_a_missing_or_malformed_viewer_redirects_without_recording(self):
        base = self.template.split("?", 1)[0]
        for url in (base, base + "?s=", base + "?s=not-a-uuid", base + "?s={subject_id}", base + f"?s={SUBJECT}x", base + "?s=" + SUBJECT.replace("-", "")):
            response = self.follow(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertEqual(response["Location"], "https://example.com/board", url)
            self.assertContract(self.contract, PATH, "get", response)
        self.assertEqual(self.clicks().count(), 0)

    def test_an_uppercase_viewer_is_the_same_person(self):
        self.click_as(SUBJECT.upper())
        self.click_as(SUBJECT)
        self.assertEqual(list(self.clicks().values_list("subject_id", flat=True)), [SUBJECT])

    def test_an_individual_slot_ignores_the_query_viewer(self):
        url = self.decide()["ad"]["click_url"]
        self.follow(f"{url}?s={OTHER}")
        self.assertEqual(list(self.clicks().values_list("subject_id", flat=True)), [SUBJECT])  # 사람은 결정의 값이다


@tag("security")
class ClickFailureTests(ClickBase):
    def test_a_recording_failure_does_not_stop_the_redirect_and_is_logged(self):
        url = self.decide()["ad"]["click_url"]
        with mock.patch("records.services._record_click", side_effect=RuntimeError("boom")), self.assertLogs("records.services", "ERROR") as logs:
            response = self.follow(url)
        self.assertEqual((response.status_code, response["Location"]), (302, "https://example.com/landing"))
        self.assertIn("클릭 기록 실패", logs.output[0])
        self.assertEqual(self.clicks().count(), 0)
        self.assertEqual(self.follow(url).status_code, 302)  # 복구되면 같은 주소가 다시 기록된다
        self.assertEqual(self.clicks().count(), 1)

    def test_a_failure_before_the_target_is_known_is_503_with_retry_after(self):
        url = self.decide()["ad"]["click_url"]
        with mock.patch("serving_api.clicks.records.observe_click", side_effect=OperationalError("database is locked")):
            response = self.follow(url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "1")
        self.assertContract(self.contract, PATH, "get", response)

    def test_processing_after_the_click_never_breaks_the_redirect(self):
        url = self.decide()["ad"]["click_url"]
        with mock.patch("records.processing.process_reaction", side_effect=RuntimeError("boom")):
            self.assertEqual(self.follow(url).status_code, 302)  # 기록은 됐고 처리는 재처리 몫
        self.assertEqual(self.clicks().get().status, "RECEIVED")


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
        barrier, statuses = threading.Barrier(10), []

        def worker():
            try:
                barrier.wait(timeout=10)
                for _ in range(200):
                    status = Client().get(path).status_code
                    if status != 503:  # 저장소 일시 장애는 사용자가 다시 여는 것과 같다
                        statuses.append(status)
                        return
                    time.sleep(0.003)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]
        self.assertEqual(statuses, [302] * 10)
        self.assertLessEqual(Reaction.objects.filter(source="server").count(), 1)
        Client().get(path)  # 동시 경합에서 기록이 밀렸어도 다음 클릭이 채운다
        self.assertEqual(Reaction.objects.filter(source="server").count(), 1)
