from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from pymongo.errors import PyMongoError

from events import api as events
from records.api import BackfillInvalidInput, backfill_events

SCHEMA_VERSION = 1


class Command(BaseCommand):
    help = (
        "이벤트가 없는 원본 행에 이벤트를 채운다(백필). 입력은 export_integrity 가 낸 event_gaps manifest(검증을 통과해야 한다). "
        "이벤트 내용은 목록이 아니라 원본 행에서 다시 만든다. 기본은 --dry-run(쓰지 않고 무엇을 쓸지만 센다), --apply 를 줘야 outbox 에 쓴다. "
        "결과는 NDJSON + manifest(backfill_result)로 낸다. 해석할 수 없는 항목이 있으면 비정상 종료한다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True, help="event_gaps manifest 경로(<이름>.manifest.json)")
        parser.add_argument("--out", required=True, help="결과를 쓸 폴더")
        parser.add_argument("--apply", action="store_true", help="실제로 outbox 에 쓴다(없으면 dry-run)")
        parser.add_argument("--chunk", type=int, default=500, help="한 트랜잭션에 처리할 항목 수. 기본 500")

    def handle(self, *args, **options):
        if options["chunk"] < 1:
            raise CommandError("--chunk 는 1 이상이어야 합니다.")
        started = datetime.now(timezone.utc)
        try:
            result = backfill_events(options["input"], apply=options["apply"], chunk=options["chunk"])
        except BackfillInvalidInput as error:
            raise CommandError(f"입력을 쓸 수 없습니다: {error}")
        except (PyMongoError, events.NotConfigured) as error:
            raise CommandError(f"이벤트 존재를 확인하지 못했습니다(MongoDB): {type(error).__name__}: {str(error)[:200]}")
        counts = result.counts()
        checkpoint = {"mode": "apply" if result.applied else "dry-run", "input_sha256": result.input_sha256, "counts": counts}
        manifest = events.write_ndjson(Path(options["out"]), "backfill_result", [o.as_record() for o in result.outcomes], "backfill_result", SCHEMA_VERSION, checkpoint=checkpoint, now=started)
        self.stdout.write(f"{checkpoint['mode']}: {counts} file={manifest['file']} sha256={manifest['sha256'][:12]}…")
        if counts["unresolved"]:
            raise CommandError(f"해석할 수 없는 항목 {counts['unresolved']}건 — 결과 파일을 확인하세요.")
