"""events 의 외부 공개 면. 다른 모듈은 이 파일만 import 한다(설계 R2).

각 함수는 **호출한 쪽의 트랜잭션 안에서** outbox 에 이벤트 한 건을 쓴다. 필드 이름·형식은 `schemas.py` 가 정한다.
"""
from . import schemas
from .outbox import OutsideTransaction, enqueue


def record_decision(*, now=None, **fields):
    payload = schemas.decision_payload(**fields)
    return enqueue(schemas.DECISION, fields["decision_id"], fields["decision_id"], payload, now)


def record_reaction_received(*, now=None, **fields):
    payload = schemas.reaction_received_payload(**fields)
    return enqueue(schemas.REACTION_RECEIVED, fields["inbox_id"], fields["decision_id"], payload, now)


def record_reaction(*, now=None, **fields):
    payload = schemas.reaction_payload(**fields)
    return enqueue(schemas.REACTION, fields["inbox_id"], fields["decision_id"], payload, now)


def record_charge(*, now=None, **fields):
    payload = schemas.charge_payload(**fields)
    return enqueue(schemas.CHARGE, fields["entry_id"], fields["decision_id"], payload, now)


__all__ = ["OutsideTransaction", "record_decision", "record_reaction_received", "record_reaction", "record_charge"]
