"""고정 시계와 메모리 저장소로 노출 재전송 정책을 검사한다."""

from datetime import timedelta
import json
import unittest
from unittest.mock import Mock
from uuid import UUID

from ad_bridge.api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from ad_bridge.impressions.store import StoredImpression
from ad_bridge.delivery.worker import dispatch_due_impressions
from ad_bridge.impressions.service import report_impression_once
from test.support.clock import FixedClock
from ad_bridge.delivery.policy import RetryPolicy
from test.support.impression_fakes import (
    DECISION_ID, SUBJECT_ID, REACTION_ID, OCCURRED_AT, PRIVATE_KEY,
    MemoryImpressionStore, received_reaction,
)


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock()
        self.store = MemoryImpressionStore()
        self.client = Mock()
        self.client.report_impression.side_effect = received_reaction
        self.policy = RetryPolicy(base_delay=2, max_delay=10, lease_seconds=30)

    def report(self):
        return report_impression_once(
            client=self.client, store=self.store, decision_id=DECISION_ID,
            subject_id=SUBJECT_ID, occurred_at=OCCURRED_AT,
            policy=self.policy, now=self.clock,
        )

    def dispatch(self, **kwargs):
        return dispatch_due_impressions(
            client=self.client, store=self.store, policy=self.policy, now=self.clock, **kwargs
        )

    def seed_due(self, count):
        for index in range(count):
            reaction_id = str(UUID(int=index + 1))
            self.store.records[reaction_id] = StoredImpression(
                decision_id=str(UUID(int=index + 101)), reaction_id=reaction_id,
                subject_id=SUBJECT_ID, occurred_at=OCCURRED_AT,
                delivery_state="UNCONFIRMED", attempts=1,
                next_attempt_at=self.clock(),
            )

    def test_failed_report_waits_until_due_and_reuses_identical_payload(self):
        self.client.report_impression.side_effect = AdsTransportError(PRIVATE_KEY)
        first = self.report()
        original_payload = json.dumps(self.client.report_impression.call_args.kwargs, sort_keys=True).encode()
        self.assertEqual(first.record.next_attempt_at, self.clock() + timedelta(seconds=2))
        self.assertEqual(first.record.attempts, 1)
        self.clock.advance(1)
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.client.report_impression.assert_called_once()
        self.clock.advance(1)
        self.client.report_impression.side_effect = received_reaction
        result = self.dispatch()
        self.assertEqual(result, {"attempted": 1, "acknowledged": 1, "unconfirmed": 0, "blocked": 0})
        retried_payload = json.dumps(self.client.report_impression.call_args.kwargs, sort_keys=True).encode()
        self.assertEqual(retried_payload, original_payload)
        self.assertEqual(self.store.record.attempts, 2)
        self.assertEqual(self.store.record.delivery_state, "ACKNOWLEDGED")
        self.assertIsNone(self.store.record.next_attempt_at)
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.assertEqual(self.client.report_impression.call_count, 2)

    def test_retry_after_remains_a_minimum_even_beyond_backoff_cap(self):
        self.client.report_impression.side_effect = AdsHTTPError(503, retry_after=600)
        outcome = self.report()
        self.assertEqual(outcome.record.next_attempt_at, self.clock() + timedelta(seconds=600))
        self.clock.advance(599)
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.clock.advance(1)
        self.client.report_impression.side_effect = received_reaction
        self.assertEqual(self.dispatch()["acknowledged"], 1)

    def test_backoff_doubles_caps_and_handles_very_large_attempt_count(self):
        for attempts, expected in ((1, 2), (2, 4), (3, 8), (4, 10), (10**9, 10)):
            with self.subTest(attempts=attempts):
                self.assertEqual(self.policy.delay_for(attempts), expected)

    def test_429_retry_after_zero_still_waits_for_local_backoff(self):
        self.client.report_impression.side_effect = AdsHTTPError(429, retry_after=0)
        outcome = self.report()
        self.assertEqual(outcome.record.next_attempt_at, self.clock() + timedelta(seconds=2))
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.clock.advance(2)
        self.client.report_impression.side_effect = received_reaction
        self.assertEqual(self.dispatch()["acknowledged"], 1)

    def test_retry_delay_starts_after_failed_http_finishes(self):
        def slow_failure(**payload):
            self.clock.advance(9)
            raise AdsTransportError(PRIVATE_KEY)

        self.client.report_impression.side_effect = slow_failure
        started_at = self.clock()
        outcome = self.report()
        self.assertEqual(outcome.record.next_attempt_at, started_at + timedelta(seconds=11))
        self.assertNotIn(PRIVATE_KEY, repr(outcome.record))

    def test_worker_reschedules_transient_failures_using_incremented_attempts(self):
        self.client.report_impression.side_effect = AdsHTTPError(500)
        self.report()
        self.clock.advance(2)
        result = self.dispatch()
        self.assertEqual(result, {"attempted": 1, "acknowledged": 0, "unconfirmed": 1, "blocked": 0})
        self.assertEqual(self.store.record.attempts, 2)
        self.assertEqual(self.store.record.next_attempt_at, self.clock() + timedelta(seconds=4))
        self.assertEqual(self.store.record.last_http_status, 500)
        self.assertEqual(self.store.record.last_error, "ads_http_error")

    def test_terminal_http_errors_never_get_new_ids_or_worker_retries(self):
        for status in (302, 400, 401, 409):
            with self.subTest(status=status):
                self.store = MemoryImpressionStore()
                self.client.reset_mock()
                self.client.report_impression.side_effect = AdsHTTPError(status)
                outcome = self.report()
                self.clock.advance(3600)
                self.assertEqual(self.dispatch()["attempted"], 0)
                self.assertEqual(outcome.record.reaction_id, REACTION_ID)
                self.assertEqual(outcome.record.delivery_state, "BLOCKED")
                self.assertIsNone(outcome.record.next_attempt_at)
                self.client.report_impression.assert_called_once()

    def test_worker_counts_permanent_failure_as_blocked(self):
        self.seed_due(1)
        self.client.report_impression.side_effect = AdsHTTPError(409)
        result = self.dispatch()
        self.assertEqual(result, {"attempted": 1, "acknowledged": 0, "unconfirmed": 0, "blocked": 1})
        self.assertEqual(self.dispatch()["attempted"], 0)

    def test_expired_sending_lease_is_recovered_with_same_event(self):
        original, _ = self.store.reserve_impression(
            DECISION_ID, SUBJECT_ID, OCCURRED_AT, now=self.clock(), lease_seconds=30
        )
        self.clock.advance(29)
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.clock.advance(1)
        self.assertEqual(self.dispatch()["acknowledged"], 1)
        self.client.report_impression.assert_called_once_with(
            decision_id=original.decision_id, reaction_id=original.reaction_id,
            subject_id=original.subject_id, occurred_at=original.occurred_at,
        )
        self.assertEqual(self.store.record.attempts, 2)

    def test_legacy_missing_schedule_or_lease_is_recoverable(self):
        for state in ("UNCONFIRMED", "SENDING"):
            with self.subTest(state=state):
                self.store = MemoryImpressionStore()
                self.client.reset_mock()
                self.store.record = StoredImpression(
                    decision_id=DECISION_ID, reaction_id=REACTION_ID,
                    subject_id=SUBJECT_ID, occurred_at=OCCURRED_AT,
                    delivery_state=state,
                )
                self.assertEqual(self.dispatch()["acknowledged"], 1)
                self.client.report_impression.assert_called_once()

    def test_malformed_acknowledged_body_stops_future_puts(self):
        self.seed_due(1)
        self.client.report_impression.side_effect = AdsResponseError(
            PRIVATE_KEY, acknowledged=True, request_id="received-but-malformed"
        )
        result = self.dispatch()
        self.assertEqual(result["acknowledged"], 1)
        saved = next(iter(self.store.records.values()))
        self.assertIsNone(saved.status)
        self.assertEqual(saved.delivery_state, "ACKNOWLEDGED")
        self.assertIsNone(saved.next_attempt_at)
        self.assertNotIn(PRIVATE_KEY, repr(saved))
        self.clock.advance(3600)
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.client.report_impression.assert_called_once()

    def test_malformed_response_without_acknowledgement_is_blocked(self):
        self.seed_due(1)
        self.client.report_impression.side_effect = AdsResponseError(PRIVATE_KEY)
        self.assertEqual(self.dispatch()["blocked"], 1)
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.client.report_impression.assert_called_once()

    def test_batch_limit_leaves_remaining_records_for_next_run(self):
        self.seed_due(3)
        first = self.dispatch(limit=2)
        self.assertEqual(first["attempted"], 2)
        self.assertEqual(first["acknowledged"], 2)
        self.assertEqual(self.client.report_impression.call_count, 2)
        second = self.dispatch(limit=2)
        self.assertEqual(second["attempted"], 1)
        self.assertEqual(second["acknowledged"], 1)

    def test_stop_signal_prevents_claim_and_stops_between_items(self):
        self.seed_due(2)
        self.assertEqual(self.dispatch(should_stop=lambda: True)["attempted"], 0)
        self.assertEqual(self.store.events, [])
        result = self.dispatch(should_stop=lambda: self.client.report_impression.call_count >= 1)
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(self.client.report_impression.call_count, 1)
        self.assertEqual(self.dispatch()["attempted"], 1)

    def test_result_save_failure_recovers_only_after_lease_expiry(self):
        self.store.finish_error = RuntimeError("result store unavailable")
        with self.assertRaisesRegex(RuntimeError, "result store unavailable"):
            self.report()
        original = self.store.record
        self.assertEqual(original.delivery_state, "SENDING")
        self.store.finish_error = None
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.clock.advance(30)
        self.assertEqual(self.dispatch()["acknowledged"], 1)
        self.assertEqual(self.store.record.reaction_id, original.reaction_id)
        self.assertEqual(self.store.record.occurred_at, original.occurred_at)
        self.assertEqual(self.client.report_impression.call_count, 2)

    def test_late_retry_after_from_expired_worker_delays_next_claim(self):
        def overlapping_sends(**payload):
            if self.client.report_impression.call_count == 1:
                # 느린 A의 예약이 만료된 동안 B가 같은 이벤트를 확보했다가 실패한다.
                self.clock.advance(30)
                result = self.dispatch()
                self.assertEqual(result["unconfirmed"], 1)
                self.assertEqual(self.store.record.next_attempt_at, self.clock() + timedelta(seconds=4))
                raise AdsHTTPError(429, retry_after=120)
            if self.client.report_impression.call_count == 2:
                raise AdsTransportError(PRIVATE_KEY)
            return received_reaction(**payload)

        self.client.report_impression.side_effect = overlapping_sends
        outcome = self.report()
        self.assertEqual(outcome.record.attempts, 2)
        self.assertEqual(outcome.record.next_attempt_at, self.clock() + timedelta(seconds=120))
        self.assertEqual(outcome.record.last_error, "ads_unreachable")
        self.assertIsNone(outcome.record.lease_token)
        self.clock.advance(4)
        self.assertEqual(self.dispatch()["attempted"], 0)
        self.clock.advance(116)
        self.assertEqual(self.dispatch()["acknowledged"], 1)
        payloads = [item.kwargs for item in self.client.report_impression.call_args_list]
        self.assertEqual(len(payloads), 3)
        self.assertTrue(all(payload == payloads[0] for payload in payloads))

    def test_policy_rejects_nonpositive_nonfinite_and_boolean_parameters(self):
        for field in ("base_delay", "max_delay", "lease_seconds"):
            for value in (0, -1, True, False, float("nan"), float("inf"), float("-inf"), None):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        RetryPolicy(**{field: value})

    def test_delay_rejects_invalid_attempts_and_retry_after(self):
        for attempts in (0, -1, True, 1.5, float("nan"), float("inf")):
            with self.subTest(attempts=attempts):
                with self.assertRaises(ValueError):
                    self.policy.delay_for(attempts)
        for retry_after in (-1, True, 1.5, float("nan"), float("inf"), "10"):
            with self.subTest(retry_after=retry_after):
                with self.assertRaises(ValueError):
                    self.policy.delay_for(1, retry_after=retry_after)

    def test_invalid_batch_limit_fails_before_claiming_or_sending(self):
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.dispatch(limit=limit)
        self.assertEqual(self.store.events, [])
        self.client.report_impression.assert_not_called()


if __name__ == "__main__":
    unittest.main()
