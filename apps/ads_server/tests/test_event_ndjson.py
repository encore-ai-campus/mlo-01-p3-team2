"""Step 4-2: NDJSON + manifest(원자적 확정·검증)와 이벤트 누락 점검·점검 결과 내보내기."""
import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from random import Random
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, TransactionTestCase, tag

from billing.models import LedgerEntry
from events import api as events
from events import ndjson, store
from events.models import EventOutbox
from events.relay import relay_batch
from records import api as records
from tests.factories import NOW, SUBJECT, World
from tests.mongo_support import MongoDatabaseMixin, unreachable_store

T = datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc)


class TempDirMixin:
    def tmpdir(self):
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)


@tag("security")
class WriteAndVerifyTests(TempDirMixin, SimpleTestCase):
    def publish(self, directory, rows, name="check", **kw):
        return ndjson.write(directory, name, rows, kw.pop("source_kind", "ledger_check"), kw.pop("schema_version", 3), now=T, **kw)

    def test_manifest_points_at_an_immutable_generation_and_describes_it_exactly(self):
        directory = self.tmpdir()
        records_in = [{"a": 1, "한글": "값"}, {"b": [1, 2]}]
        manifest = self.publish(directory, records_in, checkpoint={"scope": "x"})
        data = (directory / manifest["file"]).read_bytes()
        self.assertEqual(manifest["file"], f"check.{hashlib.sha256(data).hexdigest()[:16]}.ndjson")  # 이름에 내용의 해시가 들어간다
        self.assertEqual(data.decode("utf-8").count("\n"), 2)  # 한 줄 = 레코드 하나, 줄바꿈으로 끝난다
        self.assertEqual((manifest["sha256"], manifest["rows"], manifest["schema_version"], manifest["source_kind"], manifest["checkpoint"]),
                         (hashlib.sha256(data).hexdigest(), 2, 3, "ledger_check", {"scope": "x"}))
        self.assertEqual(manifest["created_at"], "2026-10-10T03:00:00+00:00")
        self.assertEqual(json.loads(ndjson.manifest_path(directory, "check").read_text()), manifest)
        self.assertEqual([json.loads(line) for line in data.decode("utf-8").splitlines()], records_in)
        self.assertEqual(ndjson.verify(ndjson.manifest_path(directory, "check")), [])

    def test_an_empty_result_is_a_valid_proof_of_a_clean_check(self):
        directory = self.tmpdir()
        manifest = self.publish(directory, [], name="gaps", source_kind="event_gaps")
        self.assertEqual(((directory / manifest["file"]).read_bytes(), manifest["rows"], ndjson.verify(ndjson.manifest_path(directory, "gaps"))), (b"", 0, []))

    def test_a_new_publication_never_overwrites_the_previous_generation(self):
        directory = self.tmpdir()
        first = self.publish(directory, [{"n": 1}])
        second = self.publish(directory, [{"n": 2}])
        self.assertNotEqual(first["file"], second["file"])
        self.assertTrue((directory / first["file"]).exists() and (directory / second["file"]).exists())  # 이전 세대가 그대로 있다
        self.assertEqual(ndjson.read_manifest(ndjson.manifest_path(directory, "check"))["file"], second["file"])
        again = self.publish(directory, [{"n": 2}])
        self.assertEqual(again["file"], second["file"])  # 같은 내용은 같은 파일

    def test_changed_truncated_or_extended_generations_are_caught(self):
        directory = self.tmpdir()
        manifest = self.publish(directory, [{"n": i} for i in range(3)])
        manifest_file, data = ndjson.manifest_path(directory, "check"), directory / manifest["file"]
        original = data.read_bytes()
        data.write_bytes(original.replace(b'"n":1', b'"n":9'))
        self.assertTrue(any("SHA-256" in p for p in ndjson.verify(manifest_file)))
        data.write_bytes(original[: original.rindex(b"\n", 0, len(original) - 1) + 1])  # 마지막 줄 삭제
        self.assertIn("행 수", " ".join(ndjson.verify(manifest_file)))
        data.write_bytes(original + b'{"n":3}\n')
        self.assertIn("행 수", " ".join(ndjson.verify(manifest_file)))
        data.write_bytes(original[:-1])  # 쓰다 만 파일: 줄바꿈으로 끝나지 않는다
        self.assertIn("줄바꿈", " ".join(ndjson.verify(manifest_file)))
        data.write_bytes(original)
        self.assertEqual(ndjson.verify(manifest_file), [])

    def test_a_non_json_line_is_reported_even_if_the_hashes_were_rebuilt(self):
        directory = self.tmpdir()
        manifest = self.publish(directory, [{"n": 1}])
        content = b"not json\n"
        sha = hashlib.sha256(content).hexdigest()
        new_name = f"check.{sha[:16]}.ndjson"
        (directory / new_name).write_bytes(content)
        ndjson.manifest_path(directory, "check").write_text(json.dumps({**manifest, "file": new_name, "sha256": sha}))
        self.assertIn("JSON 이 아니다", " ".join(ndjson.verify(ndjson.manifest_path(directory, "check"))))

    def test_missing_manifest_or_missing_data_file(self):
        directory = self.tmpdir()
        with self.assertRaises(ndjson.NdjsonError):
            ndjson.verify(ndjson.manifest_path(directory, "none"))
        manifest = self.publish(directory, [{"n": 1}])
        (directory / manifest["file"]).unlink()
        self.assertIn("데이터 파일이 없다", " ".join(ndjson.verify(ndjson.manifest_path(directory, "check"))))

    def test_a_manifest_cannot_point_outside_its_folder_or_at_another_name(self):
        directory = self.tmpdir()
        manifest = self.publish(directory, [{"n": 1}])
        for bad in ("../secret.0123456789abcdef.ndjson", "/etc/passwd", "check.ndjson", "other.0123456789abcdef.ndjson"):
            ndjson.manifest_path(directory, "check").write_text(json.dumps({**manifest, "file": bad}))
            self.assertTrue(ndjson.verify(ndjson.manifest_path(directory, "check")), bad)
        with self.assertRaises(ndjson.NdjsonError):
            self.publish(directory, [], name="../evil")

    def test_the_manifest_hash_must_match_the_file_name(self):
        directory = self.tmpdir()
        manifest = self.publish(directory, [{"n": 1}])
        ndjson.manifest_path(directory, "check").write_text(json.dumps({**manifest, "sha256": "0" * 64}))
        problems = " ".join(ndjson.verify(ndjson.manifest_path(directory, "check")))
        self.assertIn("SHA-256", problems)
        self.assertIn("해시", problems)

    def test_a_failure_while_replacing_the_manifest_keeps_the_previous_publication(self):
        """검토 재현 1: 데이터 교체 뒤 manifest 교체만 실패해도 이전 결과(manifest + 데이터)가 그대로 검증을 통과한다."""
        directory = self.tmpdir()
        old = self.publish(directory, [{"old": 1}])
        manifest_file = ndjson.manifest_path(directory, "check")
        before = manifest_file.read_bytes()
        real = os.replace

        def fail_on_manifest(src, dst):
            if Path(dst).name.endswith(".manifest.json"):
                raise OSError("manifest 교체 실패")
            return real(src, dst)

        with mock.patch("events.ndjson.os.replace", fail_on_manifest):
            with self.assertRaises(OSError):
                self.publish(directory, [{"new": 1}])
        self.assertEqual(manifest_file.read_bytes(), before)  # 포인터가 그대로다
        self.assertEqual(ndjson.verify(manifest_file), [])
        self.assertEqual(json.loads((directory / old["file"]).read_text()), {"old": 1})
        self.assertEqual([p.name for p in directory.iterdir() if p.name.endswith(".tmp")], [])  # 임시 파일이 남지 않는다

    def test_interleaved_publications_end_with_a_manifest_that_matches_its_data(self):
        """A 가 포인터 교체 직전에 멈춘 사이 B 가 게시를 시도해도, 최종 manifest 가 가리키는 데이터는 온전하고 두 세대의 데이터 파일이 모두 남는다(B 는 A 를 기다린다)."""
        import threading

        directory = self.tmpdir()
        manifest_file = ndjson.manifest_path(directory, "check")
        real, paused, release = ndjson._publish, threading.Event(), threading.Event()

        def gate(path, writer):
            if Path(path).name == "check.manifest.json" and threading.current_thread().name == "writer-A":
                paused.set()
                assert release.wait(30)
            return real(path, writer)

        done = {}
        with mock.patch("events.ndjson._publish", gate):
            a = threading.Thread(target=lambda: done.update(A=self.publish(directory, [{"writer": "A"}])), name="writer-A")
            a.start()
            self.assertTrue(paused.wait(10))
            b = threading.Thread(target=lambda: done.update(B=self.publish(directory, [{"writer": "B"}])), name="writer-B")
            b.start()
            release.set()
            a.join(10)
            b.join(10)
        self.assertEqual(ndjson.verify(manifest_file), [])
        self.assertEqual(ndjson.read_manifest(manifest_file)["file"], done["B"]["file"])  # 나중에 게시한 쪽의 것
        self.assertEqual(json.loads((directory / done["B"]["file"]).read_text()), {"writer": "B"})
        self.assertEqual(len([p for p in directory.iterdir() if p.name.endswith(".ndjson")]), 2)  # A 의 세대도 온전히 남아 있다

    def test_concurrent_chained_publications_do_not_drop_a_successful_generation_from_the_chain(self):
        """검토 P2-4 재현: A 가 직전 세대 G0 를 읽고 포인터 교체 직전에 대기하는 동안 B 가 게시해 성공하면, A 가 이어서 게시한 최종 manifest 의 직전이 B 가 아니라 G0 였다.
        직전 세대를 읽는 시점부터 포인터를 교체할 때까지 직렬화하므로, B 는 A 가 끝나길 기다렸다가 A 의 세대 위에 이어진다."""
        import threading

        directory = self.tmpdir()
        pointer = ndjson.manifest_path(directory, "check")
        g0 = self.publish(directory, [{"gen": 0}], chain=True)
        g0_digest = ndjson.manifest_sha256(pointer)
        real, paused, release = ndjson._publish, threading.Event(), threading.Event()

        def gate(path, writer):
            if Path(path).name == "check.manifest.json" and threading.current_thread().name == "writer-A":
                paused.set()
                assert release.wait(30)
            return real(path, writer)

        results = {}

        def run(label, rows):
            results[label] = self.publish(directory, rows, chain=True)

        with mock.patch("events.ndjson._publish", gate):
            a = threading.Thread(target=run, args=("A", [{"gen": "A"}]), name="writer-A")
            a.start()
            self.assertTrue(paused.wait(10))  # A 는 G0 를 직전으로 읽고 포인터 교체 직전에 멈춰 있다
            b = threading.Thread(target=run, args=("B", [{"gen": "B"}]), name="writer-B")
            b.start()
            b.join(0.7)
            self.assertTrue(b.is_alive(), "B 가 A 를 기다리지 않고 먼저 게시했다 — 직렬화가 없다")
            release.set()
            a.join(10)
            b.join(10)
        self.assertEqual(ndjson.verify_chain(pointer), [])
        final = ndjson.read_manifest(pointer)
        self.assertEqual(final["file"], results["B"]["file"])  # B 가 A 뒤에 이어졌다
        self.assertEqual(final["previous_sha256"], ndjson.manifest_digest(results["A"]))  # B 의 직전은 A 다
        self.assertEqual(results["A"]["previous_sha256"], ndjson.manifest_digest(g0))  # A 의 직전은 G0
        self.assertEqual(g0["previous_sha256"], None)

    def test_the_returned_manifest_digest_is_what_was_published(self):
        """감사 로그의 고정점은 이 실행이 실제로 게시한 manifest 의 해시여야 한다 — 포인터를 다시 읽어 얻으면 그 사이 다른 실행이 바꾼 것을 담을 수 있다."""
        directory = self.tmpdir()
        manifest = self.publish(directory, [{"n": 1}], chain=True)
        pointer = ndjson.manifest_path(directory, "check")
        self.assertEqual(ndjson.manifest_digest(manifest), ndjson.manifest_sha256(pointer))
        again = self.publish(directory, [{"n": 2}], chain=True)
        self.assertNotEqual(ndjson.manifest_digest(again), ndjson.manifest_digest(manifest))
        self.assertEqual(again["previous_sha256"], ndjson.manifest_digest(manifest))

    def test_a_crash_while_writing_leaves_the_previous_publication_and_no_partial_file(self):
        directory = self.tmpdir()
        self.publish(directory, [{"old": 1}])
        before = sorted(p.name for p in directory.iterdir())

        def dying():
            yield {"new": 1}
            raise RuntimeError("쓰는 도중 죽음")

        with self.assertRaises(RuntimeError):
            self.publish(directory, dying())
        self.assertEqual(sorted(p.name for p in directory.iterdir()), before)
        self.assertEqual(ndjson.verify(ndjson.manifest_path(directory, "check")), [])

    def test_durability_order_data_synced_then_renamed_then_directory_synced_then_manifest(self):
        """내구성 순서(시험이 fsync 의 유무를 직접 볼 수 없어 호출 순서로 고정한다): 파일 fsync → replace → 폴더 fsync, 데이터가 manifest 보다 먼저."""
        directory = self.tmpdir()
        calls = []
        real_fsync, real_replace = os.fsync, os.replace
        with mock.patch("events.ndjson.os.fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))), \
                mock.patch("events.ndjson.os.replace", lambda src, dst: (calls.append("replace:" + Path(dst).suffix), real_replace(src, dst))):
            self.publish(directory, [{"n": 1}])
        self.assertEqual(calls, ["fsync", "replace:.ndjson", "fsync", "fsync", "replace:.json", "fsync"])  # 데이터(파일·폴더) 다음에 manifest(파일·교체·폴더)


    def test_a_failure_at_any_step_keeps_a_verifiable_pointer_and_leaves_no_temporary_file(self):
        """계획 4-4i: 데이터 파일과 manifest 각각의 쓰기·파일 동기화·교체·폴더 동기화 중 어디서 실패해도 예외가 올라가고, 포인터는 온전한 게시본(교체 전이면 이전 것)을 가리키며, 임시 파일이 남지 않는다."""
        class FailingWrites:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.handle.close()

            def write(self, data):
                raise OSError("쓰기 실패")

        def failing(name, nth):
            real, seen = getattr(os, name), []

            def call(*args):
                seen.append(1)
                if len(seen) != nth:
                    return real(*args)
                if name == "fdopen":
                    return FailingWrites(real(*args))
                raise OSError(f"{name} 실패")
            return mock.patch(f"events.ndjson.os.{name}", call)

        # 호출 순서: 데이터 fdopen·fsync·replace·폴더 fsync → manifest fdopen·fsync·replace·폴더 fsync
        steps = [("fdopen", 1, "old"), ("fsync", 1, "old"), ("replace", 1, "old"), ("fsync", 2, "old"),
                 ("fdopen", 2, "old"), ("fsync", 3, "old"), ("replace", 2, "old"), ("fsync", 4, "new")]
        for name, nth, pointer in steps:
            with self.subTest(step=f"{name}#{nth}"):
                directory = self.tmpdir()
                old = self.publish(directory, [{"old": 1}])
                with failing(name, nth), self.assertRaises(OSError):
                    self.publish(directory, [{"new": 1}])
                manifest_file = ndjson.manifest_path(directory, "check")
                self.assertEqual(ndjson.verify(manifest_file), [])
                current = ndjson.read_manifest(manifest_file)["file"]
                self.assertEqual(current == old["file"], pointer == "old", current)
                self.assertEqual([p.name for p in directory.iterdir() if p.name.endswith(".tmp")], [])

@tag("security")
class EventGapTests(MongoDatabaseMixin, TestCase):
    def setUp(self):
        super().setUp()
        store.ensure()
        self.w = World()
        self.decision = records.decide(self.w.slot.media_id, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(self.w.slot.media_id, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW)
        self.inbox_id = view.inbox_id  # 결정 1 + 접수 1 + 판정 1 + 과금 1

    def gaps(self):
        return list(records.event_gaps())

    def test_nothing_is_missing_when_every_row_has_its_event(self):
        self.assertEqual(self.gaps(), [])

    def test_a_deleted_event_is_reported_for_each_kind(self):
        for name in ("ad.decision", "ad.reaction_received", "ad.reaction", "ad.charge"):
            row = EventOutbox.objects.get(event_name=name)
            kept = dict(event_id=row.event_id, event_name=row.event_name, schema_version=1, aggregate_id=row.aggregate_id, payload=row.payload, created_at=row.created_at)
            row.delete()
            (gap,) = self.gaps()
            self.assertEqual((gap["kind"], gap["event_name"], gap["event_id"]), ("missing_event", name, str(kept["event_id"])), name)
            EventOutbox.objects.create(**kept)

    def test_source_kind_and_id_name_the_row_to_backfill(self):
        EventOutbox.objects.filter(event_name="ad.charge").delete()
        (gap,) = self.gaps()
        entry = LedgerEntry.objects.get(entry_type="CHARGE")
        self.assertEqual((gap["source_kind"], gap["source_id"]), ("ledger_charge", str(entry.entry_id)))
        EventOutbox.objects.filter(event_name="ad.decision").delete()
        by_kind = {g["source_kind"]: g["source_id"] for g in self.gaps()}
        self.assertEqual(by_kind["decision"], str(self.decision.decision_id))

    def test_sent_and_purged_events_still_count_when_they_are_in_mongodb(self):
        """보낸 지 오래돼 outbox 에서 지워진 이벤트는 MongoDB 에 있으면 누락이 아니다."""
        relay_batch()
        EventOutbox.objects.all().delete()  # purge
        self.assertEqual(self.gaps(), [])
        store.collection().delete_one({"event_name": "ad.charge"})
        self.assertEqual([g["event_name"] for g in self.gaps()], ["ad.charge"])

    def test_events_that_were_never_written_for_old_rows_are_found(self):
        """Step 4 이전에 쌓인 행(이벤트 없이 만들어진 것)이 백필 대상으로 나온다."""
        EventOutbox.objects.all().delete()
        self.assertEqual(len(self.gaps()), 4)

    def test_sent_but_not_in_mongodb_is_reported(self):
        relay_batch()
        self.assertEqual(events.sent_but_not_in_mongo(), [])
        gone = store.collection().find_one({"event_name": "ad.reaction"})["_id"]
        store.collection().delete_one({"_id": gone})
        self.assertEqual(events.sent_but_not_in_mongo(), [gone])
        self.assertEqual(events.sent_but_not_in_mongo(limit=0), [])

    def test_when_mongodb_is_unreachable_the_answer_is_an_error_not_a_false_all_clear(self):
        EventOutbox.objects.all().delete()
        with unreachable_store():
            with self.assertRaises(Exception):
                self.gaps()


@tag("security")
class ExportCommandTests(TempDirMixin, MongoDatabaseMixin, TransactionTestCase):  # 정합성 점검은 트랜잭션 밖에서 한 스냅샷으로 읽는다
    def setUp(self):
        super().setUp()
        store.ensure()
        w = World()
        self.decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(w.slot.media_id, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW)

    def export(self, out):
        stdout = io.StringIO()
        try:
            call_command("export_integrity", "--out", str(out), stdout=stdout)
            return True, stdout.getvalue()
        except CommandError as error:
            return False, stdout.getvalue() + str(error)

    def rows(self, out, name):
        manifest = ndjson.read_manifest(ndjson.manifest_path(out, name))
        return [json.loads(line) for line in (out / manifest["file"]).read_text().splitlines()]

    def test_a_clean_state_publishes_three_empty_verified_results_and_succeeds(self):
        out = self.tmpdir() / "res"
        ok, text = self.export(out)
        self.assertTrue(ok, text)
        for name in ("ledger_check", "event_gaps", "event_delivery"):
            manifest_file = ndjson.manifest_path(out, name)
            manifest = ndjson.read_manifest(manifest_file)
            self.assertEqual((manifest["rows"], manifest["source_kind"], ndjson.verify(manifest_file)), (0, name, []))

    def test_the_checkpoint_states_the_real_scan_scope(self):
        out = self.tmpdir()
        self.export(out)
        checkpoint = ndjson.read_manifest(ndjson.manifest_path(out, "event_gaps"))["checkpoint"]
        self.assertEqual(checkpoint["scope"], "mysql-repeatable-read-snapshot")
        self.assertEqual(checkpoint["scanned"], {"decision": 1, "reaction": 1, "ledger_charge": 1})  # 실제로 훑은 행 수
        self.assertEqual(checkpoint, ndjson.read_manifest(ndjson.manifest_path(out, "ledger_check"))["checkpoint"])  # 세 점검이 같은 범위를 본다

    def test_rows_created_after_the_snapshot_began_are_not_in_the_result(self):
        """검토 재현: 점검이 시작된 뒤 생긴 행(이벤트가 아직 없는 것 포함)이 결과에 섞이지 않는다 — 모든 읽기가 한 스냅샷을 본다."""
        from records.models import Decision
        from tests.concurrency import WAIT, Worker

        out = self.tmpdir()
        created = []

        def snapshot_has_started_then_another_connection_adds_a_decision(quiescent=False):
            Decision.objects.count()  # 우리 스냅샷이 여기서 시작된다
            def insert():
                decision = Decision.objects.get(pk=self.decision.decision_id)
                decision.pk = uuid.uuid7()  # 이벤트 없이 새 결정을 하나 더 만든다(점검이 시작된 뒤의 행)
                decision._state.adding = True
                decision.save(force_insert=True)
                created.append(decision.pk)
            worker = Worker(insert)
            worker.start()
            worker.join(WAIT)
            assert not worker.errors, worker.errors
            return []

        with mock.patch("records.management.commands.export_integrity.check_ledger", snapshot_has_started_then_another_connection_adds_a_decision):
            ok, text = self.export(out)
        self.assertTrue(ok, text)  # 새 결정은 스냅샷에 보이지 않으므로 누락으로 보고되지 않는다
        self.assertEqual(self.rows(out, "event_gaps"), [])
        self.assertEqual(ndjson.read_manifest(ndjson.manifest_path(out, "event_gaps"))["checkpoint"]["scanned"]["decision"], 1)  # 훑은 범위에도 없다
        self.assertEqual(Decision.objects.count(), 2)  # (다음 점검에서는 보인다)
        ok, _ = self.export(self.tmpdir())
        self.assertFalse(ok)
        self.assertEqual(len(created), 1)

    def test_problems_are_written_and_the_command_fails(self):
        EventOutbox.objects.filter(event_name="ad.charge").delete()
        out = self.tmpdir()
        ok, text = self.export(out)
        self.assertFalse(ok)
        self.assertIn("문제 1건", text)
        self.assertEqual([r["event_name"] for r in self.rows(out, "event_gaps")], ["ad.charge"])
        self.assertEqual(ndjson.verify(ndjson.manifest_path(out, "event_gaps")), [])  # 문제가 있는 결과도 manifest 와 맞다

    def test_a_sent_event_missing_from_mongodb_is_exported_separately(self):
        """보냈다고 표시됐는데 MongoDB 에서 사라진 이벤트는 event_gaps 가 아니라 event_delivery 의 몫이다."""
        relay_batch()
        gone = store.collection().find_one({"event_name": "ad.reaction"})["_id"]
        store.collection().delete_one({"_id": gone})
        out = self.tmpdir()
        ok, _ = self.export(out)
        self.assertFalse(ok)
        self.assertEqual(self.rows(out, "event_delivery"), [{"kind": "sent_not_in_mongo", "event_id": str(gone)}])
        self.assertEqual(self.rows(out, "event_gaps"), [])  # outbox 에 남아 있으니 누락이 아니다

    def test_a_ledger_mismatch_is_exported(self):
        from billing.models import Wallet

        Wallet.objects.update(balance=1)  # 잔액 ≠ 원장 합계
        out = self.tmpdir()
        ok, _ = self.export(out)
        self.assertFalse(ok)
        row = self.rows(out, "ledger_check")[0]
        self.assertEqual(row["kind"], "ledger_problem")
        self.assertTrue(row["message"])

    def test_mongodb_unreachable_fails_without_publishing_anything(self):
        out = self.tmpdir()
        EventOutbox.objects.all().delete()
        with unreachable_store():
            ok, text = self.export(out)
        self.assertFalse(ok)
        self.assertIn("점검하지 못했습니다", text)
        self.assertEqual(list(out.glob("*")) if out.exists() else [], [])  # 불완전한 결과를 게시하지 않는다

    def test_verify_command(self):
        out = self.tmpdir()
        self.export(out)
        stdout = io.StringIO()
        files = [str(ndjson.manifest_path(out, n)) for n in ("ledger_check", "event_gaps", "event_delivery")]
        call_command("verify_ndjson", *files, stdout=stdout)
        self.assertEqual(stdout.getvalue().count("OK  "), 3)
        manifest = ndjson.read_manifest(ndjson.manifest_path(out, "ledger_check"))
        (out / manifest["file"]).write_bytes(b'{"x":1}\n')
        with self.assertRaises(CommandError):
            call_command("verify_ndjson", *files, stdout=io.StringIO())
