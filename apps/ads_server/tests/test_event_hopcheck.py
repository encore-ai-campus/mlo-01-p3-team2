"""Step 4-3c: 구간 대조(`verify_hops`) — 분류(일치·확정 불일치·중계 지연 후보·열린 창·비교 불가), 세대 사슬, 폴더 밖 고정점."""
import io
import json
import shutil
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from random import Random

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase, tag

from events import hopcheck, ndjson, store
from events.models import EventOutbox
from events.relay import relay_batch
from records import api as records
from tests.factories import NOW, SUBJECT, World
from tests.mongo_support import MongoDatabaseMixin

W = "2026-10-07T00:00:00Z"
KEY = (W, "ad.decision")


def line(count=1, ids="i", content="c", unsent=None, window=W, name="ad.decision"):
    base = {"window_start": window, "window_end": "x", "event_name": name, "count": count, "ids_sha256": ids, "content_sha256": content}
    if unsent is not None:
        base["unsent"] = unsent
    return base


def hop(name, *lines, open_windows=(), not_comparable=()):
    checkpoint = {"open_windows": list(open_windows), "not_comparable_windows": list(not_comparable)}
    return hopcheck.Hop(name, {"checkpoint": checkpoint}, {(l["window_start"], l["event_name"]): l for l in lines})


def statuses(rows):
    return [(r["status"], r["fields"]) for r in rows]


@tag("security")
class ClassificationTests(SimpleTestCase):
    def test_equal_summaries_match(self):
        self.assertEqual(statuses(hopcheck.compare(hop("hop_source", line()), hop("hop_outbox", line(unsent=0)))), [("match", [])])

    def test_each_differing_field_is_named(self):
        for override, field in (({"count": 2}, "count"), ({"ids": "other"}, "ids_sha256"), ({"content": "other"}, "content_sha256")):
            (row,) = hopcheck.compare(hop("hop_source", line()), hop("hop_outbox", line(unsent=0, **override)))
            self.assertEqual((row["status"], row["fields"]), ("mismatch", [field]))

    def test_a_missing_line_is_a_confirmed_mismatch_without_unsent(self):
        (row,) = hopcheck.compare(hop("hop_outbox", line(unsent=0)), hop("hop_mongo"))
        self.assertEqual((row["status"], row["fields"]), ("mismatch", ["line_missing_in_b"]))
        (row,) = hopcheck.compare(hop("hop_mongo"), hop("hop_outbox", line(unsent=0)))
        self.assertEqual((row["status"], row["fields"]), ("mismatch", ["line_missing_in_a"]))

    def test_mongodb_behind_with_unsent_rows_is_a_relay_lag_candidate_not_a_failure(self):
        (row,) = hopcheck.compare(hop("hop_outbox", line(count=5, unsent=2)), hop("hop_mongo", line(count=3, ids="x", content="y")))
        self.assertEqual(row["status"], "relay_lag_candidate")
        (row,) = hopcheck.compare(hop("hop_outbox", line(count=5, unsent=5)), hop("hop_mongo"))  # 줄이 아예 없는 창도(아직 하나도 못 보냄: 부족 5 = 미전송 5)
        self.assertEqual(row["status"], "relay_lag_candidate")

    def test_lag_needs_unsent_rows_and_a_smaller_downstream(self):
        (row,) = hopcheck.compare(hop("hop_outbox", line(count=5, unsent=0)), hop("hop_mongo", line(count=3)))
        self.assertEqual(row["status"], "mismatch")  # 미전송이 없는데 적다 = MongoDB 가 잃었다
        (row,) = hopcheck.compare(hop("hop_outbox", line(count=3, unsent=2)), hop("hop_mongo", line(count=3, content="z")))
        self.assertEqual(row["status"], "mismatch")  # 건수가 같은데 내용이 다르다 = 지연이 아니다
        (row,) = hopcheck.compare(hop("hop_outbox", line(count=3, unsent=2)), hop("hop_mongo", line(count=4)))
        self.assertEqual(row["status"], "mismatch")  # MongoDB 가 더 많다

    def test_source_to_mongodb_uses_the_unsent_counts_of_the_outbox_hop(self):
        source, outbox, mongo = hop("hop_source", line(count=5)), hop("hop_outbox", line(count=5, unsent=5)), hop("hop_mongo")
        self.assertEqual(hopcheck.compare(source, mongo, unsent_from=outbox)[0]["status"], "relay_lag_candidate")
        self.assertEqual(hopcheck.compare(source, mongo)[0]["status"], "mismatch")  # 근거(outbox)가 없으면 확정 불일치로 둔다

    def test_source_to_outbox_never_counts_as_lag(self):
        (row,) = hopcheck.compare(hop("hop_source", line(count=5)), hop("hop_outbox", line(count=3, unsent=2)))
        self.assertEqual(row["status"], "mismatch")  # 같은 스냅샷이라 지연이 아니다

    def test_open_windows_and_not_comparable_windows_are_not_compared(self):
        rows = hopcheck.compare(hop("hop_source", line()), hop("hop_outbox", open_windows=[W]))
        self.assertEqual([r["status"] for r in rows], ["open_window"])
        rows = hopcheck.compare(hop("hop_source", line()), hop("hop_outbox", not_comparable=[W]))
        self.assertEqual([r["status"] for r in rows], ["not_comparable"])
        # 줄이 없는 열린 창도 기록으로 남는다
        rows = hopcheck.compare(hop("hop_source"), hop("hop_mongo", open_windows=["2026-10-10T00:00:00Z"]))
        self.assertEqual([(r["status"], r["window_start"]) for r in rows], [("open_window", "2026-10-10T00:00:00Z")])


