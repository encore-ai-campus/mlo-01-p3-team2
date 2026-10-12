"""Contract proposal only. No operational tables or Kafka producer are invented."""
from typing import Protocol
from uuid import UUID
class PointIntegrationUnavailable(RuntimeError):pass
class PointGateway(Protocol):
    def record_correct_attempt(self, *, user_uuid:UUID, attempt_uuid:UUID, submission_request_uuid:UUID,
                               learning_answer_id:int, subject:str, difficulty:str, question_type:str,
                               requested_delta:int)->dict:
        """Return confirmed ledger_uuid/delta/balance_after/event_uuid, idempotently by attempt_uuid.
        Same-DB owner must make quiz_attempt/wallet/ledger/outbox atomic; cross-DB needs a durable delivery contract.
        """
        ...
def operational_gateway():
    raise PointIntegrationUnavailable('Operational DRD, user UUID mapping and point gateway are not configured.')
