"""2-4 반응 수신(inbox): 실제 URL 로 요청하고 응답을 계약(C1)에 대조한다. **2xx = 수신함에 커밋됐다**는 의미를 동시성·커밋 실패까지 확인한다."""
import json
import threading
import time
import uuid
from unittest import mock

from django.db import OperationalError, connection
from django.db.backends.base.base import BaseDatabaseWrapper
from django.test import Client, TestCase, TransactionTestCase, override_settings, tag

from masters import api as masters
from records.models import Reaction
from serving_api.throttle import buckets
from tests.contract_support import Contract, ProviderContractMixin
from tests.factories import NOW, World

BASE = "/api/media/v1"
PATH = "/decisions/{decision_id}/reactions/{reaction_id}"
WHEN = "2026-10-07T03:21:46Z"


class ReactionApiMixin(ProviderContractMixin):
    contract = Contract("serving")

    def setUp(self):
        buckets.reset()
        self.addCleanup(buckets.reset)
        self.w = World()
        self.key = masters.issue_media_key(self.w.admin, self.w.slot.media_id).key
        self.media_id = self.w.slot.media_id
        self.decision_id = uuid.uuid4()  # 이 단계는 결정의 존재를 묻지 않는다(처리 단계가 판정한다)
        self.client = Client()
        patcher = mock.patch("records.services._now", lambda now=None: now or NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def url(self, reaction_id, decision_id=None):
        return f"{BASE}/decisions/{decision_id or self.decision_id}/reactions/{reaction_id}"

    def put(self, reaction_id=None, body=None, key="USE", decision_id=None, raw=None, client=None, content_type="application/json"):
        reaction_id = reaction_id or uuid.uuid4()
        data = raw if raw is not None else json.dumps(body if body is not None else {"type": "IMPRESSION", "occurred_at": WHEN})
        headers = {"HTTP_X_MEDIA_KEY": self.key if key == "USE" else key} if key is not None else {}
        return (client or self.client).put(self.url(reaction_id, decision_id), data=data, content_type=content_type, **headers)

    def get(self, reaction_id, decision_id=None, key="USE"):
        headers = {"HTTP_X_MEDIA_KEY": self.key if key == "USE" else key} if key is not None else {}
        return self.client.get(self.url(reaction_id, decision_id), **headers)


class ReactionApiBase(ReactionApiMixin, TestCase):
    pass


@tag("security")
class PutReactionTests(ReactionApiBase):
    def test_first_report_is_201_received_and_matches_the_contract(self):
        rid = uuid.uuid4()
        response = self.put(rid)
        self.assertEqual(response.status_code, 201)
        self.assertContract(self.contract, PATH, "put", response)
        self.assertEqual(response.json(), {
            "reaction_id": str(rid), "decision_id": str(self.decision_id), "type": "IMPRESSION",
            "occurred_at": "2026-10-07T03:21:46.000Z", "received_at": "2026-10-07T12:00:00.000Z", "status": "RECEIVED", "reason_code": None,
        })
        row = Reaction.objects.get()  # 응답이 나간 시점에 이미 저장돼 있다
        self.assertEqual((row.media_id, row.reaction_id, row.decision_id, row.status), (self.media_id, rid, self.decision_id, "RECEIVED"))

    def test_the_original_body_is_kept_as_received(self):
        self.put(body={"type": "CLICK", "occurred_at": "2026-10-07T03:21:46.5Z"})
        self.assertEqual(Reaction.objects.get().raw, {"type": "CLICK", "occurred_at": "2026-10-07T03:21:46.5Z"})  # 정규화하지 않은 원문

    def test_resending_the_same_report_is_200_with_the_same_resource_and_no_new_row(self):
        rid = uuid.uuid4()
        first = self.put(rid)
        again = self.put(rid)
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertContract(self.contract, PATH, "put", again)
        self.assertEqual(again.json(), first.json())  # received_at 도 처음 값 그대로
        self.assertEqual(Reaction.objects.count(), 1)

    def test_an_equivalent_time_notation_is_the_same_content(self):
        rid = uuid.uuid4()
        self.put(rid, body={"type": "CLICK", "occurred_at": "2026-10-07T03:21:46Z"})
        again = self.put(rid, body={"type": "CLICK", "occurred_at": "2026-10-07T03:21:46.000Z"})
        self.assertEqual(again.status_code, 200)

    def test_same_id_with_different_content_is_409_and_the_first_report_is_untouched(self):
        rid = uuid.uuid4()
        self.put(rid)
        for label, kwargs in {
            "type": dict(body={"type": "CLICK", "occurred_at": WHEN}),
            "time": dict(body={"type": "IMPRESSION", "occurred_at": "2026-10-07T03:21:47Z"}),
            "decision": dict(decision_id=uuid.uuid4()),
        }.items():
            response = self.put(rid, **kwargs)
            self.assertEqual(response.status_code, 409, label)
            self.assertContract(self.contract, PATH, "put", response)
            self.assertEqual(response.json()["code"], "conflict")
        row = Reaction.objects.get()
        self.assertEqual((row.type, row.decision_id, row.raw), ("IMPRESSION", self.decision_id, {"type": "IMPRESSION", "occurred_at": WHEN}))

    def test_another_media_may_use_the_same_reaction_id(self):
        other = World()
        other_key = masters.issue_media_key(other.admin, other.slot.media_id).key
        rid = uuid.uuid4()
        mine, theirs = self.put(rid), self.put(rid, key=other_key, body={"type": "CLICK", "occurred_at": WHEN})
        self.assertEqual((mine.status_code, theirs.status_code), (201, 201))  # 유일성의 범위는 매체 안이다
        self.assertEqual(Reaction.objects.filter(reaction_id=rid).count(), 2)

    def test_an_unknown_decision_is_still_received_nothing_is_revealed(self):
        """없는 결정·남의 결정에 대한 보고도 일단 접수한다(존재 여부를 알리지 않고, 접수한 반응은 지우지 않는다)."""
        other = World()
        other_key = masters.issue_media_key(other.admin, other.slot.media_id).key
        mine = self.post_decision()
        for decision_id in (uuid.uuid4(), mine):
            response = self.put(decision_id=decision_id, key=other_key if decision_id == mine else "USE")
            self.assertEqual((response.status_code, response.json()["status"]), (201, "RECEIVED"), decision_id)

    def post_decision(self):
        response = self.client.post(
            f"{BASE}/decisions", data=json.dumps({"slot_id": str(self.w.slot.slot_id), "subject_id": str(uuid.uuid4())}),
            content_type="application/json", HTTP_X_MEDIA_KEY=self.key,
        )
        return uuid.UUID(response.json()["decision_id"])

    def test_invalid_bodies_and_ids_are_400_and_nothing_is_stored(self):
        cases = {
            "unknown type": dict(body={"type": "VIEW", "occurred_at": WHEN}),
            "lowercase type": dict(body={"type": "click", "occurred_at": WHEN}),
            "no type": dict(body={"occurred_at": WHEN}),
            "no time": dict(body={"type": "CLICK"}),
            "offset time": dict(body={"type": "CLICK", "occurred_at": "2026-10-07T12:21:46+09:00"}),
            "no zone": dict(body={"type": "CLICK", "occurred_at": "2026-10-07T03:21:46"}),
            "lowercase z": dict(body={"type": "CLICK", "occurred_at": "2026-10-07T03:21:46z"}),
            "impossible date": dict(body={"type": "CLICK", "occurred_at": "2026-13-45T03:21:46Z"}),
            "time not string": dict(body={"type": "CLICK", "occurred_at": 1760000000}),
            "extra property": dict(body={"type": "CLICK", "occurred_at": WHEN, "amount": 5}),
            "reaction id not uuid": dict(reaction_id="not-a-uuid"),
            "reaction id without hyphens": dict(reaction_id=uuid.uuid4().hex),
            "decision id not uuid": dict(decision_id="nope"),
            "broken json": dict(raw="{nope"),
        }
        for label, kwargs in cases.items():
            response = self.put(**kwargs)
            self.assertEqual(response.status_code, 400, label)
            self.assertContract(self.contract, PATH, "put", response)
        self.assertEqual(self.put(raw="x", content_type="text/plain").status_code, 415)
        self.assertEqual(Reaction.objects.count(), 0)

    def test_all_body_problems_are_reported_together(self):
        response = self.put(body={"type": "X", "occurred_at": "y", "z": 1})
        self.assertEqual(sorted(e["pointer"] for e in response.json()["errors"]), ["/occurred_at", "/type", "/z"])

    def test_oversize_body_is_413(self):
        response = self.put(raw=json.dumps({"type": "CLICK", "occurred_at": WHEN, "pad": "x" * 20000}))
        self.assertEqual(response.status_code, 413)
        self.assertContract(self.contract, PATH, "put", response)

    def test_auth_comes_first_and_nothing_is_stored_on_failure(self):
        for key in (None, "nope"):
            response = self.put(key=key, raw="{broken")  # 키가 틀리면 본문이 깨졌어도 401
            self.assertEqual(response.status_code, 401)
            self.assertContract(self.contract, PATH, "put", response)
        masters.set_media_active(self.w.admin, self.media_id, False)
        blocked = self.put()
        self.assertEqual(blocked.status_code, 403)
        self.assertContract(self.contract, PATH, "put", blocked)
        self.assertEqual(Reaction.objects.count(), 0)

    def test_unsupported_methods_are_405(self):
        self.assertEqual(self.client.post(self.url(uuid.uuid4()), data="{}", content_type="application/json", HTTP_X_MEDIA_KEY=self.key).status_code, 405)
        self.assertEqual(self.client.delete(self.url(uuid.uuid4()), HTTP_X_MEDIA_KEY=self.key).status_code, 405)

    @override_settings(MEDIA_RATE_LIMITS={"decisions": (50, 50), "reactions": (1, 2), "reads": (50, 50)})
    def test_puts_use_the_reactions_bucket_and_gets_use_the_reads_bucket(self):
        statuses = [self.put().status_code for _ in range(2)]
        blocked = self.put()
        self.assertEqual((statuses, blocked.status_code), ([201, 201], 429))
        self.assertContract(self.contract, PATH, "put", blocked)
        self.assertEqual(self.get(uuid.uuid4()).status_code, 404)  # 조회 버킷은 따로라 막히지 않는다
        self.assertEqual(Reaction.objects.count(), 2)


@tag("security")
class StorageFailureTests(ReactionApiBase):
    def test_insert_failure_is_503_and_a_retry_with_the_same_id_is_then_a_first_receipt(self):
        rid = uuid.uuid4()
        with mock.patch.object(Reaction._default_manager, "create", side_effect=OperationalError("database is locked")):
            response = self.put(rid)
        self.assertEqual(response.status_code, 503)
        self.assertContract(self.contract, PATH, "put", response)
        self.assertEqual(Reaction.objects.count(), 0)
        self.assertEqual(self.put(rid).status_code, 201)  # 매체는 같은 reaction_id 로 재시도한다

    def test_lookup_failure_is_503_too(self):
        with mock.patch("records.services.Reaction.objects.filter", side_effect=OperationalError("disk I/O error")):
            response = self.put()
        self.assertEqual(response.status_code, 503)
        self.assertContract(self.contract, PATH, "put", response)

    def test_a_unique_violation_that_slipped_past_the_precheck_is_resolved_not_a_500(self):
        """다른 연결이 사이에 같은 키를 넣은 경우(MySQL 등)의 안전망: 유일 제약 충돌 뒤 처음 행과 비교해 200/409 로 답한다."""
        rid = uuid.uuid4()
        self.put(rid)
        real_filter, calls = Reaction._default_manager.filter, []

        def blind_first_lookup(*args, **kwargs):
            qs = real_filter(*args, **kwargs)
            if not calls:  # 사전 조회만 '아직 없다'고 본 것처럼 속인다
                calls.append(1)
                return mock.Mock(first=mock.Mock(return_value=None))
            return qs

        with mock.patch.object(Reaction._default_manager, "filter", blind_first_lookup):
            same = self.put(rid)
        self.assertEqual(same.status_code, 200)
        calls.clear()
        with mock.patch.object(Reaction._default_manager, "filter", blind_first_lookup):
            different = self.put(rid, body={"type": "CLICK", "occurred_at": WHEN})
        self.assertEqual(different.status_code, 409)
        self.assertEqual(Reaction.objects.count(), 1)

    def test_a_non_unique_integrity_error_is_not_hidden(self):
        """유일 제약이 아닌 무결성 오류(예: 검사 제약)는 '중복'으로 오인해 2xx 를 내지 않는다."""
        from django.db import IntegrityError

        with mock.patch.object(Reaction._default_manager, "create", side_effect=IntegrityError("CHECK constraint failed")):
            with self.assertRaises(IntegrityError):
                Client(raise_request_exception=True).put(
                    self.url(uuid.uuid4()), data=json.dumps({"type": "CLICK", "occurred_at": WHEN}),
                    content_type="application/json", HTTP_X_MEDIA_KEY=self.key,
                )
        self.assertEqual(Reaction.objects.count(), 0)


@tag("security")
class CommitFailureTests(ReactionApiMixin, TransactionTestCase):
    """실제 커밋이 실패하면 2xx 가 나가지 않고 행도 남지 않는다 — 2xx 는 '커밋됐다'는 뜻이다."""

    def test_a_failed_commit_is_503_with_nothing_stored_and_the_retry_succeeds(self):
        rid = uuid.uuid4()
        real_commit, calls = BaseDatabaseWrapper._commit, []

        def flaky(self_):
            calls.append(1)
            if len(calls) == 1:
                raise OperationalError("disk I/O error")
            return real_commit(self_)

        with mock.patch.object(BaseDatabaseWrapper, "_commit", flaky):
            response = self.put(rid)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "1")
        self.assertContract(self.contract, PATH, "put", response)
        self.assertEqual(Reaction.objects.count(), 0)
        retry = self.put(rid)
        self.assertEqual((retry.status_code, Reaction.objects.count()), (201, 1))


