"""노출 예약·최초 전송·접수 상태 저장을 외부 연결 없이 검사한다."""

import unittest
from unittest.mock import Mock

from ad_bridge.api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from ad_bridge.impressions.service import report_impression_once
from test.support.impression_fakes import (
    DECISION_ID, SUBJECT_ID, REACTION_ID, OCCURRED_AT, PRIVATE_KEY,
    MemoryImpressionStore, received_reaction,
)


class ImpressionServiceTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryImpressionStore()
        self.client = Mock()
        self.client.report_impression.side_effect = received_reaction

    def report(self, *, occurred_at=OCCURRED_AT):
        return report_impression_once(
            client=self.client, store=self.store, decision_id=DECISION_ID,
            subject_id=SUBJECT_ID, occurred_at=occurred_at,
        )

    def test_first_report_reserves_stable_payload_before_http(self):
        def send(**payload):
            # 전송을 시작하는 순간에도 ID와 시각이 저장돼 있어야 한다.
            self.assertIsNotNone(self.store.record)
            self.assertEqual(self.store.record.delivery_state, "SENDING")
            self.assertEqual(self.store.events, ["reserve"])
            self.store.events.append("http")
            return received_reaction(**payload)

        self.client.report_impression.side_effect = send
        outcome = self.report()
        self.assertTrue(outcome.created)
        self.assertIsNone(outcome.error)
        self.client.report_impression.assert_called_once_with(
            decision_id=DECISION_ID, reaction_id=REACTION_ID,
            occurred_at=OCCURRED_AT, subject_id=SUBJECT_ID,
        )
        self.assertEqual(self.store.events, ["reserve", "http", "finish"])
        self.assertEqual(outcome.record.delivery_state, "ACKNOWLEDGED")
        self.assertEqual(outcome.record.status, "RECEIVED")
        self.assertEqual(outcome.record.request_id, "request-received")

    def test_acknowledged_duplicate_preserves_uuid_and_time_without_resending(self):
        first = self.report()
        second = self.report(occurred_at="2026-10-11T12:05:00Z")
        self.assertFalse(second.created)
        self.assertEqual(second.record, first.record)
        self.client.report_impression.assert_called_once()

    def test_unconfirmed_duplicate_is_not_retried_in_this_step(self):
        self.client.report_impression.side_effect = AdsTransportError(PRIVATE_KEY)
        first = self.report()
        second = self.report(occurred_at="2026-10-11T12:05:00Z")
        self.assertEqual(first.record.delivery_state, "UNCONFIRMED")
        self.assertFalse(second.created)
        self.assertEqual(second.record, first.record)
        self.client.report_impression.assert_called_once()

    def test_existing_sending_reservation_is_not_sent_again(self):
        original, _ = self.store.reserve_impression(DECISION_ID, SUBJECT_ID, OCCURRED_AT)
        outcome = self.report(occurred_at="2026-10-11T12:05:00Z")
        self.assertFalse(outcome.created)
        self.assertEqual(outcome.record, original)
        self.client.report_impression.assert_not_called()

    def test_terminal_http_errors_are_blocked_without_new_reaction(self):
        for status in (400, 409):
            with self.subTest(status=status):
                self.store = MemoryImpressionStore()
                self.client.reset_mock()
                self.client.report_impression.side_effect = AdsHTTPError(
                    status, request_id="terminal-request"
                )
                outcome = self.report()
                duplicate = self.report()
                self.assertEqual(outcome.record.delivery_state, "BLOCKED")
                self.assertEqual(outcome.error, "ads_http_error")
                self.assertEqual(outcome.upstream_status, status)
                self.assertEqual(duplicate.record.reaction_id, REACTION_ID)
                self.client.report_impression.assert_called_once()

    def test_retryable_http_errors_remain_unconfirmed_without_immediate_retry(self):
        for status in (429, 500, 503):
            with self.subTest(status=status):
                self.store = MemoryImpressionStore()
                self.client.reset_mock()
                self.client.report_impression.side_effect = AdsHTTPError(
                    status, request_id="retry-later", retry_after=17
                )
                outcome = self.report()
                self.assertEqual(outcome.record.delivery_state, "UNCONFIRMED")
                self.assertEqual(outcome.upstream_status, status)
                self.assertEqual(outcome.retry_after, 17)
                self.assertEqual(outcome.record.request_id, "retry-later")
                self.client.report_impression.assert_called_once()

    def test_transport_failure_is_unconfirmed_without_secret_text(self):
        self.client.report_impression.side_effect = AdsTransportError(PRIVATE_KEY)
        outcome = self.report()
        self.assertEqual(outcome.record.delivery_state, "UNCONFIRMED")
        self.assertEqual(outcome.error, "ads_unreachable")
        self.assertNotIn(PRIVATE_KEY, repr(outcome))
        self.client.report_impression.assert_called_once()

    def test_malformed_acknowledged_response_keeps_receipt_and_does_not_resend(self):
        self.client.report_impression.side_effect = AdsResponseError(
            PRIVATE_KEY, acknowledged=True, request_id="ack-with-invalid-body"
        )
        first = self.report()
        second = self.report()
        self.assertEqual(first.record.delivery_state, "ACKNOWLEDGED")
        self.assertIsNone(first.record.status)
        self.assertEqual(first.error, "ads_invalid_response")
        self.assertEqual(first.record.request_id, "ack-with-invalid-body")
        self.assertEqual(first.record, second.record)
        self.assertNotIn(PRIVATE_KEY, repr(first))
        self.client.report_impression.assert_called_once()

    def test_response_without_acknowledgement_is_blocked(self):
        self.client.report_impression.side_effect = AdsResponseError(PRIVATE_KEY)
        outcome = self.report()
        self.assertEqual(outcome.record.delivery_state, "BLOCKED")
        self.assertIsNone(outcome.record.status)
        self.assertNotIn(PRIVATE_KEY, repr(outcome))

    def test_invalid_input_is_blocked_without_raw_exception(self):
        self.client.report_impression.side_effect = ValueError(PRIVATE_KEY)
        outcome = self.report()
        self.assertEqual(outcome.record.delivery_state, "BLOCKED")
        self.assertEqual(outcome.error, "ads_invalid_input")
        self.assertNotIn(PRIVATE_KEY, repr(outcome))

    def test_reservation_failure_prevents_http(self):
        self.store.reserve_error = RuntimeError("reservation storage unavailable")
        with self.assertRaisesRegex(RuntimeError, "reservation storage unavailable"):
            self.report()
        self.assertIsNone(self.store.record)
        self.client.report_impression.assert_not_called()

    def test_save_failure_after_receipt_preserves_reservation_and_prevents_resend(self):
        self.store.finish_error = RuntimeError("result storage unavailable")
        with self.assertRaisesRegex(RuntimeError, "result storage unavailable"):
            self.report()
        reserved = self.store.record
        self.assertEqual(reserved.delivery_state, "SENDING")
        self.assertEqual(reserved.reaction_id, REACTION_ID)
        self.assertEqual(reserved.occurred_at, OCCURRED_AT)
        # 후속 요청이 오더라도 새 ID를 만들거나 HTTP를 다시 보내지 않는다.
        self.store.finish_error = None
        second = self.report(occurred_at="2026-10-11T12:05:00Z")
        self.assertFalse(second.created)
        self.assertEqual(second.record, reserved)
        self.client.report_impression.assert_called_once()


if __name__ == "__main__":
    unittest.main()
