"""outbox → MongoDB `ad_events` 중계(설계 §6.3, 계획 4-1e).

- **최소 한 번 전달 + 멱등 저장**: 문서의 `_id` 는 이벤트 ID 다. 이미 있으면 내용을 비교해 같으면 통과(duplicate), **다르면 멈추고 경보**(충돌)한다.
  쓰고 나서 `sent_at` 을 표시하기 전에 죽어도 다음에 다시 보내면 같은 내용의 중복으로 통과한다.
- **여러 중계가 동시에 돌아도 안전하다**: 행을 `FOR UPDATE SKIP LOCKED` 로 잡아 서로 다른 행을 가져간다.
- MongoDB 가 죽어 있으면 되돌리고(행은 미전송으로 남는다) 예외를 올린다. 앱의 요청 경로는 이 파일을 쓰지 않는다 — 요청은 outbox 에 쓰기만 한다.
"""
import datetime
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from pymongo.errors import BulkWriteError

from . import store
from .models import EventOutbox

DUPLICATE_KEY = 11000
BATCH = 200


class EventConflict(Exception):
    """같은 이벤트 ID 가 이미 다른 내용으로 저장돼 있다 — 멈추고 사람이 봐야 한다(이벤트 ID 가 결정적이므로 일어나선 안 되는 일)."""

    def __init__(self, event_ids):
        super().__init__(f"같은 event_id 에 다른 내용이 이미 있습니다: {[str(i) for i in event_ids]}")
        self.event_ids = event_ids


@dataclass(frozen=True)
class RelayResult:
    sent: int = 0  # 새로 저장한 건수
    duplicate: int = 0  # 이미 같은 내용이 있어 통과한 건수


def _millis(value):
    """MongoDB 날짜는 밀리초까지다 — 비교가 어긋나지 않게 처음부터 밀리초로 자른다."""
    return value.astimezone(datetime.timezone.utc).replace(microsecond=value.microsecond // 1000 * 1000)


def to_document(row):
    return {"_id": row.event_id, "event_name": row.event_name, "schema_version": row.schema_version, "produced_at": _millis(row.created_at), "payload": row.payload}


def _write(documents):
    """문서를 저장한다. 반환: (새로 저장한 수, 같은 내용이라 통과한 수, 충돌한 event_id 목록)."""
    events = store.collection()
    duplicate_ids = []
    try:
        events.insert_many(documents, ordered=False)
    except BulkWriteError as error:
        write_errors = error.details.get("writeErrors", [])
        if error.details.get("writeConcernErrors") or any(e["code"] != DUPLICATE_KEY for e in write_errors):
            raise  # 중복이 아닌 오류(과반 확인 실패·검증 거부 등)는 숨기지 않는다
        duplicate_ids = [documents[e["index"]]["_id"] for e in write_errors]
    if not duplicate_ids:
        return len(documents), 0, []
    stored = {d["_id"]: d for d in events.find({"_id": {"$in": duplicate_ids}})}
    by_id = {d["_id"]: d for d in documents}
    conflicts = [i for i in duplicate_ids if stored.get(i) != by_id[i]]
    return len(documents) - len(duplicate_ids), len(duplicate_ids) - len(conflicts), conflicts


def relay_batch(limit=BATCH, now=None):
    """안 보낸 이벤트를 최대 `limit` 건 MongoDB 에 저장하고 `sent_at` 을 표시한다. 충돌이 있으면 **충돌하지 않은 것은 표시해 커밋한 뒤** `EventConflict` 로 멈춘다."""
    conflicts = []
    with transaction.atomic():
        rows = list(EventOutbox.objects.select_for_update(skip_locked=True).filter(sent_at__isnull=True).order_by("created_at", "event_id")[:limit])
        if not rows:
            return RelayResult()
        sent, duplicate, conflicts = _write([to_document(r) for r in rows])
        done = [r.pk for r in rows if r.pk not in set(conflicts)]
        EventOutbox.objects.filter(pk__in=done).update(sent_at=now or timezone.now())
    if conflicts:
        raise EventConflict(conflicts)
    return RelayResult(sent=sent, duplicate=duplicate)


def outbox_status(now=None):
    """미전송 건수와 가장 오래된 것의 나이(초). 쌓이고 있으면 중계가 멈췄거나 MongoDB 가 죽어 있다."""
    now = now or timezone.now()
    pending = EventOutbox.objects.filter(sent_at__isnull=True)
    oldest = pending.order_by("created_at").values_list("created_at", flat=True).first()
    return {"pending": pending.count(), "oldest_age_seconds": None if oldest is None else (now - oldest).total_seconds()}
