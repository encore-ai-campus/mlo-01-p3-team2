from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from pymongo.errors import PyMongoError

from billing.api import check_ledger, consistent_read
from events import api as events
from records.api import event_gaps

SCHEMA_VERSION = 1
SCOPE = "mysql-repeatable-read-snapshot"


class Command(BaseCommand):
    help = (
        "정합성 점검 결과를 NDJSON + manifest 로 낸다: ledger_check(잔액·원장·일 소진액 불일치), event_gaps(이벤트가 없는 원본 행 = 백필 대상), "
        "event_delivery(보냈다고 표시됐지만 MongoDB 에 없는 이벤트). 한 줄 = 문제 하나이고, 문제가 없으면 행 수 0 의 파일이 점검했다는 증거다. 문제가 하나라도 있으면 비정상 종료한다. "
        "세 점검은 **하나의 MySQL 읽기 스냅샷**을 보고, manifest 의 checkpoint 에 그 범위(훑은 행 수)가 남는다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="결과를 쓸 폴더(없으면 만든다)")

    def handle(self, *args, **options):
        out = Path(options["out"])
        started = datetime.now(timezone.utc)
        scanned = {}
        try:
            with consistent_read():  # 이 안의 모든 MySQL 읽기가 한 스냅샷을 본다 — 점검 도중 새로 쌓이는 행이 거짓 누락·불일치가 되지 않는다
                ledger = [{"kind": "ledger_problem", "message": m} for m in check_ledger(quiescent=True)]
                gaps = list(event_gaps(scanned))  # 끝까지 읽은 뒤에 쓴다 — 중간에 끊긴 불완전한 목록이 파일이 되지 않게
                undelivered = [{"kind": "sent_not_in_mongo", "event_id": str(i)} for i in events.sent_but_not_in_mongo(limit=None)]
        except (PyMongoError, events.NotConfigured) as error:
            raise CommandError(f"이벤트를 점검하지 못했습니다(MongoDB): {type(error).__name__}: {str(error)[:200]}")
        checkpoint = {"scope": SCOPE, "started_at": started.isoformat(), "scanned": scanned}  # 범위 서술이다. 이어서 읽을 위치가 아니다(점검은 항상 전체)
        total = 0
        for name, rows in (("ledger_check", ledger), ("event_gaps", gaps), ("event_delivery", undelivered)):
            manifest = events.write_ndjson(out, name, rows, name, SCHEMA_VERSION, checkpoint=checkpoint, now=started)
            self.stdout.write(f"{name}: rows={manifest['rows']} file={manifest['file']} sha256={manifest['sha256'][:12]}…")
            total += manifest["rows"]
        if total:
            raise CommandError(f"문제 {total}건 — 위 파일을 확인하세요.")
