"""광고 결정 요청과 소유권 저장의 순서를 외부 연결 없이 검사한다."""

from dataclasses import replace
import unittest
from unittest.mock import Mock, call

from ad_bridge.api.types import Ad, Decision
from ad_bridge.decisions.service import create_decision


class DecisionServiceTests(unittest.TestCase):
    def setUp(self):
        self.slot_id = "aabbccdd-1234-4234-8234-123456789abc"
        self.subject_id = "11223344-1234-4234-8234-123456789abc"
        self.owner_id = "99887766-1234-4234-8234-123456789abc"
        self.decision = Decision(
            decision_id="22334455-1234-4234-8234-123456789abc",
            slot_id=self.slot_id, slot_name="테스트 슬롯", audience="individual",
            decided_at="2026-10-11T12:00:00Z", request_id="decision-request",
            ad=Ad(
                creative_id="33445566-1234-4234-8234-123456789abc",
                title="광고", image_url="http://ads.test/assets/test.png",
                redirect_url="https://example.com", click_url="http://ads.test/c/token",
            ),
        )
        self.client = Mock()
        self.client.create_decision.return_value = self.decision
        self.store = Mock()

    def create(self):
        return create_decision(
            client=self.client, store=self.store,
            slot_id=self.slot_id, subject_id=self.subject_id, owner_id=self.owner_id,
        )

    def test_request_is_saved_before_decision_is_returned(self):
        calls = Mock()
        calls.attach_mock(self.client, "client")
        calls.attach_mock(self.store, "store")
        result = self.create()
        self.assertIs(result, self.decision)
        # 서버가 발급한 결정과 그 소유자를 저장한 뒤에만 호출자에게 반환한다.
        self.assertEqual(calls.mock_calls, [
            call.client.create_decision(slot_id=self.slot_id, subject_id=self.subject_id),
            call.store.remember_decision(self.decision, self.subject_id, owner_id=self.owner_id),
        ])

    def test_storage_failure_is_propagated_without_requesting_again(self):
        failure = RuntimeError("decision storage unavailable")
        self.store.remember_decision.side_effect = failure
        with self.assertRaises(RuntimeError) as caught:
            self.create()
        self.assertIs(caught.exception, failure)
        self.client.create_decision.assert_called_once_with(
            slot_id=self.slot_id, subject_id=self.subject_id
        )
        self.store.remember_decision.assert_called_once_with(self.decision, self.subject_id, owner_id=self.owner_id)

    def test_no_ad_decision_is_also_saved(self):
        decision = replace(self.decision, ad=None)
        self.client.create_decision.return_value = decision
        self.assertIs(self.create(), decision)
        self.store.remember_decision.assert_called_once_with(decision, self.subject_id, owner_id=self.owner_id)


if __name__ == "__main__":
    unittest.main()
