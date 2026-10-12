"""이벤트 저장소 설정이 없을 때(Step 6-3e, 설계 §10 "이벤트 저장소 설정"): 웹은 그대로 뜨고, 중계는 재시도하지 않고 바로 멈춘다.

리팩터링 세션 검토 O5: 상시 중계가 `NotConfigured` 도 일시 장애로 보고 최대 30초 간격으로 영원히 재시도했다 — 출력은 계속 나오지만 outbox 만 쌓였다.
설정이 없는 것은 기다려도 고쳐지지 않는다. 접속 장애(MongoDB 가 잠시 죽음)는 지금처럼 재시도한다(`test_event_relay`).
"""
import io
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings, tag

from events import mongo
from tests.test_event_relay import enqueue_decisions


@tag("security")
@override_settings(EVENT_STORE=None)
class RelayWithoutEventStoreTests(TestCase):
    def setUp(self):
        mongo.close()  # 앞선 시험이 만든 클라이언트를 버린다(클라이언트는 설정을 처음 한 번만 읽는다)
        self.addCleanup(mongo.close)

    def test_the_standing_relay_stops_at_once_instead_of_retrying(self):
        enqueue_decisions(1)
        sleep = mock.Mock(side_effect=AssertionError("설정이 없으면 쉬었다 다시 하지 않는다"))
        with mock.patch("events.management.commands.relay_events.time.sleep", sleep), self.assertRaises(CommandError) as stopped:
            call_command("relay_events", "--interval", "0.5", stdout=io.StringIO(), stderr=io.StringIO())
        self.assertIn("이벤트 저장소 설정이 없어 중계를 멈춥니다", str(stopped.exception))
        self.assertIn("NotConfigured", str(stopped.exception))
        sleep.assert_not_called()

    def test_once_also_stops_with_the_same_message(self):
        enqueue_decisions(1)
        with self.assertRaises(CommandError) as stopped:
            call_command("relay_events", "--once", stdout=io.StringIO())
        self.assertIn("이벤트 저장소 설정이 없어 중계를 멈춥니다", str(stopped.exception))
