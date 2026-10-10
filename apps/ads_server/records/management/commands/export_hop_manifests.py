from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pymongo.errors import PyMongoError

from billing.api import consistent_read
from events import api as events
from foundation.api import record_audit
from records.api import source_documents

SCHEMA_VERSION = 1
SCOPE = "mysql-repeatable-read-snapshot"
HOPS = ("hop_source", "hop_outbox", "hop_mongo")


class Command(BaseCommand):
    help = (
        "구간별 정합 manifest(설계 §6.3a)를 낸다: hop_source(원본에서 기대되는 이벤트) / hop_outbox / hop_mongo 세 구간의 (창, 이벤트 이름)별 건수·ids_sha256·content_sha256. "
        "창은 UTC 자정 고정 하루이고 창 끝 + 여유(EVENTS_HOP_GRACE_SECONDS) 뒤에 닫힌다 — 닫히기 전 창은 요약하지 않는다. "
        "원본과 outbox 는 하나의 MySQL 읽기 스냅샷에서 읽고, 매번 새 세대로 게시한다(previous_sha256 으로 연결, 감사 로그에 고정점을 남긴다)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="결과를 쓸 폴더")
        parser.add_argument("--since", help="이 날짜(UTC, YYYY-MM-DD) 이후의 창만")

    def handle(self, *args, **options):
        since = None
        if options["since"]:
            try:
                since = datetime.combine(date.fromisoformat(options["since"]), datetime.min.time(), tzinfo=timezone.utc)
            except ValueError:
                raise CommandError("--since 는 YYYY-MM-DD 형식이어야 합니다.")
        now, grace = datetime.now(timezone.utc), settings.EVENTS_HOP_GRACE_SECONDS
        try:
            with consistent_read():  # 원본(①)과 outbox(②)는 같은 스냅샷을 본다
                source = list(source_documents())
                outbox_pairs = list(events.outbox_documents())
            mongo = list(events.mongo_documents())  # ③ 은 스냅샷 밖이다 — 중계가 진행 중이면 그 창이 잠시 어긋날 수 있다(verify_hops 가 구분한다)
        except (PyMongoError, events.NotConfigured) as error:
            raise CommandError(f"MongoDB 를 읽지 못했습니다: {type(error).__name__}: {str(error)[:200]}")
        comparable_from = events.window_start(now - timedelta(days=settings.EVENTS_OUTBOX_RETENTION_DAYS))  # 보존 정리가 닿지 않은 창만 outbox 와 대조한다
        outbox = [doc for doc, _ in outbox_pairs]
        unsent = events.unsent_counts(outbox_pairs)
        out = Path(options["out"])
        anchors = {}
        for hop, docs in (("hop_source", source), ("hop_outbox", outbox), ("hop_mongo", mongo)):
            lines, open_windows = events.summarize(docs, now, grace, since)
            extra = {}
            if hop == "hop_outbox":
                skipped = sorted({line["window_start"] for line in lines if _parse(line["window_start"]) < comparable_from})
                lines = [line for line in lines if _parse(line["window_start"]) >= comparable_from]
                for line in lines:
                    line["unsent"] = unsent.get((line["window_start"], line["event_name"]), 0)  # 중계 지연 후보를 가리는 데 쓴다
                extra = {"not_comparable_windows": skipped, "comparable_from": comparable_from.strftime("%Y-%m-%dT%H:%M:%SZ")}
            checkpoint = {
                "scope": SCOPE if hop != "hop_mongo" else "mongodb-read-outside-snapshot", "hop": hop, "window": "utc-day", "grace_seconds": grace, "started_at": now.isoformat(),
                "since": options["since"], "open_windows": [w.strftime("%Y-%m-%dT%H:%M:%SZ") for w in open_windows], "scanned_events": len(docs), **extra,
            }
            manifest = events.write_ndjson(out, hop, lines, hop, SCHEMA_VERSION, checkpoint=checkpoint, now=now, chain=True)
            anchors[hop] = events.manifest_sha256(events.manifest_path(out, hop))
            self.stdout.write(f"{hop}: rows={manifest['rows']} events={len(docs)} open_windows={len(open_windows)} file={manifest['file']}")
        record_audit(None, "events.hop_manifests_exported", detail={"anchors": anchors, "since": options["since"], "grace_seconds": grace})  # 폴더 밖의 고정점(H12)


def _parse(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
