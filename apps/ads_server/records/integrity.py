"""이벤트 누락 점검(계획 4-2): 원본 행(결정·접수·판정·원장 CHARGE)마다 이벤트가 outbox 나 MongoDB 에 있는지 본다.

**원본 행을 먼저 읽고 이벤트를 나중에 조회한다**: 이벤트는 원본 행과 같은 트랜잭션에 쓰이므로, 읽은 원본 행의 이벤트는 그 뒤 조회에서 반드시 보인다.
순서를 거꾸로 하면 점검 도중 새로 생긴 행이 거짓 누락으로 보인다.
"""
from billing import api as billing
from events import api as events

from .models import Decision, Reaction

CHUNK = 2000


def _chunks(rows, size=CHUNK):
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _sources():
    """(원천 종류, 원천 ID, 이벤트 이름) 을 훑는다."""
    for decision_id in Decision.objects.values_list("decision_id", flat=True).iterator(chunk_size=CHUNK):
        yield "decision", decision_id, events.NAMES["decision"]
    for inbox_id, status in Reaction.objects.values_list("inbox_id", "status").iterator(chunk_size=CHUNK):
        yield "reaction", inbox_id, events.NAMES["reaction_received"]
        if status != "RECEIVED":
            yield "reaction", inbox_id, events.NAMES["reaction"]
    for entry_id in billing.charge_entry_ids():
        yield "ledger_charge", entry_id, events.NAMES["charge"]


def event_gaps():
    """이벤트가 없는 원본 행을 NDJSON 레코드(dict)로 낸다. MongoDB 에 닿지 못하면 예외가 난다(없다고 잘못 말하지 않는다)."""
    for batch in _chunks(_sources()):
        ids = {events.event_id_for(name, source_id): (kind, source_id, name) for kind, source_id, name in batch}
        for event_id in events.missing_event_ids(list(ids)):
            kind, source_id, name = ids[event_id]
            yield {"kind": "missing_event", "event_name": name, "source_kind": kind, "source_id": str(source_id), "event_id": str(event_id)}
