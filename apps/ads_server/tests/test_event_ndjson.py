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
from tests.mongo_support import MongoDatabaseMixin

T = datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc)


class TempDirMixin:
    def tmpdir(self):
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)


@tag("security")
class WriteAndVerifyTests(TempDirMixin, SimpleTestCase):
    def test_manifest_describes_the_file_exactly(self):
        path = self.tmpdir() / "check.ndjson"
        records_in = [{"a": 1, "한글": "값"}, {"b": [1, 2]}]
        manifest = ndjson.write(path, records_in, "ledger_check", 3, checkpoint="cp-1", now=T)
        data = path.read_bytes()
        self.assertEqual(data.decode("utf-8").count("\n"), 2)  # 한 줄 = 레코드 하나, 줄바꿈으로 끝난다
        self.assertEqual(manifest["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual((manifest["rows"], manifest["schema_version"], manifest["source_kind"], manifest["checkpoint"], manifest["file"]), (2, 3, "ledger_check", "cp-1", "check.ndjson"))
        self.assertEqual(manifest["created_at"], "2026-10-10T03:00:00+00:00")
        self.assertEqual(json.loads(ndjson.manifest_path(path).read_text()), manifest)
        self.assertEqual([json.loads(line) for line in data.decode("utf-8").splitlines()], records_in)
        self.assertEqual(ndjson.verify(path), [])

    def test_an_empty_result_is_a_valid_proof_of_a_clean_check(self):
        path = self.tmpdir() / "clean.ndjson"
        manifest = ndjson.write(path, [], "event_gaps", 1, now=T)
        self.assertEqual((manifest["rows"], path.read_bytes(), ndjson.verify(path)), (0, b"", []))

    def test_changed_truncated_or_extended_files_are_caught(self):
        path = self.tmpdir() / "x.ndjson"
        ndjson.write(path, [{"n": i} for i in range(3)], "k", 1)
        original = path.read_bytes()
        path.write_bytes(original.replace(b'"n":1', b'"n":9'))
        self.assertTrue(any("SHA-256" in p for p in ndjson.verify(path)))
        path.write_bytes(original[: original.rindex(b"\n", 0, len(original) - 1) + 1])  # 마지막 줄 삭제
        problems = " ".join(ndjson.verify(path))
        self.assertIn("행 수", problems)
        self.assertIn("SHA-256", problems)
        path.write_bytes(original + b'{"n":3}\n')
        self.assertIn("행 수", " ".join(ndjson.verify(path)))
        path.write_bytes(original[:-1])  # 쓰다 만 파일: 줄바꿈으로 끝나지 않는다
        self.assertIn("줄바꿈", " ".join(ndjson.verify(path)))
        path.write_bytes(original)
        self.assertEqual(ndjson.verify(path), [])

    def test_a_non_json_line_is_reported_even_if_the_manifest_was_rebuilt(self):
        path = self.tmpdir() / "y.ndjson"
        ndjson.write(path, [{"n": 1}], "k", 1)
        path.write_bytes(b"not json\n")
        manifest = ndjson.read_manifest(path)
        manifest["sha256"] = hashlib.sha256(b"not json\n").hexdigest()
        ndjson.manifest_path(path).write_text(json.dumps(manifest))
        self.assertIn("JSON 이 아니다", " ".join(ndjson.verify(path)))

    def test_missing_manifest_means_the_file_is_not_trusted(self):
        path = self.tmpdir() / "z.ndjson"
        path.write_bytes(b'{"n":1}\n')
        with self.assertRaises(ndjson.NdjsonError):
            ndjson.verify(path)

    def test_a_manifest_of_another_file_is_rejected(self):
        directory = self.tmpdir()
        ndjson.write(directory / "a.ndjson", [{"n": 1}], "k", 1)
        (directory / "b.ndjson").write_bytes((directory / "a.ndjson").read_bytes())
        ndjson.manifest_path(directory / "b.ndjson").write_bytes(ndjson.manifest_path(directory / "a.ndjson").read_bytes())
        self.assertIn("a.ndjson", " ".join(ndjson.verify(directory / "b.ndjson")))

    def test_a_crash_while_writing_leaves_no_half_written_final_file(self):
        directory = self.tmpdir()
        path = directory / "w.ndjson"
        ndjson.write(path, [{"old": 1}], "k", 1)
        before = (path.read_bytes(), ndjson.manifest_path(path).read_bytes())

        def dying():
            yield {"new": 1}
            raise RuntimeError("쓰는 도중 죽음")

        with self.assertRaises(RuntimeError):
            ndjson.write(path, dying(), "k", 1)
        self.assertEqual((path.read_bytes(), ndjson.manifest_path(path).read_bytes()), before)  # 이전 결과가 그대로다
        self.assertEqual(sorted(p.name for p in directory.iterdir()), ["w.manifest.json", "w.ndjson"])  # 임시 파일이 남지 않는다
        self.assertEqual(ndjson.verify(path), [])

    def test_the_data_file_is_replaced_before_the_manifest(self):
        """manifest 가 있으면 데이터 파일은 완결이다 — 데이터 파일을 먼저 확정하고 manifest 를 나중에 확정한다."""
        directory = self.tmpdir()
        path = directory / "o.ndjson"
        order = []
        real = os.replace
        with mock.patch("events.ndjson.os.replace", lambda src, dst: (order.append(Path(dst).name), real(src, dst))):
            ndjson.write(path, [{"n": 1}], "k", 1)
        self.assertEqual(order, ["o.ndjson", "o.manifest.json"])


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
        from django.test import override_settings

        from events import mongo

        EventOutbox.objects.all().delete()
        with override_settings(EVENT_STORE={**mongo.config(), "HOSTS": ["127.0.0.1:1"], "REPLICA_SET": None}):
            mongo.close()
            with self.assertRaises(Exception):
                self.gaps()
            mongo.close()


@tag("security")
class ExportCommandTests(TempDirMixin, MongoDatabaseMixin, TransactionTestCase):  # 정합성 점검은 트랜잭션 밖에서 한 스냅샷으로 읽는다
    def setUp(self):
        super().setUp()
        store.ensure()
        w = World()
        decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW)

    def export(self, out):
        stdout = io.StringIO()
        try:
            call_command("export_integrity", "--out", str(out), stdout=stdout)
            return True, stdout.getvalue()
        except CommandError as error:
            return False, stdout.getvalue() + str(error)

    def test_a_clean_state_writes_two_empty_verified_files_and_succeeds(self):
        out = self.tmpdir() / "res"
        ok, text = self.export(out)
        self.assertTrue(ok, text)
        for name, kind in (("ledger_check", "ledger_check"), ("event_gaps", "event_gaps")):
            path = out / f"{name}.ndjson"
            self.assertEqual((ndjson.read_manifest(path)["rows"], ndjson.read_manifest(path)["source_kind"], ndjson.verify(path)), (0, kind, []))
        self.assertTrue(ndjson.read_manifest(out / "event_gaps.ndjson")["checkpoint"].startswith("scanned-before:"))

    def test_problems_are_written_and_the_command_fails(self):
        EventOutbox.objects.filter(event_name="ad.charge").delete()
        out = self.tmpdir()
        ok, text = self.export(out)
        self.assertFalse(ok)
        self.assertIn("문제 1건", text)
        lines = (out / "event_gaps.ndjson").read_text().splitlines()
        self.assertEqual([json.loads(line)["event_name"] for line in lines], ["ad.charge"])
        self.assertEqual(ndjson.verify(out / "event_gaps.ndjson"), [])  # 문제가 있는 결과도 manifest 와 맞다
        self.assertEqual(ndjson.read_manifest(out / "event_gaps.ndjson")["rows"], 1)

    def test_a_ledger_mismatch_is_exported(self):
        from billing.models import Wallet

        Wallet.objects.update(balance=1)  # 잔액 ≠ 원장 합계
        out = self.tmpdir()
        ok, _ = self.export(out)
        self.assertFalse(ok)
        row = json.loads((out / "ledger_check.ndjson").read_text().splitlines()[0])
        self.assertEqual(row["kind"], "ledger_problem")
        self.assertTrue(row["message"])

    def test_mongodb_unreachable_fails_without_writing_an_incomplete_gap_list(self):
        from django.test import override_settings

        from events import mongo

        out = self.tmpdir()
        EventOutbox.objects.all().delete()
        with override_settings(EVENT_STORE={**mongo.config(), "HOSTS": ["127.0.0.1:1"], "REPLICA_SET": None}):
            mongo.close()
            ok, text = self.export(out)
            mongo.close()
        self.assertFalse(ok)
        self.assertIn("점검하지 못했습니다", text)
        self.assertFalse((out / "event_gaps.ndjson").exists())  # 불완전한 목록을 완결 파일로 남기지 않는다

    def test_verify_command(self):
        out = self.tmpdir()
        self.export(out)
        stdout = io.StringIO()
        call_command("verify_ndjson", str(out / "ledger_check.ndjson"), str(out / "event_gaps.ndjson"), stdout=stdout)
        self.assertEqual(stdout.getvalue().count("OK  "), 2)
        (out / "ledger_check.ndjson").write_bytes(b'{"x":1}\n')
        with self.assertRaises(CommandError):
            call_command("verify_ndjson", str(out / "ledger_check.ndjson"), str(out / "event_gaps.ndjson"), stdout=io.StringIO())
