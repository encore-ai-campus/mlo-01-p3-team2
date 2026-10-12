"""Step 4-3a: 이벤트 백필 — 이벤트가 없는 원본 행에 원본에서 이벤트를 다시 만들어 채운다. 라이브 이벤트와 같고, 멱등이며, 추측하지 않는다."""
import io
import json
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from random import Random
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase, tag

from events import ndjson, store
from events.models import EventOutbox
from events.relay import relay_batch
from foundation.models import AuditLog
from records import api as records
from records.processing import parse_reaction_ref, reaction_ref
from records.models import Reaction
from tests.factories import NOW, SUBJECT, World
from tests.mongo_support import MongoDatabaseMixin
from tests.test_event_invariants import load_test


def snapshot(rows):
    return {r.pk: (r.event_name, r.schema_version, r.aggregate_id, r.created_at, r.payload) for r in rows}


@tag("security")
class BackfillTests(MongoDatabaseMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        store.ensure()
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        w = World()
        self.decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(w.slot.media_id, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW + timedelta(seconds=7))  # 처리 시각 ≠ 수신 시각
        self.inbox_id = view.inbox_id
        self.live = snapshot(EventOutbox.objects.all())  # 라이브 경로가 만든 이벤트 4건 = 백필이 재현해야 할 기준
        self.assertEqual(len(self.live), 4)

    # ------------------------------------------------------------------ 도우미
    def gaps_manifest(self, name="gaps"):
        out = self.dir / name
        try:
            call_command("export_integrity", "--out", str(out), stdout=io.StringIO())
        except CommandError:
            pass  # 누락이 있으면 비정상 종료하지만 결과는 게시된다
        return ndjson.manifest_path(out, "event_gaps")

    def run_backfill(self, manifest, *flags, out="res"):
        stdout = io.StringIO()
        try:
            call_command("backfill_events", "--input", str(manifest), "--out", str(self.dir / out), *flags, stdout=stdout)
            return True, stdout.getvalue()
        except CommandError as error:
            return False, stdout.getvalue() + str(error)

    def result_rows(self, out="res"):
        manifest = ndjson.read_manifest(ndjson.manifest_path(self.dir / out, "backfill_result"))
        return [json.loads(line) for line in (self.dir / out / manifest["file"]).read_text().splitlines()], manifest

    def wipe(self):
        EventOutbox.objects.all().delete()  # Step 4 이전에 쌓인 행처럼 이벤트가 없다

    # ------------------------------------------------------------------ 본체
    def test_dry_run_is_the_default_and_writes_nothing(self):
        self.wipe()
        ok, text = self.run_backfill(self.gaps_manifest())
        self.assertTrue(ok, text)
        self.assertEqual(EventOutbox.objects.count(), 0)
        rows, manifest = self.result_rows()
        self.assertEqual({r["outcome"] for r in rows}, {"would_write"})
        self.assertEqual((len(rows), manifest["checkpoint"]["mode"], manifest["checkpoint"]["counts"]["would_write"]), (4, "dry-run", 4))
        self.assertEqual(AuditLog.objects.filter(action="events.backfilled").count(), 0)  # 읽기만 했다

    def test_apply_recreates_exactly_the_events_the_live_path_made(self):
        self.wipe()
        ok, text = self.run_backfill(self.gaps_manifest(), "--apply")
        self.assertTrue(ok, text)
        self.assertEqual(snapshot(EventOutbox.objects.all()), self.live)  # 이름·버전·메시지 키·생성 시각·페이로드가 라이브와 같다
        rows, manifest = self.result_rows()
        self.assertEqual({r["outcome"] for r in rows}, {"written"})
        self.assertEqual(manifest["checkpoint"]["counts"]["written"], 4)

    def test_after_backfill_the_gap_check_and_the_event_verifier_are_clean(self):
        self.wipe()
        self.run_backfill(self.gaps_manifest(), "--apply")
        out = self.dir / "after"
        call_command("export_integrity", "--out", str(out), stdout=io.StringIO())  # 문제 없으면 정상 종료
        self.assertEqual(ndjson.read_manifest(ndjson.manifest_path(out, "event_gaps"))["rows"], 0)
        self.assertEqual(load_test.verify_events(), [])
        relay_batch()
        self.assertEqual(load_test.verify_events(relayed=True), [])  # 중계가 평소처럼 MongoDB 로 보낸다

    def test_running_it_twice_adds_nothing(self):
        self.wipe()
        manifest = self.gaps_manifest()
        self.run_backfill(manifest, "--apply", out="r1")
        before = snapshot(EventOutbox.objects.all())
        ok, text = self.run_backfill(manifest, "--apply", out="r2")
        self.assertTrue(ok, text)
        self.assertEqual(snapshot(EventOutbox.objects.all()), before)
        rows, _ = self.result_rows("r2")
        self.assertEqual({r["outcome"] for r in rows}, {"already_present"})

    def test_events_the_live_path_made_in_the_meantime_are_not_written_again(self):
        """목록을 만든 뒤 라이브가 일부를 먼저 만든 경우: 그것은 건드리지 않고 나머지만 쓴다."""
        self.wipe()
        manifest = self.gaps_manifest()
        keep = next(iter(self.live))
        row = self.live[keep]
        EventOutbox.objects.create(event_id=keep, event_name=row[0], schema_version=row[1], aggregate_id=row[2], created_at=row[3], payload=row[4])
        self.run_backfill(manifest, "--apply")
        rows, _ = self.result_rows()
        self.assertEqual(sorted(r["outcome"] for r in rows), ["already_present", "written", "written", "written"])
        self.assertEqual(snapshot(EventOutbox.objects.all()), self.live)

    def test_events_that_exist_only_in_mongodb_after_purge_are_not_rewritten(self):
        relay_batch()
        EventOutbox.objects.all().delete()  # 보낸 뒤 보존 기간이 지나 outbox 에서 지워졌다
        manifest = self.gaps_manifest()
        self.assertEqual(ndjson.read_manifest(manifest)["rows"], 0)  # 누락이 아니다
        # 일부러 목록에 넣어도 MongoDB 에 있으면 다시 쓰지 않는다
        one = next(iter(self.live))
        forged = ndjson.write(self.dir / "forged", "event_gaps", [{"kind": "missing_event", "event_name": self.live[one][0], "source_kind": self.kind_of(self.live[one][0]),
                                                                  "source_id": str(self.source_of(one)), "event_id": str(one)}], "event_gaps", 1)
        ok, _ = self.run_backfill(ndjson.manifest_path(self.dir / "forged", "event_gaps"), "--apply")
        self.assertTrue(ok)
        rows, _ = self.result_rows()
        self.assertEqual([r["outcome"] for r in rows], ["already_present"])
        self.assertEqual(EventOutbox.objects.count(), 0)
        self.assertEqual(forged["rows"], 1)

    def kind_of(self, event_name):
        return {"ad.decision": "decision", "ad.reaction_received": "reaction", "ad.reaction": "reaction", "ad.charge": "ledger_charge"}[event_name]

    def source_of(self, event_id):
        from billing.models import LedgerEntry

        name = self.live[event_id][0]
        return {"ad.decision": self.decision.decision_id, "ad.reaction_received": self.inbox_id, "ad.reaction": self.inbox_id,
                "ad.charge": LedgerEntry.objects.get(entry_type="CHARGE").entry_id}[name]

    # ------------------------------------------------------------------ 입력을 믿지 않는다
    def forged_manifest(self, records_in, name="forged"):
        ndjson.write(self.dir / name, "event_gaps", records_in, "event_gaps", 1)
        return ndjson.manifest_path(self.dir / name, "event_gaps")

    def line(self, eid, **override):
        name = self.live[eid][0]
        return {"kind": "missing_event", "event_name": name, "source_kind": self.kind_of(name), "source_id": str(self.source_of(eid)), "event_id": str(eid), **override}

    def test_a_tampered_input_file_is_refused_and_nothing_is_written(self):
        self.wipe()
        manifest = self.gaps_manifest()
        data = self.dir / "gaps" / ndjson.read_manifest(manifest)["file"]
        data.write_bytes(data.read_bytes() + b'{"x":1}\n')
        ok, text = self.run_backfill(manifest, "--apply")
        self.assertFalse(ok)
        self.assertIn("검증 실패", text)
        self.assertEqual(EventOutbox.objects.count(), 0)

    def test_an_input_that_is_not_an_event_gaps_manifest_is_refused(self):
        out = self.dir / "other"
        ndjson.write(out, "ledger_check", [], "ledger_check", 1)
        ok, text = self.run_backfill(ndjson.manifest_path(out, "ledger_check"), "--apply")
        self.assertFalse(ok)
        self.assertIn("event_gaps", text)

    def test_a_forged_event_id_is_refused(self):
        """목록에 적힌 event_id 가 원천 ID 에서 다시 계산한 값과 다르면 거부한다 — 목록의 값을 믿지 않는다."""
        self.wipe()
        any_id = next(iter(self.live))
        ok, text = self.run_backfill(self.forged_manifest([self.line(any_id, event_id=str(uuid.uuid4()))]), "--apply")
        self.assertFalse(ok)
        self.assertIn("다시 계산한 값과 다르다", text)
        self.assertEqual(EventOutbox.objects.count(), 0)

    def test_a_mismatched_event_name_and_source_kind_is_refused(self):
        self.wipe()
        any_id = next(iter(self.live))
        ok, text = self.run_backfill(self.forged_manifest([self.line(any_id, source_kind="ledger_charge" if self.kind_of(self.live[any_id][0]) != "ledger_charge" else "decision")]), "--apply")
        self.assertFalse(ok)
        self.assertIn("맞지 않는다", text)

    def test_a_source_id_that_does_not_exist_is_unresolved_not_invented(self):
        self.wipe()
        ghost = uuid.uuid4()
        from events import schemas

        record = {"kind": "missing_event", "event_name": "ad.decision", "source_kind": "decision", "source_id": str(ghost),
                  "event_id": str(schemas.event_id_of("ad.decision", ghost))}
        ok, text = self.run_backfill(self.forged_manifest([record]), "--apply")
        self.assertFalse(ok)  # 해석 불가는 비정상 종료
        rows, _ = self.result_rows()
        self.assertEqual((rows[0]["outcome"], rows[0]["reason"]), ("unresolved", "원본 결정이 없다"))
        self.assertEqual(EventOutbox.objects.count(), 0)  # 없는 사실의 이벤트를 만들지 않는다

    def test_a_charge_whose_reaction_cannot_be_found_is_unresolved_and_the_rest_is_still_written(self):
        """과금의 결정은 추측하지 않는다 — 반응을 못 찾으면 해석 불가. 나머지 항목은 계속 쓴다."""
        self.wipe()
        manifest = self.gaps_manifest()
        Reaction.objects.filter(pk=self.inbox_id).delete()
        ok, text = self.run_backfill(manifest, "--apply")
        self.assertFalse(ok)
        rows, _ = self.result_rows()
        by_name = {r["event_name"]: r for r in rows}
        self.assertEqual(by_name["ad.charge"]["outcome"], "unresolved")
        self.assertIn("추측하지 않는다", by_name["ad.charge"]["reason"])
        self.assertEqual(by_name["ad.reaction"]["outcome"], "unresolved")
        self.assertEqual(by_name["ad.decision"]["outcome"], "written")
        self.assertEqual(EventOutbox.objects.filter(event_name="ad.charge").count(), 0)

    def test_a_reaction_that_is_not_judged_yet_gets_no_judged_event(self):
        w = World()
        decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(2))
        pending, _ = records.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        from events import schemas

        record = {"kind": "missing_event", "event_name": "ad.reaction", "source_kind": "reaction", "source_id": str(pending.inbox_id),
                  "event_id": str(schemas.event_id_of("ad.reaction", pending.inbox_id))}
        before = EventOutbox.objects.count()
        ok, _ = self.run_backfill(self.forged_manifest([record]), "--apply")
        self.assertTrue(ok)  # 해석 불가가 아니다: 판정이 라이브로 만든다
        rows, _ = self.result_rows()
        self.assertEqual(rows[0]["outcome"], "skipped_not_judged")
        self.assertEqual(EventOutbox.objects.count(), before)

    def test_a_legacy_basis_is_written_but_counted_separately(self):
        self.wipe()
        Reaction.objects.filter(pk=self.inbox_id).update(basis={"v": 0, "legacy": {"note": "2-13 이전"}})
        manifest = self.gaps_manifest()
        ok, _ = self.run_backfill(manifest, "--apply")
        self.assertTrue(ok)
        rows, result_manifest = self.result_rows()
        judged = next(r for r in rows if r["event_name"] == "ad.reaction")
        self.assertEqual((judged["outcome"], judged["legacy_basis"]), ("written", True))
        self.assertEqual(result_manifest["checkpoint"]["counts"]["legacy_basis"], 1)
        self.assertTrue(EventOutbox.objects.filter(event_name="ad.reaction").exists())

    # ------------------------------------------------------------------ 안전장치
    def test_each_chunk_is_atomic_with_its_audit_log(self):
        self.wipe()
        manifest = self.gaps_manifest()
        real, calls = EventOutbox.objects.bulk_create, []

        def fail_on_third(objs, *a, **k):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("세 번째 이벤트 쓰기 실패")
            return real(objs, *a, **k)

        with mock.patch.object(EventOutbox.objects, "bulk_create", fail_on_third):
            with self.assertRaises(RuntimeError):
                records.backfill_events(manifest, apply=True, chunk=2)
        self.assertEqual(EventOutbox.objects.count(), 2)  # 첫 청크(2건)는 커밋됐고 실패한 청크는 통째로 되돌려졌다
        audits = AuditLog.objects.filter(action="events.backfilled")
        self.assertEqual(sum(a.detail["written"] for a in audits), 2)  # 감사 로그도 커밋된 청크만큼
        result = records.backfill_events(manifest, apply=True, chunk=2)  # 다시 돌리면 나머지만 쓴다
        self.assertEqual(result.counts()["written"], 2)
        self.assertEqual(snapshot(EventOutbox.objects.all()), self.live)

    def test_each_chunk_has_its_own_audit_entry_numbered_from_zero(self):
        self.wipe()
        records.backfill_events(self.gaps_manifest(), apply=True, chunk=3)  # 4건 → 3 + 1(덜 찬 마지막 청크)
        audits = AuditLog.objects.filter(action="events.backfilled").order_by("created_at", "log_id")
        self.assertEqual([(a.detail["chunk"], a.detail["written"]) for a in audits], [(0, 3), (1, 1)])

    def test_the_audit_log_records_the_input_and_the_counts(self):
        self.wipe()
        manifest = self.gaps_manifest()
        self.run_backfill(manifest, "--apply")
        (audit,) = AuditLog.objects.filter(action="events.backfilled")
        self.assertEqual((audit.detail["written"], audit.detail["input_sha256"]), (4, ndjson.read_manifest(manifest)["sha256"]))
        self.assertEqual(audit.actor_id, None)  # 시스템 작업

    def test_the_result_file_is_published_and_verifies(self):
        self.wipe()
        self.run_backfill(self.gaps_manifest(), "--apply")
        self.assertEqual(ndjson.verify(ndjson.manifest_path(self.dir / "res", "backfill_result")), [])
        _, manifest = self.result_rows()
        self.assertEqual(manifest["source_kind"], "backfill_result")
        self.assertEqual(len(manifest["checkpoint"]["input_sha256"]), 64)

    def test_mongodb_unreachable_refuses_instead_of_guessing(self):
        from django.test import override_settings

        from events import mongo

        self.wipe()
        manifest = self.gaps_manifest()
        with override_settings(EVENT_STORE={**mongo.config(), "HOSTS": ["127.0.0.1:1"], "REPLICA_SET": None}):
            mongo.close()
            ok, text = self.run_backfill(manifest, "--apply")
            mongo.close()
        self.assertFalse(ok)
        self.assertIn("MongoDB", text)
        self.assertEqual(EventOutbox.objects.count(), 0)


class ReactionRefFormatTests(SimpleTestCase):
    """원장 멱등 키 `<매체>:<reaction_id>` 를 만들고 해석하는 한 쌍(계획 4-4c — 잘못된 키의 처리는 옮기기 전 `backfill._parse_ref` 의 동작을 고정한 특성 시험). 해석하지 못하면 `None` — 백필은 결정을 추측하지 않는다."""

    def test_a_ref_made_from_a_reaction_parses_back(self):
        media_id, reaction_id = uuid.uuid4(), uuid.uuid4()
        self.assertEqual(reaction_ref(media_id, reaction_id), f"{media_id}:{reaction_id}")
        self.assertEqual(parse_reaction_ref(reaction_ref(media_id, reaction_id)), (media_id, reaction_id))

    def test_malformed_refs_do_not_parse(self):
        good = str(uuid.uuid4())
        for ref in (good, "", f"{good}{good}", f"{good}:", f":{good}", f"{good}:not-a-uuid", f"not-a-uuid:{good}", f"{good}:{good}:{good}", f"{good};{good}", None, 12):
            self.assertIsNone(parse_reaction_ref(ref), ref)
