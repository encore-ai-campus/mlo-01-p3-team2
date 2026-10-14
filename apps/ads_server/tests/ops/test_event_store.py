"""MongoDB 이벤트 저장소 연결 (계획 DB-2): `ad_events` 컬렉션·색인 생성이 멱등이고, 확인 명령이 문제를 잡고, 저장소가 죽어 있어도 앱이 영향을 받지 않는다."""
import datetime
import io
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings, tag
from pymongo.errors import DuplicateKeyError, PyMongoError, WriteError

from events import mongo, store

from tests.support.mongo_support import UNREACHABLE, EventStoreTestCase, store_with, unreachable_store
from tests.support.cases import Cases


def event(**override):
    doc = {"_id": uuid.uuid4(), "event_name": "ad.decision", "schema_version": 1,
           "produced_at": datetime.datetime.now(datetime.timezone.utc), "payload": {"decision_id": str(uuid.uuid4())}}
    return {**doc, **override}


def run(command):
    out = io.StringIO()
    try:
        call_command(command, stdout=out)
        return True, out.getvalue()
    except CommandError as exc:
        return False, out.getvalue() + str(exc)


class EnsureTests(Cases, EventStoreTestCase):
    def case_creates_collection_and_indexes_and_is_idempotent(self):
        first = store.ensure()
        self.assertEqual(len(first), 3)
        self.assertEqual(store.ensure(), [])  # 두 번째는 할 일이 없다
        names = set(mongo.database()[store.COLLECTION].index_information())
        self.assertEqual(names, {"_id_", *store.INDEXES})
        self.assertTrue(all(r.ok for r in store.check()), store.check())

    def case_envelope_is_enforced_and_event_id_is_unique(self):
        store.ensure()
        events = store.collection()
        events.insert_one(event())
        same = event()
        events.insert_one(same)
        with self.assertRaises(DuplicateKeyError):  # `_id = event_id` → 같은 event_id 는 두 번 들어가지 않는다(멱등 저장의 바탕)
            events.insert_one(same)
        for broken in ({"payload": None}, {"event_name": 1}, {"schema_version": "1"}, {"produced_at": "2026-10-09"}):
            with self.assertRaises(WriteError, msg=broken):
                events.insert_one(event(**broken))
        missing = event()
        del missing["payload"]
        with self.assertRaises(WriteError):
            events.insert_one(missing)
        self.assertEqual(events.count_documents({}), 2)

    def case_consumer_queries_use_the_indexes_without_sorting(self):
        """소비자의 읽기 방식: 이벤트 종류별 시각 순 증분, 결정 하나의 이벤트 시각 순. 색인이 그 순서를 그대로 준다(메모리 정렬 없음)."""
        store.ensure()
        for filt in ({"event_name": "ad.decision"}, {"payload.decision_id": "d1"}):
            plan = str(store.collection().find(filt).sort("produced_at", 1).explain()["queryPlanner"]["winningPlan"])
            self.assertIn("IXSCAN", plan, filt)
            self.assertNotIn("SORT", plan, filt)

    def case_event_id_round_trips_as_uuid(self):
        store.ensure()
        doc = event()
        store.collection().insert_one(doc)
        self.assertEqual(store.collection().find_one({"_id": doc["_id"]})["_id"], doc["_id"])
        raw = mongo.database()[store.COLLECTION].find_one({}, {"_id": 1})  # 기본(표준) 표현으로 읽어도 UUID 로 돌아온다
        self.assertIsInstance(raw["_id"], uuid.UUID)

    def case_index_with_other_keys_is_not_dropped_silently(self):
        store.ensure()
        name = next(iter(store.INDEXES))
        store.collection().drop_index(name)
        store.collection().create_index([("something_else", 1)], name=name)
        with self.assertRaises(RuntimeError):
            store.ensure()
        self.assertEqual(store.collection().index_information()[name]["key"], [("something_else", 1)])  # 지우지 않았다

    def case_envelope_validator_drift_is_repaired(self):
        store.ensure()
        mongo.database().command("collMod", store.COLLECTION, validator={})
        self.assertFalse(all(r.ok for r in store.check()))
        self.assertEqual(store.ensure(), [f"컬렉션 {store.COLLECTION} 봉투 검증 갱신"])
        self.assertTrue(all(r.ok for r in store.check()))

    def test_ensure(self):
        self.run_cases()


