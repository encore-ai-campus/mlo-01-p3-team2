"""Step 4-3b: 구간별 정합 manifest — 정규화 규칙(JCS)·창·요약값, 세 구간의 게시, 세대 연결."""
import hashlib
import io
import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase, override_settings, tag

from events import hops, ndjson, store
from events.models import EventOutbox
from events.relay import relay_batch
from foundation.models import AuditLog
from records import api as records
from tests.factories import NOW, SUBJECT, World
from tests.mongo_support import MongoDatabaseMixin

UTC = timezone.utc


@tag("security")
class CanonicalJsonTests(SimpleTestCase):
    def test_rfc8785_sample(self):
        """RFC 8785 부록의 숫자·문자열·리터럴 예시."""
        sample = json.loads('{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001],"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/","literals":[null,true,false]}')
        self.assertEqual(hops.canonical_json(sample), '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}')

    def test_keys_sort_by_utf16_code_units_not_code_points(self):
        keys = ["€", "\r", "דּ", "1", "\U0001F600", "\u0080", "ö"]
        ordered = list(json.loads(hops.canonical_json({k: 1 for k in keys})).keys())
        self.assertEqual(ordered, ["\r", "1", "\u0080", "ö", "€", "\U0001F600", "דּ"])  # 😀(D83D DE00)가 U+FB33 보다 앞이다

    def test_number_formats_follow_ecmascript(self):
        for value, text in ((300.0, "300"), (0.5, "0.5"), (1e21, "1e+21"), (1e-7, "1e-7"), (0.000001, "0.000001"), (1.5e-10, "1.5e-10"), (-2.5, "-2.5"), (0.0, "0"), (2592000.0, "2592000")):
            self.assertEqual(hops.canonical_json(value), text)
        self.assertEqual(hops.canonical_json([1, 1.0, True, False, None]), "[1,1,true,false,null]")  # 불리언은 숫자와 다르다
        with self.assertRaises(ValueError):
            hops.canonical_json(float("nan"))

    def test_document_form_has_millisecond_utc_time_and_lowercase_ids(self):
        moment = datetime(2026, 10, 10, 3, 0, 1, 987654, tzinfo=UTC)
        doc = hops.normal_document(uuid.UUID("AAAAAAAA-0000-5000-8000-000000000001"), "ad.decision", 1, moment, {"a": 1})
        self.assertEqual((doc["event_id"], doc["produced_at"]), ("aaaaaaaa-0000-5000-8000-000000000001", "2026-10-10T03:00:01.987Z"))  # 반올림하지 않고 자른다


@tag("security")
class SummaryTests(SimpleTestCase):
    NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

    def doc(self, i, at, name="ad.decision", **payload):
        return hops.normal_document(uuid.UUID(int=i), name, 1, at, payload or {"n": i})

    def test_windows_are_utc_days_and_closed_only_after_the_grace(self):
        start = datetime(2026, 10, 9, tzinfo=UTC)
        docs = [self.doc(1, start + timedelta(hours=1)), self.doc(2, datetime(2026, 10, 10, 11, tzinfo=UTC))]  # 어제 창, 오늘 창(열림)
        lines, open_windows = hops.summarize(docs, self.NOW, 120)
        self.assertEqual([(l["window_start"], l["window_end"], l["count"]) for l in lines], [("2026-10-09T00:00:00Z", "2026-10-10T00:00:00Z", 1)])
        self.assertEqual(open_windows, [datetime(2026, 10, 10, tzinfo=UTC)])
        # 어제 창은 자정 + 2분 전까지는 아직 열려 있다
        self.assertEqual(hops.summarize(docs[:1], datetime(2026, 10, 10, 0, 1, 59, tzinfo=UTC), 120), ([], [start]))
        self.assertEqual(len(hops.summarize(docs[:1], datetime(2026, 10, 10, 0, 2, 0, tzinfo=UTC), 120)[0]), 1)

    def test_hashes_follow_the_documented_rules_and_ignore_order(self):
        at = datetime(2026, 10, 9, 5, tzinfo=UTC)
        docs = [self.doc(3, at), self.doc(1, at), self.doc(2, at)]
        (line,), _ = hops.summarize(docs, self.NOW, 120)
        ids = sorted(d["event_id"] for d in docs)
        self.assertEqual(line["ids_sha256"], hashlib.sha256("\n".join(ids).encode()).hexdigest())
        by_id = {d["event_id"]: d for d in docs}
        content = "\n".join(hops.canonical_json(by_id[i]) for i in ids)
        self.assertEqual(line["content_sha256"], hashlib.sha256(content.encode()).hexdigest())
        self.assertEqual(hops.summarize(list(reversed(docs)), self.NOW, 120)[0], [line])  # 들어온 순서는 상관없다

    def test_a_change_of_content_moves_only_the_content_hash_and_a_missing_event_moves_both(self):
        at = datetime(2026, 10, 9, 5, tzinfo=UTC)
        base = [self.doc(1, at), self.doc(2, at)]
        (line,), _ = hops.summarize(base, self.NOW, 120)
        (changed,), _ = hops.summarize([base[0], self.doc(2, at, n=99)], self.NOW, 120)
        self.assertEqual((changed["ids_sha256"] == line["ids_sha256"], changed["content_sha256"] == line["content_sha256"]), (True, False))
        (missing,), _ = hops.summarize(base[:1], self.NOW, 120)
        self.assertEqual((missing["count"], missing["ids_sha256"] == line["ids_sha256"], missing["content_sha256"] == line["content_sha256"]), (1, False, False))
        (typed,), _ = hops.summarize([base[0], self.doc(2, at, n=2, flag=True)], self.NOW, 120)
        (typed2,), _ = hops.summarize([base[0], self.doc(2, at, n=2, flag=1)], self.NOW, 120)
        self.assertNotEqual(typed["content_sha256"], typed2["content_sha256"])  # true 와 1 은 다르다

    def test_an_empty_window_group_is_not_listed_and_event_names_are_separate_lines(self):
        at = datetime(2026, 10, 9, 5, tzinfo=UTC)
        lines, _ = hops.summarize([self.doc(1, at), self.doc(2, at, name="ad.charge")], self.NOW, 120)
        self.assertEqual(sorted(l["event_name"] for l in lines), ["ad.charge", "ad.decision"])
        self.assertEqual(hops.summarize([], self.NOW, 120), ([], []))

    def test_since_drops_older_windows(self):
        old, new = datetime(2026, 10, 1, 5, tzinfo=UTC), datetime(2026, 10, 9, 5, tzinfo=UTC)
        lines, _ = hops.summarize([self.doc(1, old), self.doc(2, new)], self.NOW, 120, since=datetime(2026, 10, 5, tzinfo=UTC))
        self.assertEqual([l["window_start"] for l in lines], ["2026-10-09T00:00:00Z"])


