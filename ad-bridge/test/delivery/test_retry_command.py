"""재전송 명령의 반복·종료·실패 처리를 HTTP·DB·대기 없이 확인한다."""

from io import StringIO
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import Mock, patch
from uuid import UUID

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import SimpleTestCase

from ad_bridge.management.commands import dispatch_ad_reactions as command
from ad_bridge.delivery.sender import ImpressionReport
from ad_bridge.impressions.store import StoredImpression

COUNTS = {"attempted": 3, "acknowledged": 1, "unconfirmed": 1, "blocked": 1}
SECRET = "unit-test-command-private-key"
REACTION_ID = "44556677-1234-4234-8234-123456789abc"
OWNER_ID = "11223344-1234-4234-8234-123456789abc"
AD_SUBJECT_ID = "d8d3d672-5458-ddcc-c90c-a7844b3aa51a"


class RetryCommandTests(SimpleTestCase):
    def setUp(self):
        self.out, self.err = StringIO(), StringIO()
        self.stop = Event()
        self.client = Mock()
        self.config = Mock()
        self.policy = Mock()
        patches = {
            "config": patch.object(command.AdsConfig, "from_env", return_value=self.config),
            "client_factory": patch.object(command, "AdsClient", return_value=self.client),
            "policy_factory": patch.object(command, "RetryPolicy", return_value=self.policy),
            "dispatch": patch.object(command, "dispatch_due_impressions", return_value=COUNTS),
            "connections": patch.object(command, "close_old_connections"),
            "event": patch.object(command, "Event", return_value=self.stop),
            "wait": patch.object(self.stop, "wait", return_value=False),
            "signal": patch.object(command.signal, "signal"),
            "getsignal": patch.object(command.signal, "getsignal", return_value="previous-handler"),
        }
        for name, item in patches.items():
            setattr(self, name, item.start())
            self.addCleanup(item.stop)

    def run_command(self, *args, **kwargs):
        # 명령 객체를 직접 호출하지 않아 실제 Django 앱의 명령 발견 경로도 검사한다.
        return call_command("dispatch_ad_reactions", *args, stdout=self.out, stderr=self.err, **kwargs)

    def prepare_recovery(self):
        self.recovery_now = datetime(2026, 10, 12, tzinfo=timezone.utc)
        self.policy.lease_seconds = 60
        self.recovery_record = StoredImpression(
            decision_id="22334455-1234-4234-8234-123456789abc",
            reaction_id=REACTION_ID, subject_id=AD_SUBJECT_ID,
            occurred_at="2026-10-11T12:00:00.123000Z", delivery_state="SENDING",
            attempts=3, lease_token="55667788-1234-4234-8234-123456789abc",
            lease_expires_at=self.recovery_now + timedelta(seconds=60),
            last_http_status=401, last_error="ads_http_error", request_id=SECRET,
        )
        self.recovery_outcome = ImpressionReport(replace(self.recovery_record,
            delivery_state="ACKNOWLEDGED", status="RECEIVED", reason_code=SECRET,
            lease_token=None, lease_expires_at=None, last_http_status=None), True)
        patches = {
            "recovery_claim": patch.object(command.impression_store, "claim_blocked_401_impression",
                return_value=self.recovery_record),
            "recovery_send": patch.object(command, "send_once", return_value=self.recovery_outcome),
            "recovery_clock": patch.object(command, "utc_now", return_value=self.recovery_now),
        }
        for name, item in patches.items():
            setattr(self, name, item.start())
            self.addCleanup(item.stop)

    def test_recovery_sends_only_the_explicit_record_and_exits(self):
        self.prepare_recovery()
        self.run_command("--recover-401", REACTION_ID.upper())
        self.recovery_claim.assert_called_once_with(
            UUID(REACTION_ID), now=self.recovery_now, lease_seconds=60,
        )
        self.recovery_send.assert_called_once_with(client=self.client, store=command.impression_store,
            record=self.recovery_record, policy=self.policy, now=self.recovery_clock)
        self.dispatch.assert_not_called()
        self.wait.assert_not_called()
        self.assertEqual(self.connections.call_count, 2)
        self.signal.assert_called_with(command.signal.SIGINT, "previous-handler")
        self.assertIn("401 복구 요청", self.out.getvalue())
        self.assertIn("ACKNOWLEDGED", self.out.getvalue())
        for private in (SECRET, OWNER_ID, AD_SUBJECT_ID):
            self.assertNotIn(private, self.out.getvalue() + self.err.getvalue())

    def test_recovery_invalid_uuid_is_redacted_before_config_or_claim(self):
        self.prepare_recovery()
        for value in (SECRET, "", 123, True):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(CommandError) as caught:
                self.run_command(recover_401=value)
            self.assertNotIn(SECRET, str(caught.exception))
        self.config.assert_not_called()
        self.recovery_claim.assert_not_called()
        self.recovery_send.assert_not_called()
        self.dispatch.assert_not_called()
        self.connections.assert_not_called()

    def test_recovery_invalid_config_does_not_claim_or_send(self):
        self.prepare_recovery()
        self.config.side_effect = ValueError(SECRET)
        with self.assertRaises(CommandError) as caught:
            self.run_command("--recover-401", REACTION_ID)
        self.assertNotIn(SECRET, str(caught.exception))
        self.recovery_claim.assert_not_called()
        self.recovery_send.assert_not_called()
        self.dispatch.assert_not_called()
        self.connections.assert_not_called()

    def test_recovery_excluded_record_fails_without_sending(self):
        self.prepare_recovery()
        self.recovery_claim.return_value = None
        with self.assertRaises(CommandError):
            self.run_command("--recover-401", REACTION_ID)
        self.recovery_claim.assert_called_once()
        self.recovery_send.assert_not_called()
        self.dispatch.assert_not_called()
        self.wait.assert_not_called()
        self.assertIn("401 복구 제외", self.out.getvalue())
        self.assertEqual(self.connections.call_count, 2)

    def test_recovery_without_receipt_fails_after_one_send(self):
        self.prepare_recovery()
        for state, http_status in (("BLOCKED", 401), ("UNCONFIRMED", 503)):
            with self.subTest(state=state):
                self.recovery_send.reset_mock()
                self.recovery_send.return_value = ImpressionReport(replace(self.recovery_record,
                    delivery_state=state, last_http_status=http_status, reason_code=SECRET),
                    True, error=SECRET, upstream_status=http_status)
                with self.assertRaises(CommandError) as caught:
                    self.run_command("--recover-401", REACTION_ID)
                self.recovery_send.assert_called_once()
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertIn(f"마지막 HTTP 오류 {http_status}", self.out.getvalue())
        self.dispatch.assert_not_called()
        self.wait.assert_not_called()
        self.assertNotIn(SECRET, self.out.getvalue() + self.err.getvalue())

    def test_recovery_receipt_without_final_judgment_is_success(self):
        self.prepare_recovery()
        self.recovery_send.return_value = ImpressionReport(replace(self.recovery_outcome.record,
            status=None, reason_code=None), True, error="ads_invalid_response")
        # 최종 판정이나 본문 해석 실패와 별개로 HTTP 접수 확인은 성공으로 처리한다.
        self.run_command("--recover-401", REACTION_ID)
        self.recovery_send.assert_called_once()
        self.assertIn("ACKNOWLEDGED", self.out.getvalue())
        self.dispatch.assert_not_called()

    def test_recovery_database_failures_are_redacted_and_do_not_repeat(self):
        self.prepare_recovery()
        for failure_stage in ("claim", "send"):
            with self.subTest(failure_stage=failure_stage):
                self.recovery_claim.side_effect = DatabaseError(SECRET) if failure_stage == "claim" else None
                self.recovery_send.side_effect = DatabaseError(SECRET) if failure_stage == "send" else None
                self.recovery_send.reset_mock()
                with self.assertRaises(CommandError) as caught:
                    self.run_command("--recover-401", REACTION_ID)
                self.assertNotIn(SECRET, str(caught.exception))
                if failure_stage == "claim":
                    self.recovery_send.assert_not_called()
                else:
                    self.recovery_send.assert_called_once()
        self.dispatch.assert_not_called()
        self.wait.assert_not_called()
        self.assertNotIn(SECRET, self.out.getvalue() + self.err.getvalue())

    def test_recovery_record_validation_failure_is_redacted(self):
        self.prepare_recovery()
        self.recovery_claim.side_effect = ValueError(SECRET)
        with self.assertRaises(CommandError) as caught:
            self.run_command("--recover-401", REACTION_ID)
        self.assertNotIn(SECRET, str(caught.exception))
        self.recovery_send.assert_not_called()
        self.dispatch.assert_not_called()

    def test_recovery_first_ctrl_c_finishes_request_and_restores_handler(self):
        self.prepare_recovery()

        def send(**kwargs):
            handler = self.signal.call_args_list[0].args[1]
            handler(command.signal.SIGINT, None)
            return self.recovery_outcome

        self.recovery_send.side_effect = send
        self.run_command("--recover-401", REACTION_ID)
        self.recovery_send.assert_called_once()
        self.assertTrue(self.stop.is_set())
        self.assertIn("401 복구 결과", self.out.getvalue())
        self.signal.assert_called_with(command.signal.SIGINT, "previous-handler")
        self.assertEqual(self.connections.call_count, 2)

    def test_recovery_keyboard_interrupt_still_restores_handler_and_connections(self):
        self.prepare_recovery()
        self.recovery_send.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_command("--recover-401", REACTION_ID)
        self.signal.assert_called_with(command.signal.SIGINT, "previous-handler")
        self.assertEqual(self.connections.call_count, 2)
        self.dispatch.assert_not_called()

    def test_recovery_stop_before_start_does_not_claim_or_send(self):
        self.prepare_recovery()
        self.stop.set()
        with self.assertRaises(CommandError):
            self.run_command("--recover-401", REACTION_ID)
        self.recovery_claim.assert_not_called()
        self.recovery_send.assert_not_called()
        self.dispatch.assert_not_called()

    def test_recovery_cli_returns_failure_code_when_receipt_is_not_confirmed(self):
        self.prepare_recovery()
        self.recovery_send.return_value = ImpressionReport(replace(self.recovery_record,
            delivery_state="BLOCKED", last_http_status=401), True, "ads_http_error", 401)
        # 실제 명령 진입점도 CommandError를 실패 종료 코드로 바꾸는지 확인한다.
        entrypoint = command.Command(stdout=self.out, stderr=self.err)
        with self.assertRaises(SystemExit) as caught:
            entrypoint.run_from_argv(["manage.py", "dispatch_ad_reactions", "--recover-401", REACTION_ID])
        self.assertEqual(caught.exception.code, 1)
        self.assertNotIn(SECRET, self.out.getvalue() + self.err.getvalue())
        self.recovery_send.assert_called_once()
        self.dispatch.assert_not_called()

    def test_recovery_cli_completes_successfully_when_receipt_is_confirmed(self):
        self.prepare_recovery()
        entrypoint = command.Command(stdout=self.out, stderr=self.err)
        entrypoint.run_from_argv(["manage.py", "dispatch_ad_reactions", "--recover-401", REACTION_ID])
        self.recovery_send.assert_called_once()
        self.dispatch.assert_not_called()
        self.assertEqual(self.err.getvalue(), "")
        self.assertIn("ACKNOWLEDGED", self.out.getvalue())

    def test_once_dispatches_exactly_one_batch_with_default_options(self):
        self.run_command("--once")
        self.config.assert_called_once_with()
        self.client_factory.assert_called_once_with(self.config.return_value)
        self.policy_factory.assert_called_once_with()
        self.dispatch.assert_called_once_with(
            client=self.client, store=command.impression_store, limit=100,
            policy=self.policy, should_stop=self.stop.is_set,
        )
        self.assertEqual(self.connections.call_count, 2)
        self.wait.assert_not_called()
        self.assertIn("시도 3건", self.out.getvalue())
        self.assertIn("접수 1건", self.out.getvalue())
        self.assertEqual(self.err.getvalue(), "")

    def test_custom_batch_and_interval_are_used(self):
        def dispatch(**kwargs):
            if self.dispatch.call_count == 2:
                self.stop.set()
            return COUNTS
        self.dispatch.side_effect = dispatch
        self.run_command("--batch-size", "7", "--poll-interval", "0.25")
        self.assertEqual(self.dispatch.call_count, 2)
        self.assertTrue(all(call.kwargs["limit"] == 7 for call in self.dispatch.call_args_list))
        self.wait.assert_called_once_with(0.25)
        self.config.assert_called_once_with()
        self.assertEqual(self.connections.call_count, 3)

    def test_invalid_options_fail_before_config_or_dispatch(self):
        cases = ({"batch_size": 0}, {"batch_size": -1}, {"batch_size": True},
                 {"batch_size": 1.5}, {"poll_interval": 0}, {"poll_interval": -1},
                 {"poll_interval": float("nan")}, {"poll_interval": float("inf")},
                 {"poll_interval": True})
        for options in cases:
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.run_command(once=True, **options)
        self.config.assert_not_called()
        self.dispatch.assert_not_called()
        self.connections.assert_not_called()

    def test_invalid_config_fails_without_claiming_or_exposing_secret(self):
        self.config.side_effect = ValueError(SECRET)
        with self.assertRaises(CommandError) as caught:
            self.run_command("--once")
        self.assertNotIn(SECRET, str(caught.exception))
        self.dispatch.assert_not_called()
        self.connections.assert_not_called()
        self.client_factory.assert_not_called()

    def test_default_loop_uses_stop_callback_between_batches(self):
        def dispatch(**kwargs):
            self.assertFalse(kwargs["should_stop"]())
            if self.dispatch.call_count == 2:
                self.stop.set()
                self.assertTrue(kwargs["should_stop"]())
            return COUNTS
        self.dispatch.side_effect = dispatch
        self.run_command()
        self.assertEqual(self.dispatch.call_count, 2)
        self.wait.assert_called_once_with(1.0)
        self.signal.assert_called_with(command.signal.SIGINT, "previous-handler")

    def test_first_ctrl_c_finishes_batch_then_stops_and_restores_handler(self):
        def dispatch(**kwargs):
            handler = self.signal.call_args_list[0].args[1]
            handler(command.signal.SIGINT, None)
            self.assertTrue(kwargs["should_stop"]())
            return COUNTS
        self.dispatch.side_effect = dispatch
        self.run_command()
        self.dispatch.assert_called_once()
        self.wait.assert_not_called()
        self.signal.assert_called_with(command.signal.SIGINT, "previous-handler")
        self.assertEqual(self.connections.call_count, 2)

    def test_second_ctrl_c_propagates_keyboard_interrupt(self):
        def dispatch(**kwargs):
            handler = self.signal.call_args_list[0].args[1]
            handler(command.signal.SIGINT, None)
            handler(command.signal.SIGINT, None)
        self.dispatch.side_effect = dispatch
        with self.assertRaises(KeyboardInterrupt):
            self.run_command()
        self.signal.assert_called_with(command.signal.SIGINT, "previous-handler")
        self.assertEqual(self.connections.call_count, 2)

    def test_once_database_failure_is_nonzero_and_redacted(self):
        self.dispatch.side_effect = DatabaseError(SECRET)
        with self.assertRaises(CommandError) as caught:
            self.run_command("--once")
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertNotIn(SECRET, self.out.getvalue() + self.err.getvalue())
        self.dispatch.assert_called_once()
        self.wait.assert_not_called()

    def test_loop_database_failure_waits_and_reconnects_before_next_batch(self):
        def dispatch(**kwargs):
            if self.dispatch.call_count == 1:
                raise DatabaseError(SECRET)
            self.stop.set()
            return COUNTS
        self.dispatch.side_effect = dispatch
        self.run_command()
        self.assertEqual(self.dispatch.call_count, 2)
        self.assertEqual(self.connections.call_count, 3)
        self.wait.assert_called_once_with(1.0)
        self.assertIn("DB 작업에 실패", self.err.getvalue())
        self.assertNotIn(SECRET, self.out.getvalue() + self.err.getvalue())

    def test_idle_batches_do_not_emit_repeated_output(self):
        self.dispatch.return_value = dict.fromkeys(COUNTS, 0)
        self.wait.side_effect = lambda timeout: self.stop.set()
        self.run_command()
        self.assertEqual(self.out.getvalue(), "")
        self.dispatch.assert_called_once()

    def test_unexpected_exception_and_keyboard_interrupt_are_not_swallowed(self):
        for error in (RuntimeError("unexpected"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.stop.clear()
                self.dispatch.side_effect = error
                with self.assertRaises(type(error)):
                    self.run_command()
                self.signal.assert_called_with(command.signal.SIGINT, "previous-handler")
        self.wait.assert_not_called()

    def test_cleanup_database_error_is_redacted(self):
        self.connections.side_effect = [None, DatabaseError(SECRET)]
        self.run_command("--once")
        self.assertIn("DB 연결 정리에 실패", self.err.getvalue())
        self.assertNotIn(SECRET, self.out.getvalue() + self.err.getvalue())
