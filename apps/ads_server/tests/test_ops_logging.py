"""운영 로그(Step 6-3b, 설계 §10 "운영 로그"): 요청 ID 를 로그로 찾을 수 있고, 503 은 원인을 한 줄로 남기며, 시각은 UTC ISO 8601 Z 하나다.

리팩터링 세션 검토 O4·O7: Django 의 4xx·5xx 요약 줄은 요청 ID 미들웨어가 끝난 뒤에 남아 `[-]` 로 찍혔다. 화면·클릭의 503 은 원인을 남기지 않았다.
상시 명령의 상태·장애 줄에는 시각이 없었다.
"""
import io
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from django.core import signing
from django.core.management import call_command
from django.db import OperationalError
from django.test import RequestFactory, SimpleTestCase, TestCase, tag
from django.utils import timezone as app_clock
from pymongo.errors import ServerSelectionTimeoutError

from foundation import errors
from foundation.logging import RequestIdFilter, UtcFormatter
from foundation.middleware import ApiErrorMiddleware
from serving_api import clicks

STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")  # 로그 시각과 명령 줄의 시각이 같은 모양이다
LOCK_TIMEOUT = OperationalError(1205, "Lock wait timeout exceeded; try restarting transaction")


def stamped_lines(text):
    return [line for line in text.splitlines() if line.strip()]


@tag("security")
class RequestIdInDjangoSummaryTests(TestCase):
    def test_the_summary_line_of_a_4xx_carries_the_request_id_of_the_response(self):
        """Django 는 미들웨어가 끝난 뒤(요청 ID 를 되돌린 뒤) 요약 줄을 남긴다. 필터가 기록에 실린 요청에서 ID 를 꺼낸다."""
        with self.assertLogs("django.request", "WARNING") as logs:  # 시험 설정은 이 logger 를 CRITICAL 로 낮춰 두었다
            response = self.client.get(f"/api/media/v1/decisions/{uuid.uuid4()}")  # 키 없음 → 401
        (record,) = logs.records
        RequestIdFilter().filter(record)
        self.assertEqual((response.status_code, record.request_id), (401, response["X-Request-ID"]))

    def test_a_record_without_a_request_keeps_the_placeholder(self):
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        RequestIdFilter().filter(record)
        self.assertEqual(record.request_id, "-")


@tag("security")
class UtcLogTimeTests(SimpleTestCase):
    def configured_formatter(self):
        (formatter,) = {h.formatter for h in logging.getLogger().handlers if isinstance(h.formatter, UtcFormatter)}
        return formatter

    def test_the_configured_log_time_is_utc_iso_8601_with_z_whatever_the_process_time_zone(self):
        formatter = self.configured_formatter()  # 설정(LOGGING)이 이 형식을 실제로 쓴다
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        record.created, record.msecs = datetime(2026, 10, 12, 3, 4, 5, tzinfo=timezone.utc).timestamp(), 678
        saved = os.environ.get("TZ")
        self.addCleanup(lambda: (os.environ.__setitem__("TZ", saved) if saved else os.environ.pop("TZ", None), time.tzset()))
        os.environ["TZ"] = "Asia/Seoul"  # 프로세스 시간대가 KST 여도
        time.tzset()
        self.assertEqual(formatter.formatTime(record), "2026-10-12T03:04:05.678Z")


@tag("security")
class OneLine503Tests(SimpleTestCase):
    def test_a_screen_503_from_a_lock_error_logs_its_cause_in_one_line(self):
        with self.assertLogs("foundation.middleware", "WARNING") as logs:
            response = ApiErrorMiddleware(lambda request: None).process_exception(RequestFactory().get("/advertiser/campaigns/"), LOCK_TIMEOUT)
        (record,) = logs.records
        self.assertEqual(response.status_code, 503)
        self.assertIn("OperationalError 1205", record.getMessage())
        self.assertIn("/advertiser/campaigns/", record.getMessage())
        self.assertIsNone(record.exc_info)  # 트레이스백 없음(장애 중 요청마다 쌓이지 않게)

    def test_a_click_503_logs_its_cause_in_one_line(self):
        decision_id = str(uuid.uuid4())
        token = signing.dumps({"d": decision_id}, salt=clicks.SALT, compress=False)
        with mock.patch("serving_api.clicks.records.observe_click", side_effect=OperationalError(2003, "Can't connect to MySQL server")), \
                self.assertLogs("serving_api.clicks", "WARNING") as logs, self.assertRaises(errors.Unavailable):
            clicks.follow_click(RequestFactory().get(f"/c/{token}"), token)
        (record,) = logs.records
        self.assertIn(f"decision={decision_id} OperationalError 2003", record.getMessage())
        self.assertIsNone(record.exc_info)


@tag("security")
class StampedCommandLinesTests(TestCase):
    def assertStamped(self, lines):
        now = app_clock.now()  # 명령이 찍는 시계와 같은 시계(시계를 앞당겨 도는 scripts/clock_shift_test.py 에서도 맞게)
        for line in lines:
            match = STAMP.match(line)
            self.assertTrue(match, line)
            when = datetime.strptime(match.group(), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            self.assertLess(abs(now - when), timedelta(minutes=1), line)  # 지역 시각이 아니라 UTC 다

    def test_process_reactions_stamps_its_status_and_failure_lines(self):
        out = io.StringIO()
        call_command("process_reactions", "--once", "--retry-stuck", stdout=out)
        self.assertStamped(stamped_lines(out.getvalue()))  # retried-stuck · started · 요약
        self.assertEqual(len(stamped_lines(out.getvalue())), 3)
        err = io.StringIO()
        with mock.patch("records.management.commands.process_reactions.process_pending", side_effect=OperationalError(2003, "down")), \
                mock.patch("records.management.commands.process_reactions.time.sleep", side_effect=KeyboardInterrupt):
            call_command("process_reactions", "--interval", "0.5", stdout=io.StringIO(), stderr=err)
        self.assertStamped(stamped_lines(err.getvalue()))
        self.assertIn("DB 연결 문제", err.getvalue())

    def test_relay_events_stamps_its_status_and_failure_lines_but_not_the_status_query(self):
        out = io.StringIO()
        with mock.patch("events.management.commands.relay_events.relay_batch", return_value=SimpleNamespace(sent=0, duplicate=0)), \
                mock.patch("events.management.commands.relay_events.outbox_status", return_value={"pending": 0, "oldest_age_seconds": None}):
            call_command("relay_events", "--once", stdout=out)
            self.assertStamped(stamped_lines(out.getvalue()))  # started · 요약
            self.assertEqual(len(stamped_lines(out.getvalue())), 2)
            status = io.StringIO()
            call_command("relay_events", "--status", stdout=status)
        self.assertEqual(status.getvalue().strip(), "{'pending': 0, 'oldest_age_seconds': None}")  # 일회성 조회는 그대로(기계가 읽기 쉽게)
        err = io.StringIO()
        with mock.patch("events.management.commands.relay_events.relay_batch", side_effect=ServerSelectionTimeoutError("down")), \
                mock.patch("events.management.commands.relay_events.time.sleep", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            call_command("relay_events", "--interval", "0.5", stdout=io.StringIO(), stderr=err)
        self.assertStamped(stamped_lines(err.getvalue()))
        self.assertIn("이번 주기를 건너뛴다", err.getvalue())