@tag("security")
class ExportHopManifestsTests(MongoDatabaseMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        store.ensure()
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        w = World()
        self.decision = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))  # 2026-10-07 — 닫힌 창
        view, _ = records.receive_reaction(w.slot.media_id, self.decision.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
        records.process_reaction(view.inbox_id, now=NOW + timedelta(seconds=7))

    def export(self, *flags, out="out"):
        stdout = io.StringIO()
        try:
            call_command("export_hop_manifests", "--out", str(self.dir / out), *flags, stdout=stdout)
            return True, stdout.getvalue()
        except CommandError as error:
            return False, stdout.getvalue() + str(error)

    def lines(self, hop, out="out"):
        manifest = ndjson.read_manifest(ndjson.manifest_path(self.dir / out, hop))
        return [json.loads(l) for l in (self.dir / out / manifest["file"]).read_text().splitlines()], manifest

    def keyed(self, hop, **kw):
        return {(l["window_start"], l["event_name"]): l for l in self.lines(hop, **kw)[0]}

    def test_three_hops_agree_after_the_relay(self):
        relay_batch()
        ok, text = self.export()
        self.assertTrue(ok, text)
        source, outbox, mongo = (self.keyed(h) for h in ("hop_source", "hop_outbox", "hop_mongo"))
        self.assertEqual(sorted(source), sorted(outbox))
        self.assertEqual(len(source), 4)  # 이벤트 네 종류 × 창 하나(2026-10-07)
        for key in source:
            for field in ("count", "ids_sha256", "content_sha256", "window_end"):
                self.assertEqual(source[key][field], outbox[key][field], (key, field))
                self.assertEqual(source[key][field], mongo[key][field], (key, field))
            self.assertEqual(outbox[key]["unsent"], 0)

    def test_before_the_relay_mongodb_is_empty_and_outbox_shows_unsent(self):
        self.export()
        self.assertEqual(self.lines("hop_mongo")[0], [])
        self.assertTrue(all(l["unsent"] == 1 for l in self.lines("hop_outbox")[0]))  # 중계 지연 후보를 가리는 근거

    def test_manifests_describe_scope_and_are_valid(self):
        relay_batch()
        self.export()
        for hop in ("hop_source", "hop_outbox", "hop_mongo"):
            path = ndjson.manifest_path(self.dir / "out", hop)
            manifest = ndjson.read_manifest(path)
            self.assertEqual((ndjson.verify(path), manifest["source_kind"], manifest["schema_version"]), ([], hop, 1))
            cp = manifest["checkpoint"]
            self.assertEqual((cp["hop"], cp["window"], cp["grace_seconds"], cp["scanned_events"]), (hop, "utc-day", 120, 4))
        self.assertEqual(ndjson.read_manifest(ndjson.manifest_path(self.dir / "out", "hop_source"))["checkpoint"]["scope"], "mysql-repeatable-read-snapshot")
        self.assertEqual(ndjson.read_manifest(ndjson.manifest_path(self.dir / "out", "hop_mongo"))["checkpoint"]["scope"], "mongodb-read-outside-snapshot")

    def test_open_windows_are_not_summarized_but_listed(self):
        """오늘 창은 아직 열려 있다 — 줄에 넣지 않고 checkpoint 에만 적는다."""
        w = World()
        records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=datetime.now(UTC), rng=Random(2))
        self.export()
        today = hops.window_start(datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertNotIn(today, {l["window_start"] for l in self.lines("hop_source")[0]})
        self.assertIn(today, self.lines("hop_source")[1]["checkpoint"]["open_windows"])

    def test_the_grace_setting_changes_when_a_window_closes(self):
        with override_settings(EVENTS_HOP_GRACE_SECONDS=10**9):
            self.export(out="long")
        self.assertEqual(self.lines("hop_source", out="long")[0], [])  # 아주 긴 여유 — 어떤 창도 아직 닫히지 않았다
        self.assertEqual(len(self.lines("hop_source", out="long")[1]["checkpoint"]["open_windows"]), 1)

    def test_windows_older_than_the_outbox_retention_are_not_compared_with_the_outbox(self):
        with override_settings(EVENTS_OUTBOX_RETENTION_DAYS=1):  # 2026-10-07 창은 이미 보존 정리 범위 밖
            self.export()
        self.assertEqual(self.lines("hop_outbox")[0], [])
        checkpoint = self.lines("hop_outbox")[1]["checkpoint"]
        self.assertEqual(checkpoint["not_comparable_windows"], ["2026-10-07T00:00:00Z"])
        self.assertTrue(self.lines("hop_source")[0] and self.lines("hop_source")[0] != [])  # 원본 구간에는 그대로 있다

    def test_a_tampered_hop_is_visible_from_the_manifests_alone(self):
        relay_batch()
        row = EventOutbox.objects.get(event_name="ad.charge")
        payload = row.payload
        payload["charged_amount"] = 999
        EventOutbox.objects.filter(pk=row.pk).update(payload=payload)
        self.export()
        key = ("2026-10-07T00:00:00Z", "ad.charge")
        source, outbox, mongo = (self.keyed(h)[key] for h in ("hop_source", "hop_outbox", "hop_mongo"))
        self.assertEqual(source["ids_sha256"], outbox["ids_sha256"])  # 존재는 같고
        self.assertNotEqual(source["content_sha256"], outbox["content_sha256"])  # 내용만 다르다
        self.assertEqual(source["content_sha256"], mongo["content_sha256"])

    def test_the_same_data_gives_the_same_lines(self):
        relay_batch()
        self.export(out="a")
        self.export(out="b")
        for hop in ("hop_source", "hop_outbox", "hop_mongo"):
            self.assertEqual(self.lines(hop, out="a")[0], self.lines(hop, out="b")[0])
            self.assertEqual(ndjson.read_manifest(ndjson.manifest_path(self.dir / "a", hop))["file"], ndjson.read_manifest(ndjson.manifest_path(self.dir / "b", hop))["file"])  # 같은 내용 = 같은 데이터 파일

    def test_generations_are_chained_and_the_audit_log_holds_the_anchor(self):
        self.export()
        first = {h: ndjson.manifest_sha256(ndjson.manifest_path(self.dir / "out", h)) for h in ("hop_source", "hop_outbox", "hop_mongo")}
        relay_batch()  # 상태가 바뀐 뒤 다시 낸다 = 새 세대
        self.export()
        for hop in first:
            path = ndjson.manifest_path(self.dir / "out", hop)
            self.assertEqual(ndjson.read_manifest(path)["previous_sha256"], first[hop])
            self.assertEqual(ndjson.verify_chain(path), [])
        audits = list(AuditLog.objects.filter(action="events.hop_manifests_exported").order_by("created_at"))
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[1].detail["anchors"]["hop_source"], ndjson.manifest_sha256(ndjson.manifest_path(self.dir / "out", "hop_source")))  # 폴더 밖의 고정점
        self.assertEqual(audits[0].detail["anchors"], first)

    def test_a_missing_or_changed_previous_generation_breaks_the_chain(self):
        self.export()
        self.export()
        self.export()
        path = ndjson.manifest_path(self.dir / "out", "hop_source")
        previous = ndjson.read_manifest(path)["previous_sha256"]
        copy = self.dir / "out" / f"hop_source.manifest.{previous[:16]}.json"
        copy.write_text(copy.read_text().replace('"rows"', '"rows "'))
        self.assertIn("바뀌었다", " ".join(ndjson.verify_chain(path)))
        copy.unlink()
        self.assertIn("없다", " ".join(ndjson.verify_chain(path)))

    def test_mongodb_unreachable_fails_without_publishing(self):
        from events import mongo

        with override_settings(EVENT_STORE={**mongo.config(), "HOSTS": ["127.0.0.1:1"], "REPLICA_SET": None}):
            mongo.close()
            ok, text = self.export()
            mongo.close()
        self.assertFalse(ok)
        self.assertIn("MongoDB", text)
        self.assertFalse((self.dir / "out").exists())

    def test_since_option(self):
        ok, _ = self.export("--since", "2026-10-08")
        self.assertTrue(ok)
        self.assertEqual(self.lines("hop_source")[0], [])  # 2026-10-07 창은 제외
        self.assertFalse(self.export("--since", "어제")[0])
