"""공유 요청에는 내부 사용자와 가명을 넣지 않고 저장 후 반환한다."""

from unittest import TestCase
from unittest.mock import Mock, call
from uuid import uuid4

from ad_bridge.decisions.service import create_decision
from ad_bridge.tests.support import shared_decision


class SharedDecisionServiceTests(TestCase):
    def test_shared_response_is_saved_before_return(self):
        calls = Mock()
        decision = shared_decision()
        calls.client.create_decision.return_value = decision
        result = create_decision(client=calls.client, store=calls.store, slot_id=decision.slot_id)
        self.assertIs(result, decision)
        self.assertEqual(calls.mock_calls, [
            call.client.create_decision(slot_id=decision.slot_id, subject_id=None),
            call.store.remember_decision(decision, None, owner_id=None),
        ])

    def test_storage_failure_is_propagated_without_a_second_request(self):
        client, store = Mock(), Mock()
        store.remember_decision.side_effect = RuntimeError("저장 실패")
        with self.assertRaises(RuntimeError):
            create_decision(client=client, store=store, slot_id=str(uuid4()))
        client.create_decision.assert_called_once()

    def test_partial_user_identity_is_rejected_before_http(self):
        client, store = Mock(), Mock()
        for identity in ({"owner_id": uuid4()}, {"subject_id": uuid4()}):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                create_decision(client=client, store=store, slot_id=str(uuid4()), **identity)
        client.create_decision.assert_not_called()
        store.remember_decision.assert_not_called()
