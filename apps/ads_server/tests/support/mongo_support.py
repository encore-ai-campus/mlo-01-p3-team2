"""MongoDB 시험 도우미. 시험마다 무작위 이름의 데이터베이스를 쓰고, **그 이름만** 지운다(남의 데이터베이스를 지우지 않는다)."""
import uuid
from contextlib import contextmanager
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from events import mongo

PREFIX = "ads_events_test_"
UNREACHABLE = {"HOSTS": ["127.0.0.1:1"], "REPLICA_SET": None}  # 아무도 듣지 않는 포트
FAST_FAIL_MS = 300  # 시험에서만: 닿지 않는 저장소를 운영 대기(`mongo.TIMEOUT_MS`, 3초)만큼 기다리지 않는다


@contextmanager
def store_with(**changes):
    """이벤트 저장소 설정을 `changes` 로 바꾼 채 실행한다. 연결은 앞뒤로 버리고(클라이언트는 설정을 처음 한 번만 읽는다), 서버 선택 대기는 짧게 줄인다."""
    with override_settings(EVENT_STORE={**mongo.config(), **changes}), mock.patch.object(mongo, "TIMEOUT_MS", FAST_FAIL_MS):
        mongo.close()
        try:
            yield
        finally:
            mongo.close()


def unreachable_store():
    return store_with(**UNREACHABLE)


class MongoDatabaseMixin:
    """시험용 MongoDB 데이터베이스(무작위 이름)를 시험마다 쓰고 끝나면 지운다. 어떤 TestCase 와도 섞어 쓴다."""

    def setUp(self):
        super().setUp()
        self.db_name = f"{PREFIX}{uuid.uuid4().hex}"
        override = override_settings(EVENT_STORE={**settings.EVENT_STORE, "NAME": self.db_name})
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self.drop_database)
        mongo.close()

    def drop_database(self):
        try:
            assert self.db_name.startswith(PREFIX) and len(self.db_name) >= len(PREFIX) + 32
            mongo.client().drop_database(self.db_name)
        finally:
            mongo.close()


class EventStoreTestCase(MongoDatabaseMixin, SimpleTestCase):
    pass
