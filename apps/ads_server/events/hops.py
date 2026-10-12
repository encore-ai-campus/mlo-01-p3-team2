"""구간별 정합 manifest의 규칙(DRD §5.6 "구간별 manifest 계약", 계획 4-3b). 파이프라인 쪽이 같은 규칙으로 같은 값을 만들 수 있게 **언어 중립 규칙**으로 고정한다.

- **창**: `produced_at` 기준 UTC 자정 고정 하루. 창이 끝나고 `grace` 초(설정 `EVENTS_HOP_GRACE_SECONDS`, 기본 120)가 지나면 닫힌 창이다. 닫히기 전의 창은 요약하지 않는다.
- **문서 형태**(MongoDB 에 쓰는 형태): `{"event_id", "event_name", "schema_version", "produced_at", "payload"}`. `event_id` 는 소문자 하이픈 UUID 문자열,
  `produced_at` 은 **밀리초까지의 UTC** 문자열 `YYYY-MM-DDTHH:MM:SS.mmmZ`(MongoDB 날짜의 정밀도). `payload` 는 이벤트에 저장된 JSON 그대로.
- `ids_sha256`: 창·이벤트 이름의 이벤트 ID 문자열을 오름차순으로 정렬해 `\\n` 으로 이은 UTF-8 바이트의 SHA-256(0건이면 빈 바이트의 해시).
- `content_sha256`: 위 문서를 정규화 JSON 으로 만들어 이벤트 ID 순으로 `\\n` 으로 이은 UTF-8 바이트의 SHA-256. 정규화는 **RFC 8785(JCS)**: 객체 키를 UTF-16 코드 단위 순으로 정렬,
  공백 없음, 문자열은 JSON 이스케이프(비 ASCII 는 그대로), 불리언·`null`·숫자는 JSON 값 그대로, 정수는 10진수, 실수는 ECMAScript 숫자 문자열(`300.0` → `300`).
  정수와 같은 값의 실수는 JCS 에서 같은 문자열이 된다 — 타입까지의 엄격한 구분은 중계의 충돌 판정과 `verify_events` 가 맡는다.
"""
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .models import EventOutbox
from . import store

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


# ---------------------------------------------------------------- 구간 계약 값 (내보내는 쪽 `export_hop_manifests` 와 대조하는 쪽 `hopcheck` 이 같이 쓴다)

HOP_SCHEMA_VERSION = 1  # 구간 줄 모양의 계약 버전(manifest 의 `schema_version`)
WINDOWS = {"day": DAY, "hour": HOUR}  # 창의 크기: UTC 자정 고정 하루(기본), 옵션으로 UTC 정시 고정 한 시간


def window_label(name):
    """창 옵션 이름(`day`·`hour`) → `checkpoint.window` 선언(`utc-day`·`utc-hour`)."""
    return f"utc-{name}"


WINDOW_SIZES = {window_label(name): size for name, size in WINDOWS.items()}  # `checkpoint.window` 선언 → 크기(대조 쪽이 읽는다)

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # 창 경계·열린 창·보존 기준 시각(초까지의 UTC)
MILLIS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"  # 문서의 `produced_at`(밀리초까지의 UTC, 출력은 `_millis_utc`)


def format_time(moment):
    return moment.strftime(TIME_FORMAT)  # 받은 UTC 시각 그대로(변환하지 않는다)


def parse_time(text):
    """`format_time` 의 반대. 형식이 아니면 `ValueError`(문자열이 아니면 `TypeError`)."""
    return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- 정규화 (RFC 8785)

def _es_number(value):
    """ECMAScript `Number::toString` 과 같은 실수 표기(JCS 가 요구한다)."""
    if not math.isfinite(value):
        raise ValueError("JSON 에 NaN·무한대는 없다")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    normalized = Decimal(repr(abs(value))).normalize().as_tuple()
    digits, exponent = normalized.digits, normalized.exponent
    k = len(digits)
    n = k + exponent  # 10^(n-1) <= 값 < 10^n
    d = "".join(map(str, digits))
    if k <= n <= 21:
        return sign + d + "0" * (n - k)
    if 0 < n <= 21:
        return sign + d[:n] + "." + d[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + d
    e = n - 1
    mantissa = d[0] + ("." + d[1:] if k > 1 else "")
    return f"{sign}{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"


def canonical_json(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        return _es_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0].encode("utf-16-be"))  # UTF-16 코드 단위 순
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical_json(v) for k, v in items) + "}"
    raise TypeError(f"정규화할 수 없는 타입: {type(value).__name__}")


def _millis_utc(moment):
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _produced(doc):
    return datetime.strptime(doc["produced_at"], MILLIS_FORMAT).replace(tzinfo=timezone.utc)


def normal_document(event_id, event_name, schema_version, produced_at, payload):
    return {"event_id": str(event_id).lower(), "event_name": event_name, "schema_version": schema_version, "produced_at": _millis_utc(produced_at), "payload": payload}


# ---------------------------------------------------------------- 창과 요약

def window_start(moment, size=DAY):
    moment = moment.astimezone(timezone.utc)
    return moment.replace(minute=0, second=0, microsecond=0) if size == HOUR else moment.replace(hour=0, minute=0, second=0, microsecond=0)


def is_closed(start, now, grace_seconds, size=DAY):
    return start + size + timedelta(seconds=grace_seconds) <= now


