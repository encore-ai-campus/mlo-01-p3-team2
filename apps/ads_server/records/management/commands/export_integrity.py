import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from pymongo.errors import PyMongoError

from billing.api import check_ledger
from events import api as events
from records.api import event_gaps

LEDGER_SCHEMA_VERSION = 1
GAPS_SCHEMA_VERSION = 1


class Command(BaseCommand):
    help = (
        "정합성 점검 결과를 NDJSON + manifest 로 낸다: ledger_check(잔액·원장·일 소진액 불일치), event_gaps(이벤트가 없는 원본 행). "
        "한 줄 = 문제 하나이고, 문제가 없으면 행 수 0 의 파일이 점검했다는 증거다. 문제가 하나라도 있으면 비정상 종료한다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="결과를 쓸 폴더(없으면 만든다)")

    def handle(self, *args, **options):
        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)
        started = datetime.now(timezone.utc)
        checkpoint = f"scanned-before:{started.isoformat()}"  # 이 시각 뒤에 생긴 원본 행은 점검 대상이 아니다
        total = 0
        total += self.export(out / "ledger_check.ndjson", ({"kind": "ledger_problem", "message": m} for m in check_ledger()), "ledger_check", LEDGER_SCHEMA_VERSION, checkpoint, started)
        try:
            gaps = list(event_gaps())  # 끝까지 읽은 뒤에 쓴다 — MongoDB 오류로 중간에 끊긴 불완전한 목록이 파일이 되지 않게
        except (PyMongoError, events.NotConfigured) as error:
            raise CommandError(f"이벤트 누락을 점검하지 못했습니다(MongoDB): {type(error).__name__}: {str(error)[:200]}")
        total += self.export(out / "event_gaps.ndjson", gaps, "event_gaps", GAPS_SCHEMA_VERSION, checkpoint, started)
        if total:
            raise CommandError(f"문제 {total}건 — 위 파일을 확인하세요.")

    def export(self, path, records, source_kind, schema_version, checkpoint, now):
        manifest = events.write_ndjson(path, records, source_kind, schema_version, checkpoint=checkpoint, now=now)
        self.stdout.write(f"{manifest['file']}: rows={manifest['rows']} sha256={manifest['sha256'][:12]}… {json.dumps(manifest['source_kind'])}")
        return manifest["rows"]