@tag("security")
class LagExplanationTests(SimpleTestCase):
    """검토 P2-1: 미전송 하나가 전송 완료 이벤트의 유실을 가리면 안 된다 — 부족분이 미전송 건수로 설명될 때만 지연 후보다."""

    def classify(self, outbox_count, unsent, mongo_count):
        rows = hopcheck.compare(hop("hop_outbox", line(count=outbox_count, unsent=unsent)), hop("hop_mongo", *([line(count=mongo_count)] if mongo_count else [])))
        return rows[0]["status"]

    def test_the_shortfall_must_fit_in_the_unsent_rows(self):
        self.assertEqual(self.classify(3, 3, 0), "relay_lag_candidate")  # 셋 다 아직 못 보냈다
        self.assertEqual(self.classify(3, 2, 1), "relay_lag_candidate")  # 부족 2 = 미전송 2
        self.assertEqual(self.classify(3, 1, 2), "relay_lag_candidate")  # 부족 1 = 미전송 1
        self.assertEqual(self.classify(3, 1, 0), "mismatch")  # 검토 재현: 부족 3 > 미전송 1 — 적어도 두 건은 확정 유실
        self.assertEqual(self.classify(3, 2, 0), "mismatch")  # 부족 3 > 미전송 2
        self.assertEqual(self.classify(5, 1, 3), "mismatch")  # 부족 2 > 미전송 1
        self.assertEqual(self.classify(3, 0, 2), "mismatch")  # 미전송이 없는데 적다

    def test_source_to_mongodb_uses_the_same_rule_with_the_outbox_unsent_counts(self):
        source, outbox = hop("hop_source", line(count=3)), hop("hop_outbox", line(count=3, unsent=1))
        self.assertEqual(hopcheck.compare(source, hop("hop_mongo"), unsent_from=outbox)[0]["status"], "mismatch")
        outbox = hop("hop_outbox", line(count=3, unsent=3))
        self.assertEqual(hopcheck.compare(source, hop("hop_mongo"), unsent_from=outbox)[0]["status"], "relay_lag_candidate")

    def test_the_fields_still_say_what_differs(self):
        (row,) = hopcheck.compare(hop("hop_outbox", line(count=3, unsent=1)), hop("hop_mongo"))
        self.assertEqual((row["status"], row["fields"]), ("mismatch", ["line_missing_in_b"]))


A64, B64 = "a" * 64, "b" * 64  # 형식이 맞는 해시


