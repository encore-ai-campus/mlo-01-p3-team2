"""MongoDB 시험 도우미. 시험마다 무작위 이름의 데이터베이스를 쓰고, **그 이름만** 지운다(남의 데이터베이스를 지우지 않는다)."""
import uuid

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from events import mongo

PREFIX = "ads_events_test_"


class EventStoreTestCase(SimpleTestCase):
    def setUp(self):
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
