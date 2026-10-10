import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from events import hopcheck, ndjson
from foundation.api import latest_audit_detail

SCHEMA_VERSION = 1
HOP_FILES = ("hop_source", "hop_outbox", "hop_mongo")


class Command(BaseCommand):
    help = (
        "구간별 정합 manifest(export_hop_manifests 가 낸 폴더)를 대조한다: 원본→outbox, outbox→MongoDB, 원본→MongoDB. 각 manifest 의 SHA-256·행 수와 세대 사슬을 검증하고, "
        "최신 manifest 가 감사 로그의 고정점과 같은지 본다. --pipeline 으로 파이프라인 쪽이 같은 규칙으로 낸 manifest 를 MongoDB 구간과도 대조한다. "
        "확정 불일치·사슬 오류·고정점 불일치가 있으면 비정상 종료한다(중계 지연 후보는 보고만 하고 다시 확인한다)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dir", required=True, help="export_hop_manifests 의 출력 폴더")
        parser.add_argument("--out", help="대조 결과(NDJSON + manifest)를 낼 폴더")
        parser.add_argument("--pipeline", help="파이프라인 쪽 구간 manifest 경로(MongoDB 구간과 대조)")
        parser.add_argument("--no-anchor", action="store_true", help="감사 로그의 고정점과 대조하지 않는다(다른 환경에서 받은 폴더를 볼 때)")

    def handle(self, *args, **options):
        directory = Path(options["dir"])
        errors, hops = [], {}
        for name in HOP_FILES:
            path = ndjson.manifest_path(directory, name)
            try:
                hops[name] = hopcheck.load_hop(path, name)
            except hopcheck.HopInputError as error:
                errors.append(f"{name}: {error}")
                continue
            errors += [f"{name}: 세대 사슬 — {p}" for p in ndjson.verify_chain(path)]
        if not options["no_anchor"] and not errors:
            anchors = (latest_audit_detail("events.hop_manifests_exported") or {}).get("anchors")
            if anchors is None:
                errors.append("감사 로그에 고정점이 없다(export_hop_manifests 를 한 번도 실행하지 않았거나 다른 환경의 폴더다 — --no-anchor)")
            else:
                for name in HOP_FILES:
                    if anchors.get(name) != ndjson.manifest_sha256(ndjson.manifest_path(directory, name)):
                        errors.append(f"{name}: 최신 manifest 가 감사 로그의 고정점과 다르다(폴더가 마지막 실행 뒤에 바뀌었다)")
        rows = []
        if len(hops) == len(HOP_FILES):
            source, outbox, mongo = (hops[n] for n in HOP_FILES)
            rows += hopcheck.compare(source, outbox) + hopcheck.compare(outbox, mongo) + hopcheck.compare(source, mongo, unsent_from=outbox)
        if options["pipeline"]:
            try:
                pipeline = hopcheck.load_hop(options["pipeline"], "pipeline")
            except hopcheck.HopInputError as error:
                errors.append(f"pipeline: {error}")
            else:
                if "hop_mongo" in hops:
                    rows += hopcheck.compare(hops["hop_mongo"], pipeline, unsent_from=hops.get("hop_outbox"))
        counts = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        for line in errors:
            self.stdout.write(f"FAIL {line}")
        for row in rows:
            if row["status"] in (hopcheck.MISMATCH, hopcheck.LAG):
                self.stdout.write(f"{'FAIL' if row['status'] == hopcheck.MISMATCH else 'LAG '} {row['pair']} {row['window_start']} {row['event_name']} {row['fields']}")
        self.stdout.write(f"결과: {counts or '비교한 줄 없음'}")
        if options["out"]:
            checkpoint = {"counts": counts, "errors": errors, "inputs": {n: h.manifest["sha256"] for n, h in hops.items()}}
            manifest = ndjson.write(Path(options["out"]), "hop_report", rows, "hop_report", SCHEMA_VERSION, checkpoint=checkpoint, now=datetime.now(timezone.utc))
            self.stdout.write(f"hop_report: rows={manifest['rows']} file={manifest['file']}")
        if errors or counts.get(hopcheck.MISMATCH):
            raise CommandError(f"구간 대조 실패 — 오류 {len(errors)}건, 확정 불일치 {counts.get(hopcheck.MISMATCH, 0)}건")