def hour_line(start="2026-10-07T05:00:00Z", end="2026-10-07T06:00:00Z", **kw):
    return line(window=start, ids=A64, content=B64, **kw) | {"window_end": end}


class InputValidationTests(SimpleTestCase):
    """검토 P2-3: 파일 체크섬이 맞는 것과 집계 범위가 같은 것은 별개다 — 대조 전에 창 시작·끝·크기와 계약 버전·구간 종류를 확인한다."""

    def publish(self, lines, kind="hop_mongo", window="utc-day", schema_version=1, hop_field="same", **extra):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        checkpoint = {"window": window, "open_windows": []}
        if hop_field == "same":
            checkpoint["hop"] = kind
        elif hop_field:
            checkpoint["hop"] = hop_field
        if "unresolved" in extra:
            checkpoint["unresolved_charges"] = extra["unresolved"]
        ndjson.write(directory, "h", lines, kind, schema_version, checkpoint=checkpoint)
        return ndjson.manifest_path(directory, "h")

    def day(self, **kw):
        return line(window="2026-10-07T00:00:00Z", **({"ids": A64, "content": B64} | kw)) | {"window_end": "2026-10-08T00:00:00Z"}

    def load(self, path, name="hop_mongo"):
        return hopcheck.load_hop(path, name, expected_kind=name if name != "pipeline" else None)

    def test_a_well_formed_input_loads(self):
        hop_loaded = self.load(self.publish([self.day()]))
        self.assertEqual((hop_loaded.window, len(hop_loaded.lines)), ("utc-day", 1))

    def test_the_window_end_must_match_the_declared_window_size(self):
        """검토 재현: 시작 시각·요약값은 그대로 두고 끝 시각을 한 시간 뒤로 바꾸고 checkpoint.window 를 utc-hour 로 — 일별과 시간별이 match 로 성공했다."""
        forged = line(window="2026-10-07T00:00:00Z", ids=A64, content=B64) | {"window_end": "2026-10-07T01:00:00Z"}
        with self.assertRaises(hopcheck.HopInputError) as raised:
            self.load(self.publish([forged], window="utc-day"))
        self.assertIn("창", str(raised.exception))
        self.load(self.publish([forged], window="utc-hour"))  # 선언한 크기와 맞으면 그 자체로는 올바른 시간별 manifest 다

    def test_daily_and_hourly_manifests_are_never_compared(self):
        daily = self.load(self.publish([self.day()]))
        hourly = self.load(self.publish([line(window="2026-10-07T00:00:00Z", ids=A64, content=B64) | {"window_end": "2026-10-07T01:00:00Z"}], window="utc-hour"), "pipeline")
        with self.assertRaises(hopcheck.HopInputError):
            hopcheck.compare(daily, hourly)

    def test_windows_must_be_aligned_to_the_utc_boundary(self):
        misaligned = line(window="2026-10-07T03:00:00Z", ids=A64, content=B64) | {"window_end": "2026-10-08T03:00:00Z"}
        with self.assertRaises(hopcheck.HopInputError):
            self.load(self.publish([misaligned]))
        half_hour = hour_line("2026-10-07T05:30:00Z", "2026-10-07T06:30:00Z")
        with self.assertRaises(hopcheck.HopInputError):
            self.load(self.publish([half_hour], window="utc-hour"))

    def test_an_unknown_window_kind_contract_version_or_hop_kind_is_refused(self):
        for kwargs in ({"window": "utc-week"}, {"window": None}, {"schema_version": 2}, {"kind": "hop_other"}, {"kind": "ledger_check"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(hopcheck.HopInputError):
                    self.load(self.publish([self.day()], **kwargs))

    def test_the_unresolved_charge_count_must_be_a_non_negative_integer(self):
        """원본 구간의 `unresolved_charges`(창에 놓을 수 없는 과금 원장 줄)는 줄 대조에 나오지 않고 이 값으로만 실패한다 — 형식이 틀린 값으로 0 처럼 지나가지 않는다."""
        self.assertEqual(self.load(self.publish([self.day()], kind="hop_source", unresolved=2), "hop_source").unresolved_charges, 2)
        for bad in ("1", -1, True, 1.5, None):
            with self.subTest(bad=bad), self.assertRaises(hopcheck.HopInputError):
                self.load(self.publish([self.day()], kind="hop_source", unresolved=bad), "hop_source")

    def test_the_file_must_be_the_hop_it_is_loaded_as(self):
        outbox_file = self.publish([self.day(unsent=0)], kind="hop_outbox")
        with self.assertRaises(hopcheck.HopInputError):
            self.load(outbox_file, "hop_mongo")  # 구간 종류가 다른 파일을 바꿔 끼울 수 없다
        with self.assertRaises(hopcheck.HopInputError):
            self.load(self.publish([self.day()], hop_field="hop_source"), "hop_mongo")  # checkpoint 의 구간이 다르다

    def test_a_duplicate_summary_key_is_refused_not_overwritten(self):
        with self.assertRaises(hopcheck.HopInputError) as raised:
            self.load(self.publish([self.day(), self.day(content="c" * 64)]))
        self.assertIn("중복", str(raised.exception))

    def test_malformed_lines_are_refused(self):
        for broken in ({"count": -1}, {"count": True}, {"count": "1"}, {"ids_sha256": "xyz"}, {"content_sha256": "A" * 64}, {"window_start": "어제"}):
            with self.subTest(broken=broken):
                with self.assertRaises(hopcheck.HopInputError):
                    self.load(self.publish([self.day() | broken]))
        missing = self.day()
        del missing["ids_sha256"]
        with self.assertRaises(hopcheck.HopInputError):
            self.load(self.publish([missing]))


@tag("security")
class VerifyHopsCommandTests(MongoDatabaseMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        store.ensure()
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        w = World()
        decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        view, _ = records.receive_reaction(w.slot.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW + timedelta(seconds=7))

    def export(self):
        call_command("export_hop_manifests", "--out", str(self.dir / "hops"), stdout=io.StringIO())

    def verify(self, *flags):
        out = io.StringIO()
        try:
            call_command("verify_hops", "--dir", str(self.dir / "hops"), *flags, stdout=out)
            return True, out.getvalue()
        except CommandError as error:
            return False, out.getvalue() + str(error)

    def lines(self, hop_name):
        manifest = ndjson.read_manifest(ndjson.manifest_path(self.dir / "hops", hop_name))
        return [json.loads(l) for l in (self.dir / "hops" / manifest["file"]).read_text().splitlines()]

    def test_everything_matches_after_the_relay(self):
        relay_batch()
        self.export()
        ok, text = self.verify("--out", str(self.dir / "report"))
        self.assertTrue(ok, text)
        self.assertIn("'match': 12", text)  # 세 쌍 × 4줄
        manifest = ndjson.read_manifest(ndjson.manifest_path(self.dir / "report", "hop_report"))
        self.assertEqual((ndjson.verify(ndjson.manifest_path(self.dir / "report", "hop_report")), manifest["checkpoint"]["counts"], manifest["checkpoint"]["errors"]), ([], {"match": 12}, []))

    def test_before_the_relay_it_is_a_lag_candidate_and_the_command_still_succeeds(self):
        self.export()
        ok, text = self.verify()
        self.assertTrue(ok, text)
        self.assertIn("relay_lag_candidate", text)
        self.assertIn("LAG", text)
        relay_batch()
        self.export()  # 다시 확인 = 다시 낸 manifest
        ok, text = self.verify()
        self.assertTrue(ok, text)
        self.assertNotIn("LAG", text)

    def test_a_tampered_outbox_event_is_a_confirmed_mismatch(self):
        relay_batch()
        row = EventOutbox.objects.get(event_name="ad.charge")
        payload = row.payload
        payload["charged_amount"] = 999
        EventOutbox.objects.filter(pk=row.pk).update(payload=payload)
        self.export()
        ok, text = self.verify()
        self.assertFalse(ok)
        self.assertIn("content_sha256", text)
        self.assertIn("hop_source->hop_outbox", text)
        self.assertIn("hop_outbox->hop_mongo", text)

    def test_an_event_lost_by_mongodb_after_it_was_sent_is_a_confirmed_mismatch(self):
        relay_batch()
        store.collection().delete_one({"event_name": "ad.reaction"})
        self.export()
        ok, text = self.verify()
        self.assertFalse(ok)
        self.assertIn("FAIL hop_outbox->hop_mongo", text)

    def test_a_broken_generation_chain_is_reported(self):
        self.export()
        self.export()
        self.export()
        path = ndjson.manifest_path(self.dir / "hops", "hop_source")
        previous = ndjson.read_manifest(path)["previous_sha256"]
        (self.dir / "hops" / f"hop_source.manifest.{previous[:16]}.json").unlink()
        ok, text = self.verify()
        self.assertFalse(ok)
        self.assertIn("세대 사슬", text)

    def test_rewriting_a_manifest_outside_the_export_is_caught_by_the_audit_anchor(self):
        """폴더에 쓸 수 있는 사람이 그럴듯한 새 manifest 를 직접 게시해도, 감사 로그의 고정점과 달라 드러난다."""
        relay_batch()
        self.export()
        ndjson.write(self.dir / "hops", "hop_source", [], "hop_source", 1, checkpoint={"hop": "hop_source", "window": "utc-day", "open_windows": []}, chain=True)  # (모양은 올바르지만 감사 로그에 남지 않는 게시)
        ok, text = self.verify()
        self.assertFalse(ok)
        self.assertIn("고정점", text)
        self.assertNotIn("고정점", self.verify("--no-anchor")[1])  # 고정점 확인을 끄면 이 경고는 없다(다른 환경의 폴더용)

    def test_without_any_anchor_the_check_asks_for_no_anchor(self):
        relay_batch()
        self.export()
        from foundation.models import AuditLog

        AuditLog.objects.filter(action="events.hop_manifests_exported")._raw_delete(AuditLog.objects.db)  # (시험에서만: 추가 전용 규칙을 우회해 고정점이 없는 상태를 만든다)
        ok, text = self.verify()
        self.assertFalse(ok)
        self.assertIn("--no-anchor", text)
        self.assertTrue(self.verify("--no-anchor")[0])

    def test_a_modified_data_file_fails_the_input_check(self):
        relay_batch()
        self.export()
        manifest = ndjson.read_manifest(ndjson.manifest_path(self.dir / "hops", "hop_mongo"))
        data = self.dir / "hops" / manifest["file"]
        data.write_bytes(data.read_bytes().replace(b'"count":1', b'"count":7'))
        ok, text = self.verify()
        self.assertFalse(ok)
        self.assertIn("hop_mongo", text)
        self.assertIn("검증 실패", text)

    def test_a_pipeline_manifest_is_compared_with_the_mongodb_hop(self):
        relay_batch()
        self.export()
        pipeline_dir = self.dir / "pipeline"
        mongo_lines = self.lines("hop_mongo")
        ndjson.write(pipeline_dir, "pipeline", mongo_lines, "hop_pipeline", 1, checkpoint={"open_windows": [], "window": "utc-day"})
        ok, text = self.verify("--pipeline", str(ndjson.manifest_path(pipeline_dir, "pipeline")))
        self.assertTrue(ok, text)
        self.assertIn("'match': 16", text)
        bad = [dict(l, content_sha256="0" * 64) if l["event_name"] == "ad.charge" else l for l in mongo_lines]
        ndjson.write(pipeline_dir, "pipeline", bad, "hop_pipeline", 1, checkpoint={"open_windows": [], "window": "utc-day"})
        ok, text = self.verify("--pipeline", str(ndjson.manifest_path(pipeline_dir, "pipeline")))
        self.assertFalse(ok)
        self.assertIn("hop_mongo->pipeline", text)
        self.assertIn("content_sha256", text)

    def test_a_missing_hop_manifest_fails(self):
        self.export()
        ndjson.manifest_path(self.dir / "hops", "hop_outbox").unlink()
        ok, text = self.verify()
        self.assertFalse(ok)
        self.assertIn("hop_outbox", text)
