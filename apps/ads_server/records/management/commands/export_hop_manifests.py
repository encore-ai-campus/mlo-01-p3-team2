import resource
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pymongo.errors import PyMongoError

from billing.api import consistent_read
from events import api as events
from foundation.api import record_audit
from records.api import source_streams, unresolved_charges

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
        parser.add_argument("--window", choices=sorted(events.WINDOWS), default="day", help="창의 크기: day(UTC 자정 고정 하루, 기본) 또는 hour(UTC 정시 고정 한 시간)")
        parser.add_argument("--as-of", help="재현용: 이 시각(ISO 8601, UTC)을 '지금'으로 보고 창을 닫는다(기본은 실제 지금). 시험이 날짜가 바뀐 뒤의 점검을 재현할 때 쓴다")

    def handle(self, *args, **options):
        since = None
        if options["since"]:
            try:
                since = datetime.combine(date.fromisoformat(options["since"]), datetime.min.time(), tzinfo=timezone.utc)
            except ValueError:
                raise CommandError("--since 는 YYYY-MM-DD 형식이어야 합니다.")
        size = events.WINDOWS[options["window"]]
        try:
            now = datetime.fromisoformat(options["as_of"]).astimezone(timezone.utc) if options["as_of"] else datetime.now(timezone.utc)
        except ValueError:
            raise CommandError("--as-of 는 ISO 8601 시각이어야 합니다.")
        grace = settings.EVENTS_HOP_GRACE_SECONDS
        try:
            # 구간마다 닫힌 창을 하나씩·종류별로 읽어 요약한다 — 전체 이력을 메모리에 두지 않고, 열린 창과 --since 앞은 읽지 않는다(외부 검토 7936ac7 P3-3)
            with consistent_read():  # 원본(①)과 outbox(②)는 같은 스냅샷을 본다
                results = {"hop_source": events.summarize_windows(source_streams(), now, grace, since, size),
                           "hop_outbox": events.summarize_windows(events.outbox_streams(), now, grace, since, size)}
                unsent = events.unsent_counts(size)
                unresolved, examples = unresolved_charges()  # 창에 놓을 수 없는 과금 원장 줄 — 원본 구간에서 빠지므로 따로 센다(외부 검토 4bd3ce8 P2)
            results["hop_mongo"] = events.summarize_windows(events.mongo_streams(), now, grace, since, size)  # ③ 은 스냅샷 밖이다 — 중계가 진행 중이면 그 창이 잠시 어긋날 수 있다(verify_hops 가 구분한다)
        except (PyMongoError, events.NotConfigured) as error:
            raise CommandError(f"MongoDB 를 읽지 못했습니다: {events.mongo_error_text(error)}")
        # 보존 정리는 보낸 지 EVENTS_OUTBOX_RETENTION_DAYS 가 지난 행을 지운다. 시작이 이 기준 시각 이후인 창의 행은 (생성 ≤ 전송 이므로) 한 줄도 지워지지 않았다.
        # 기준 시각이 창의 한가운데에 걸리면 그 창의 앞부분은 지워졌을 수 있으므로 창 전체를 뺀다. 판정은 행이 남아 있는지가 아니라 **보존 범위와 창 경계**로 한다
        # (오래된 창의 행이 모두 지워져도 '대조 제외' 정보가 사라지지 않게).
        cutoff = now - timedelta(days=settings.EVENTS_OUTBOX_RETENTION_DAYS)
        summaries = {hop: (lines, open_windows) for hop, (lines, open_windows, _read, _largest) in results.items()}
        scanned = {hop: read for hop, (_lines, _open, read, _largest) in results.items()}  # 읽은 이벤트 수(범위 안의 닫힌 창)
        starts = {line["window_start"] for lines, _ in summaries.values() for line in lines}  # 어느 구간에든 있는 닫힌 창
        not_comparable = sorted(start for start in starts if events.parse_time(start) < cutoff)
        out = Path(options["out"])
        with events.run_lock(out):  # 세 manifest 게시부터 감사 로그 커밋까지가 한 단위 — 겹친 실행이 최신 감사 고정점과 최종 포인터를 엇갈리게 하지 않는다
            anchors = {}
            for hop, (lines, open_windows) in summaries.items():
                extra = {"unresolved_charges": unresolved, "unresolved_charge_examples": examples} if hop == "hop_source" else {}
                if hop == "hop_outbox":
                    lines = [line for line in lines if line["window_start"] not in not_comparable]
                    for line in lines:
                        line["unsent"] = unsent.get((line["window_start"], line["event_name"]), 0)  # 중계 지연 후보를 가리는 데 쓴다
                    extra = {"not_comparable_windows": not_comparable, "retention_cutoff": events.format_time(cutoff)}
                checkpoint = {
                    "scope": SCOPE if hop != "hop_mongo" else "mongodb-read-outside-snapshot", "hop": hop, "window": events.window_label(options["window"]), "grace_seconds": grace, "started_at": now.isoformat(),
                    "since": options["since"], "open_windows": [events.format_time(w) for w in open_windows], "scanned_events": scanned[hop], **extra,
                }
                manifest = events.write_ndjson(out, hop, lines, hop, events.HOP_SCHEMA_VERSION, checkpoint=checkpoint, now=now, chain=True)
                anchors[hop] = events.manifest_digest(manifest)  # 이 실행이 게시한 manifest 의 해시(포인터를 다시 읽지 않는다)
                self.stdout.write(f"{hop}: rows={manifest['rows']} events={scanned[hop]} open_windows={len(open_windows)} largest_window={results[hop][3]} file={manifest['file']}")
            record_audit(None, "events.hop_manifests_exported", detail={"anchors": anchors, "since": options["since"], "grace_seconds": grace})  # 폴더 밖의 고정점(H12)
        self.stdout.write(f"peak_rss={peak_rss_mib():.1f}MiB")
        if unresolved:  # 게시는 한다(나머지 대조는 계속된다). 실패로 끝내고 verify_hops 도 실패로 본다
            raise CommandError(f"창에 놓을 수 없는 과금 원장 줄 {unresolved}건 — 반응이 없거나 판정 전이라 생성 시각을 정할 수 없다(추정하지 않는다). 예: {', '.join(examples)}")  # 이 프로세스의 최대 상주 메모리 — 이력이 쌓여도 늘지 않아야 한다(창 하나·종류 하나만 든다)


def peak_rss_mib():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (2**20 if sys.platform == "darwin" else 2**10)  # macOS 는 바이트, Linux 는 KiB