@tag("security")
class ConcurrentReceiptTests(ReactionApiMixin, TransactionTestCase):
    """같은 (매체, reaction_id) 가 동시에 들어와도 행은 하나다. 매체처럼 503/429 는 재시도한다."""

    def send_all(self, jobs):
        """jobs: [(reaction_id, body)]. 각 작업을 스레드 하나로 동시에 시작하고, 2xx/409 가 나올 때까지 재시도한 최종 상태를 모은다."""
        barrier, results = threading.Barrier(len(jobs)), [None] * len(jobs)

        def worker(index, reaction_id, body):
            client = Client()
            try:
                barrier.wait(timeout=10)
                for _ in range(400):
                    response = self.put(reaction_id, body=body, client=client)
                    if response.status_code not in (503, 429):
                        results[index] = (response.status_code, response.json())
                        return
                    time.sleep(0.003)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i, *job)) for i, job in enumerate(jobs)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]
        return results

    @override_settings(MEDIA_RATE_LIMITS={"decisions": (1000, 1000), "reactions": (100000, 100000), "reads": (1000, 1000)})
    def test_identical_concurrent_reports_make_one_row_one_201(self):
        rid = uuid.uuid4()
        body = {"type": "CLICK", "occurred_at": WHEN}
        results = self.send_all([(rid, body)] * 10)
        statuses = sorted(r[0] for r in results)
        self.assertEqual(statuses, [200] * 9 + [201])
        self.assertEqual(len({json.dumps(r[1], sort_keys=True) for r in results}), 1)  # 모두 같은 자원
        self.assertEqual(Reaction.objects.filter(media_id=self.media_id, reaction_id=rid).count(), 1)

    @override_settings(MEDIA_RATE_LIMITS={"decisions": (1000, 1000), "reactions": (100000, 100000), "reads": (1000, 1000)})
    def test_conflicting_concurrent_reports_have_exactly_one_winner(self):
        rid = uuid.uuid4()
        jobs = [(rid, {"type": kind, "occurred_at": WHEN}) for kind in ("IMPRESSION", "CLICK", "CONVERSION") for _ in range(3)]
        results = self.send_all(jobs)
        winners = [r for r in results if r[0] == 201]
        self.assertEqual(len(winners), 1)
        stored = Reaction.objects.get(media_id=self.media_id, reaction_id=rid)
        self.assertEqual(winners[0][1]["type"], stored.type)
        for (status, _body), (_rid, sent) in zip(results, jobs):
            if status != 201:  # 승자가 아니면: 같은 내용은 200(재전송), 다른 내용은 409
                self.assertEqual(status, 200 if sent["type"] == stored.type else 409)
        self.assertEqual(Reaction.objects.filter(reaction_id=rid).count(), 1)

    @override_settings(MEDIA_RATE_LIMITS={"decisions": (1000, 1000), "reactions": (100000, 100000), "reads": (1000, 1000)})
    def test_many_distinct_reports_are_all_stored(self):
        jobs = [(uuid.uuid4(), {"type": "IMPRESSION", "occurred_at": WHEN}) for _ in range(20)]
        results = self.send_all(jobs)
        self.assertEqual([r[0] for r in results], [201] * 20)
        self.assertEqual(Reaction.objects.count(), 20)  # 수신 확인한 건은 전부 저장돼 있다