class CheckTests(Cases, EventStoreTestCase):
    def failed(self):
        return {r.name for r in store.check() if not r.ok}

    def case_missing_collection_missing_index_are_reported(self):
        self.assertEqual(self.failed(), {"컬렉션"})
        store.ensure()
        store.collection().drop_index("decision_produced_at")
        self.assertEqual(self.failed(), {"색인 decision_produced_at"})

    def case_index_with_other_keys_is_reported(self):
        store.ensure()
        store.collection().drop_index("event_name_produced_at")
        store.collection().create_index([("event_name", 1)], name="event_name_produced_at")
        self.assertEqual(self.failed(), {"색인 event_name_produced_at"})

    def case_check_does_not_pollute_the_contract_collection(self):
        store.ensure()
        store.check()
        self.assertEqual(store.collection().count_documents({}), 0)
        self.assertEqual(store.collection(store.PROBE_COLLECTION).count_documents({}), 0)

    def case_commands_report_and_fail(self):
        ok, text = run("check_event_store")
        self.assertFalse(ok)
        self.assertIn("FAIL 컬렉션", text)
        self.assertTrue(run("ensure_event_store")[0])
        ok, text = run("check_event_store")
        self.assertTrue(ok, text)
        self.assertIn("OK   쓰기 권한", text)

    def test_check(self):
        self.run_cases()


@tag("security")
class UnavailableStoreTests(Cases, EventStoreTestCase):
    """저장소가 없거나 틀려도 확인은 예외로 끝나지 않고 FAIL 로 말한다. 비밀번호는 출력에 나오지 않는다."""

    def check_with(self, **changes):
        with store_with(**changes):
            return store.check()

    def case_unreachable_server(self):
        results = self.check_with(**UNREACHABLE)
        self.assertEqual([r.name for r in results], ["연결"])
        self.assertFalse(results[0].ok)

    def case_wrong_password_fails_without_leaking_it(self):
        results = self.check_with(PASSWORD="not-the-password")
        text = " ".join(r.detail for r in results)
        self.assertTrue(any(not r.ok for r in results))
        self.assertNotIn("not-the-password", text)

    def case_wrong_replica_set_name_is_reported(self):
        results = self.check_with(REPLICA_SET="no-such-set")
        self.assertTrue(any(not r.ok for r in results))

    def case_not_configured(self):
        results = self.check_with(HOSTS=[])
        self.assertEqual([(r.name, r.ok) for r in results], [("설정", False)])
        with override_settings(EVENT_STORE=None):
            self.assertEqual([(r.name, r.ok) for r in store.check()], [("설정", False)])

    def case_the_app_does_not_connect_at_all(self):
        """연결은 처음 쓸 때 만든다: 저장소가 죽어 있어도 저장소를 쓰지 않는 요청은 연결을 만들지 않고, 쓰려는 순간에야 실패한다."""
        with unreachable_store():
            self.assertIsNone(mongo._client)
            from django.test import Client
            self.assertEqual(Client().get("/healthz-does-not-exist").status_code, 404)
            self.assertIsNone(mongo._client)  # 요청이 끝나도 연결을 만들지 않았다
            self.assertRaises(PyMongoError, lambda: mongo.client().admin.command("ping"))  # 쓰려는 순간에야 실패한다

    def test_unavailable_store(self):
        self.run_cases()


class ClientOptionsTests(Cases, EventStoreTestCase):
    def options(self, **changes):
        from django.conf import settings
        return mongo.client_options({**settings.EVENT_STORE, **changes})

    def case_acknowledged_by_majority_and_uuid_standard(self):
        o = self.options()
        self.assertEqual((o["w"], o["retryWrites"], o["uuidRepresentation"]), ("majority", True, "standard"))

    def case_credentials_are_options_not_part_of_the_host(self):
        o = self.options(HOSTS=["a:1", "b:2"], USER="u", PASSWORD="pw-secret", REPLICA_SET="rs0")
        self.assertEqual(o["host"], ["a:1", "b:2"])
        self.assertNotIn("pw-secret", " ".join(o["host"]))
        self.assertEqual((o["username"], o["replicaSet"]), ("u", "rs0"))
        self.assertNotIn("username", self.options(USER=None))
        self.assertNotIn("replicaSet", self.options(REPLICA_SET=None))

    def test_client_options(self):
        self.run_cases()