def summarize(documents, now, grace_seconds, since=None, size=DAY):
    """정규화 문서(`normal_document`) 들을 (창, 이벤트 이름)별로 요약한다. 반환: (줄 목록, 열린 창 시작 목록). 열린 창은 줄에 넣지 않는다."""
    groups, open_windows = {}, set()
    for doc in documents:
        start = window_start(_produced(doc), size)
        if since is not None and start < since:
            continue
        if not is_closed(start, now, grace_seconds, size):
            open_windows.add(start)
            continue
        groups.setdefault((start, doc["event_name"]), []).append(doc)
    lines = []
    for (start, name), docs in sorted(groups.items()):
        docs.sort(key=lambda d: d["event_id"])
        lines.append({
            "window_start": format_time(start), "window_end": format_time(start + size), "event_name": name, "count": len(docs),
            "ids_sha256": hashlib.sha256("\n".join(d["event_id"] for d in docs).encode("utf-8")).hexdigest(),
            "content_sha256": hashlib.sha256("\n".join(canonical_json(d) for d in docs).encode("utf-8")).hexdigest(),
        })
    return lines, sorted(open_windows)


# ---------------------------------------------------------------- 창 단위 읽기 (외부 검토 00d3067 P3-3)

def summarize_windows(streams, now, grace_seconds, since=None, size=DAY):
    """`summarize` 와 같은 결과를 **닫힌 창 하나·흐름 하나씩** 읽어 만든다 — 전체 이력을 메모리에 두지 않고, 열린 창과 `since` 앞은 읽지 않는다.

    흐름은 (`first`, `read`) 쌍이다: `first(lo)` 는 `lo`(None 이면 처음) 이후 가장 이른 생성 시각(없으면 None), `read(start, end)` 는 생성 시각이 [start, end) 인 정규화 문서.
    흐름끼리 이벤트 이름이 겹치지 않아야 한다. 반환: (줄 목록, 열린 창 시작 목록, 읽은 문서 수, 한 번에 가장 많이 든 문서 수).
    """
    # ponytail: 창 하나·흐름 하나는 통째로 메모리에 든다(ID 순 정렬이 필요하다). 그것도 크면 --window hour, 그래도 크면 외부 정렬
    lines, open_windows, read_count, largest = [], set(), 0, 0
    for first, read in streams:
        lo = since
        while (moment := first(lo)) is not None:  # 빈 창은 건너뛴다(다음 행이 있는 창으로)
            start = window_start(moment, size)
            lo = start + size
            if not is_closed(start, now, grace_seconds, size):
                open_windows.add(start)
                continue
            docs = list(read(start, lo))
            read_count, largest = read_count + len(docs), max(largest, len(docs))
            lines += summarize(docs, now, grace_seconds, since, size)[0]
    return sorted(lines, key=lambda line: (line["window_start"], line["event_name"])), sorted(open_windows), read_count, largest


def table_stream(queryset, field, to_documents):
    """Django 질의를 생성 시각 열 `field` 의 창으로 읽는 흐름(`summarize_windows` 용). `to_documents(rows)` 가 창 하나의 행을 정규화 문서로 바꾼다.
    `field` 로 시작하는(앞의 같음 조건 뒤에 오는) 색인이 있어야 창마다 범위만 읽는다."""
    def first(lo):
        rows = queryset if lo is None else queryset.filter(**{f"{field}__gte": lo})
        return rows.order_by(field).values_list(field, flat=True).first()

    def read(start, end):
        return to_documents(queryset.filter(**{f"{field}__gte": start, f"{field}__lt": end}))
    return first, read


def outbox_streams():
    """② 구간: outbox 를 이벤트 종류마다 창으로 읽는 흐름(색인 `events_outbox_name_created_idx`). 호출한 쪽의 읽기 스냅샷 안에서 쓴다."""
    def documents(rows):
        return [normal_document(row.event_id, row.event_name, row.schema_version, row.created_at, row.payload) for row in rows]
    for name in EventOutbox.objects.order_by("event_name").values_list("event_name", flat=True).distinct():
        yield table_stream(EventOutbox.objects.filter(event_name=name), "created_at", documents)


def mongo_streams():
    """③ 구간: MongoDB 를 이벤트 종류마다 창으로 읽는 흐름(색인 `event_name_produced_at`)."""
    events = store.collection()
    return [_mongo_stream(events, name) for name in sorted(events.distinct("event_name"))]


def _mongo_stream(events, name):
    def first(lo):
        doc = events.find_one({"event_name": name, **({"produced_at": {"$gte": lo}} if lo else {})}, {"produced_at": 1}, sort=[("produced_at", 1)])
        return doc and doc["produced_at"]

    def read(start, end):
        return [normal_document(doc["_id"], doc["event_name"], doc["schema_version"], doc["produced_at"], doc["payload"])
                for doc in events.find({"event_name": name, "produced_at": {"$gte": start, "$lt": end}})]
    return first, read


def unsent_counts(size=DAY):
    """아직 보내지 않은 outbox 행의 (창 시작, 이벤트 이름)별 건수. 중계 지연 후보를 가리는 데 쓴다. 미전송 행만 읽는다(색인 `events_outbox_pending_idx`).
    호출한 쪽의 읽기 스냅샷 안에서 부른다."""
    rows = EventOutbox.objects.filter(sent_at__isnull=True).values_list("created_at", "event_name").iterator()
    return Counter((format_time(window_start(created_at, size)), name) for created_at, name in rows)