@tag("security")
class GetReactionTests(ReactionApiBase):
    def test_owner_reads_the_report_and_it_matches_the_contract(self):
        rid = uuid.uuid4()
        created = self.put(rid).json()
        response = self.get(rid)
        self.assertEqual(response.status_code, 200)
        self.assertContract(self.contract, PATH, "get", response)
        self.assertEqual(response.json(), created)

    def test_the_reported_status_follows_the_row(self):
        rid = uuid.uuid4()
        self.put(rid)
        Reaction.objects.filter(reaction_id=rid).update(status="REJECTED", reason_code="duplicate_type")
        body = self.get(rid).json()
        self.assertEqual((body["status"], body["reason_code"]), ("REJECTED", "duplicate_type"))
        self.assertContract(self.contract, PATH, "get", self.get(rid))

    def test_other_media_missing_malformed_and_wrong_decision_are_the_same_404(self):
        rid = uuid.uuid4()
        self.put(rid)
        other = World()
        other_key = masters.issue_media_key(other.admin, other.slot.media_id).key
        details = set()
        for label, response in {
            "other media": self.get(rid, key=other_key),
            "missing": self.get(uuid.uuid4()),
            "wrong decision": self.get(rid, decision_id=uuid.uuid4()),
            "malformed reaction": self.client.get(f"{BASE}/decisions/{self.decision_id}/reactions/nope", HTTP_X_MEDIA_KEY=self.key),
            "no hyphens": self.client.get(f"{BASE}/decisions/{self.decision_id}/reactions/{rid.hex}", HTTP_X_MEDIA_KEY=self.key),
        }.items():
            self.assertEqual(response.status_code, 404, label)
            self.assertContract(self.contract, PATH, "get", response)
            details.add(response.json()["detail"])
        self.assertEqual(len(details), 1)

    def test_auth_applies_to_reads(self):
        rid = uuid.uuid4()
        self.put(rid)
        self.assertEqual(self.get(rid, key=None).status_code, 401)
        masters.set_media_active(self.w.admin, self.media_id, False)
        self.assertEqual(self.get(rid).status_code, 403)
