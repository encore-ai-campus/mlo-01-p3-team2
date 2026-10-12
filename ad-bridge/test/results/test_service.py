"""조회 서비스의 소유권·실패·저장 순서를 격리해 검사한다."""
from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock
from ad_bridge.api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from ad_bridge.impressions.store import StoredImpression, DecisionNotFound, ImpressionNotReady
from ad_bridge.results.service import refresh_result
from test.support.impression_fakes import DECISION_ID, REACTION_ID, SUBJECT_ID, OCCURRED_AT, received_reaction


class ResultServiceTests(TestCase):
    def setUp(self):
        self.record = StoredImpression(DECISION_ID, REACTION_ID, SUBJECT_ID, OCCURRED_AT, "ACKNOWLEDGED")
        self.result = received_reaction(decision_id=DECISION_ID, reaction_id=REACTION_ID,
                                        subject_id=SUBJECT_ID, occurred_at=OCCURRED_AT)
        self.store = Mock()
        self.store.get_impression.return_value = self.record
        self.client = Mock()
        self.client.get_reaction.return_value = self.result

    def refresh(self):
        return refresh_result(client=self.client, store=self.store, decision_id=DECISION_ID, subject_id=SUBJECT_ID)

    def check_state(self, state):
        self.client.get_reaction.return_value = replace(self.result, status=state, reason_code="future" if state == "REJECTED" else None)
        self.store.update_result.return_value = replace(self.record, status=state)
        self.assertEqual(self.refresh().status, state)
        self.client.get_reaction.assert_called_once_with(decision_id=DECISION_ID, reaction_id=REACTION_ID)
        self.assertEqual(self.store.update_result.call_args.kwargs["status"], state)
        self.client.report_impression.assert_not_called()

    def test_received(self):
        self.check_state("RECEIVED")

    def test_accepted(self):
        self.check_state("ACCEPTED")

    def test_rejected(self):
        self.check_state("REJECTED")
        self.assertEqual(self.store.update_result.call_args.kwargs["reason_code"], "future")

    def test_owner(self):
        self.store.get_impression.side_effect = DecisionNotFound()
        with self.assertRaises(DecisionNotFound):
            self.refresh()
        self.client.get_reaction.assert_not_called()
        self.store.update_result.assert_not_called()

    def test_pending(self):
        for state in ("SENDING", "UNCONFIRMED", "BLOCKED"):
            self.store.get_impression.return_value = replace(self.record, delivery_state=state)
            with self.assertRaises(ImpressionNotReady):
                self.refresh()
        self.client.get_reaction.assert_not_called()

    def test_lookup_error(self):
        for error in (AdsHTTPError(404), AdsHTTPError(429), AdsHTTPError(503),
                      AdsTransportError("failed"), AdsResponseError("invalid")):
            self.client.get_reaction.side_effect = error
            with self.assertRaises(type(error)):
                self.refresh()
        self.store.update_result.assert_not_called()
        self.client.report_impression.assert_not_called()

    def test_mismatch(self):
        for field, value in (("decision_id", SUBJECT_ID), ("reaction_id", SUBJECT_ID),
                             ("subject_id", None), ("type", "CLICK"), ("occurred_at", "2026-10-12T00:00:00Z")):
            self.client.get_reaction.return_value = replace(self.result, **{field: value})
            with self.assertRaises(AdsResponseError):
                self.refresh()
        self.store.update_result.assert_not_called()

    def test_save_error(self):
        self.store.update_result.side_effect = RuntimeError("storage failed")
        with self.assertRaises(RuntimeError):
            self.refresh()
        self.client.get_reaction.assert_called_once()
        self.client.report_impression.assert_not_called()
