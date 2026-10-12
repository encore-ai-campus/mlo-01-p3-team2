"""재전송 명령의 반복·종료·실패 처리를 HTTP·DB·대기 없이 확인한다."""

from io import StringIO
from threading import Event
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import SimpleTestCase

from ad_bridge.management.commands import dispatch_ad_reactions as command

COUNTS = {"attempted": 3, "acknowledged": 1, "unconfirmed": 1, "blocked": 1}
SECRET = "unit-test-command-private-key"


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
