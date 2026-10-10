"""events 의 외부 공개 면. 다른 모듈은 이 파일만 import 한다(설계 R2).

각 함수는 **호출한 쪽의 트랜잭션 안에서** outbox 에 이벤트 한 건을 쓴다. 필드 이름·형식은 `schemas.py` 가 정한다.
"""
from . import hops, ndjson, schemas
from .mongo import NotConfigured
from .outbox import OutsideTransaction, enqueue
from .relay import missing_event_ids, sent_but_not_in_mongo


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


def event_id_for(event_name, source_id):
    return schemas.event_id_of(event_name, source_id)


NAMES = {"decision": schemas.DECISION, "reaction_received": schemas.REACTION_RECEIVED, "reaction": schemas.REACTION, "charge": schemas.CHARGE}
write_ndjson, verify_ndjson, read_manifest, NdjsonError = ndjson.write, ndjson.verify, ndjson.read_manifest, ndjson.NdjsonError
manifest_sha256, verify_chain, manifest_path = ndjson.manifest_sha256, ndjson.verify_chain, ndjson.manifest_path

SCHEMA_VERSION = schemas.SCHEMA_VERSION
decision_payload, reaction_received_payload, reaction_payload, charge_payload = (
    schemas.decision_payload, schemas.reaction_received_payload, schemas.reaction_payload, schemas.charge_payload)
normal_document, summarize, window_start, canonical_json = hops.normal_document, hops.summarize, hops.window_start, hops.canonical_json
outbox_documents, mongo_documents, unsent_counts, WINDOWS = hops.outbox_documents, hops.mongo_documents, hops.unsent_counts, hops.WINDOWS

__all__ = [
    "SCHEMA_VERSION", "decision_payload", "reaction_received_payload", "reaction_payload", "charge_payload",
    "normal_document", "summarize", "window_start", "canonical_json", "outbox_documents", "mongo_documents", "unsent_counts", "WINDOWS",
    "OutsideTransaction", "record_decision", "record_reaction_received", "record_reaction", "record_charge", "event_id_for", "NAMES",
    "missing_event_ids", "sent_but_not_in_mongo", "write_ndjson", "verify_ndjson", "read_manifest", "manifest_sha256", "verify_chain", "manifest_path", "NdjsonError", "NotConfigured",
]
