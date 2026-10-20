"""outbox 쓰기. **호출한 쪽의 트랜잭션 안에서만** 쓴다 — 업무 데이터와 같은 트랜잭션이어야 "저장은 됐는데 이벤트가 없는" 상태가 생기지 않는다."""
from django.db import connection
from django.utils import timezone

from . import schemas
from .models import EventOutbox


class OutsideTransaction(RuntimeError):
    """트랜잭션 밖에서 outbox 를 쓰려 했다(프로그래밍 오류)."""


def enqueue(event_name, source_id, aggregate_id, payload, produced_at=None):
    """이벤트 한 건을 outbox 에 쓴다. 같은 (이벤트 종류, 원천 ID) 는 한 줄만 남고 다시 써도 바뀌지 않는다(재처리 멱등)."""
    if not connection.in_atomic_block:
        raise OutsideTransaction("outbox 는 업무 데이터와 같은 트랜잭션 안에서 써야 한다")
    row = EventOutbox(
        event_id=schemas.event_id_of(event_name, source_id), event_name=event_name, schema_version=schemas.SCHEMA_VERSIONS[event_name],
        aggregate_id=aggregate_id, payload=payload, created_at=produced_at or timezone.now(),
    )
    # 이미 있으면 아무것도 바꾸지 않는다(ON DUPLICATE KEY UPDATE 로 같은 값을 다시 쓴다). INSERT IGNORE 는 쓰지 않는다: STRICT 모드의 다른 오류(길이·형식)까지 경고로 삼킨다
    EventOutbox.objects.bulk_create([row], update_conflicts=True, update_fields=["event_name"])
    return row.event_id
