"""Step 4-3b: 구간별 정합 manifest — 정규화 규칙(JCS)·창·요약값, 세 구간의 게시, 세대 연결."""
import hashlib
import io
import json
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings, tag

from billing import api as billing
from events import api as events, hops, ndjson, store
from events.models import EventOutbox
from events.relay import relay_batch
from foundation.models import AuditLog
from records import api as records
from records.models import Decision, Reaction
from records.processing import reaction_ref
from tests.factories import DAY, NOW, SUBJECT, World
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

    def test_hour_windows_are_utc_hours(self):
        at = datetime(2026, 10, 9, 5, 30, tzinfo=UTC)
        lines, open_windows = hops.summarize([self.doc(1, at), self.doc(2, at + timedelta(minutes=45))], self.NOW, 120, size=hops.HOUR)
        self.assertEqual([(l["window_start"], l["window_end"], l["count"]) for l in lines], [("2026-10-09T05:00:00Z", "2026-10-09T06:00:00Z", 1), ("2026-10-09T06:00:00Z", "2026-10-09T07:00:00Z", 1)])
        self.assertEqual(hops.summarize([self.doc(1, datetime(2026, 10, 10, 11, 59, tzinfo=UTC))], datetime(2026, 10, 10, 12, 1, tzinfo=UTC), 120, size=hops.HOUR), ([], [datetime(2026, 10, 10, 11, tzinfo=UTC)]))  # 여유 2분이 안 됐다

    def test_since_drops_older_windows(self):
        old, new = datetime(2026, 10, 1, 5, tzinfo=UTC), datetime(2026, 10, 9, 5, tzinfo=UTC)
        lines, _ = hops.summarize([self.doc(1, old), self.doc(2, new)], self.NOW, 120, since=datetime(2026, 10, 5, tzinfo=UTC))
        self.assertEqual([l["window_start"] for l in lines], ["2026-10-09T00:00:00Z"])


@tag("security")
class WindowedSummaryTests(TestCase):
    """외부 검토(00d3067) P3-3: 내보내기는 닫힌 창을 하나씩·종류별로 읽어 요약한다 — 전체 이력을 메모리에 두지 않고, 결과는 전부 읽어 한 번에 요약한 것과 같다."""

    AS_OF = NOW + 3 * DAY  # 2026-10-10 12:00 — 10-09 까지의 창은 닫혔고 10-10 은 열려 있다
    SINCE = datetime(2026, 10, 7, tzinfo=UTC)
    STREAM = {events.NAMES["decision"]: "결정", events.NAMES["reaction_received"]: "접수", events.NAMES["reaction"]: "처리", events.NAMES["charge"]: "처리"}  # 과금은 판정과 같은 시각

    def setUp(self):
        w = World(ends_in=None)
        edge = NOW + DAY + timedelta(hours=11, minutes=59, seconds=58)  # 10-08 23:59:58 에 받고 10-09 00:00:05 에 처리 — 접수와 판정·과금의 창이 다르다
        midnight = datetime(2026, 10, 8, tzinfo=UTC)  # 창 경계에 딱 놓인 행은 뒤 창의 것
        for at in (NOW - DAY, NOW, midnight, NOW + DAY, NOW + DAY, edge, NOW + 2 * DAY, NOW + 3 * DAY):  # 10-06(--since 앞) ~ 10-10(열린 창)
            d = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=at, rng=Random(1))
            view, _ = records.receive_reaction(w.slot.media_id, d.decision_id, uuid.uuid4(), "IMPRESSION", at, {"type": "IMPRESSION"}, now=at)
            if at != NOW + DAY:
                records.process_reaction(view.inbox_id, now=at + timedelta(seconds=7))  # 10-08 낮의 반응은 아직 판정 전(처리 시각 없음)

    def everything(self):
        """전부 읽은 기대 이벤트(예전 방식의 입력)."""
        return [events.normal_document(i, name, events.SCHEMA_VERSION, at, payload) for i, (name, _key, at, payload) in records.expected_events().items()]

    def test_the_source_hop_matches_summarizing_everything_at_once(self):
        docs = self.everything()
        self.assertEqual({d["event_name"] for d in docs}, set(self.STREAM))  # 네 종류가 모두 있다(과금 포함)
        for since, size in ((None, hops.DAY), (self.SINCE, hops.DAY), (None, hops.HOUR)):
            lines, open_windows, _read, _largest = events.summarize_windows(records.source_streams(), self.AS_OF, 120, since, size)
            self.assertEqual((lines, open_windows), events.summarize(docs, self.AS_OF, 120, since, size), (since, size))

    def test_the_outbox_hop_matches_summarizing_everything_at_once(self):
        docs = [events.normal_document(r.event_id, r.event_name, r.schema_version, r.created_at, r.payload) for r in EventOutbox.objects.all()]
        for since, size in ((None, hops.DAY), (self.SINCE, hops.DAY), (None, hops.HOUR)):
            lines, open_windows, _read, _largest = events.summarize_windows(events.outbox_streams(), self.AS_OF, 120, since, size)
            self.assertEqual((lines, open_windows), events.summarize(docs, self.AS_OF, 120, since, size), (since, size))

    def test_it_reads_only_closed_windows_after_since_one_window_and_kind_at_a_time(self):
        _lines, _open, read, largest = events.summarize_windows(records.source_streams(), self.AS_OF, 120, self.SINCE)
        produced = [(hops.window_start(hops._produced(d)), self.STREAM[d["event_name"]]) for d in self.everything()]
        in_range = Counter(key for key in produced if self.SINCE <= key[0] < hops.window_start(self.AS_OF))
        self.assertEqual(read, sum(in_range.values()))  # --since 앞(10-06)과 열린 창(10-10)의 행은 읽지 않는다
        self.assertLess(read, len(produced))
        self.assertEqual(largest, max(in_range.values()))  # 한 번에 든 것은 창 하나·종류 하나

    def test_unresolved_charges_are_counted_without_holding_the_ledger(self):
        """창에 놓을 수 없는 과금 원장 줄(반응이 없음·판정 전·키 형식이 틀림)만 센다. 원장을 묶음으로 이어 읽어도(묶음 1) 결과가 같다."""
        self.assertEqual(records.unresolved_charges(), (0, []))  # 정상 과금은 모두 판정한 반응이 있다
        w = World(ends_in=None)
        pending, _ = records.receive_reaction(w.slot.media_id, records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(5)).decision_id,
                                              uuid.uuid4(), "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)  # 받았지만 판정 전
        refs = [f"{w.slot.media_id}:{uuid.uuid4()}", f"{w.slot.media_id}:{pending.reaction_id}", "형식이-틀린-키"]
        for ref in refs:
            billing.charge_for_reaction(w.adv.pk, w.campaign.campaign_id, "IMPRESSION", "IMPRESSION", 10, ref, now=NOW)
        entries = [e.entry_id for e in billing.charge_entries_for(refs)]
        count, examples = records.unresolved_charges()
        self.assertEqual((count, sorted(examples)), (3, sorted(str(e) for e in entries)))
        self.assertEqual(records.unresolved_charges(batch=1), (count, examples))
        self.assertEqual(records.unresolved_charges(examples=2)[1], examples[:2])

    def test_the_reaction_lookup_reads_only_the_charged_pairs(self):
        """재검토(5e8fa8c) P3: 반응 조회가 매체 집합 × 반응 ID 집합의 교차 조합을 읽었다(키 B개에 최대 B²행). 정확한 (매체, 반응) 쌍만 읽는다.
        매체 넷이 같은 반응 ID 넷을 모두 판정했고 과금은 대각선 넷뿐 — 한 묶음(4)의 조회가 4행을 넘지 않는다."""
        ids, worlds = [uuid.uuid4() for _ in range(4)], [World(ends_in=None) for _ in range(4)]
        for i, w in enumerate(worlds):
            d = records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(i))
            for reaction_id in [ids[i]] + [x for x in ids if x != ids[i]]:  # 대각선이 먼저 인정·과금되고 나머지는 같은 사람의 중복이라 판정만 된다
                view, _ = records.receive_reaction(w.slot.media_id, d.decision_id, reaction_id, "IMPRESSION", NOW, {"type": "IMPRESSION"}, now=NOW)
                records.process_reaction(view.inbox_id, now=NOW)
        self.assertEqual(Reaction.objects.filter(media_id__in=[w.slot.media_id for w in worlds], processed_at__isnull=False).count(), 16)
        self.assertEqual(len(billing.charge_entries_for([reaction_ref(w.slot.media_id, ids[i]) for i, w in enumerate(worlds)])), 4)
        fetched = []

        def count_rows(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if "FROM `records_reaction`" in sql:
                fetched.append(context["cursor"].rowcount)
            return result
        with connection.execute_wrapper(count_rows):
            self.assertEqual(records.unresolved_charges(batch=4)[0], 0)
        self.assertTrue(fetched)
        self.assertLessEqual(max(fetched), 4, fetched)

    def test_unsent_counts_read_only_the_unsent_rows(self):
        EventOutbox.objects.filter(event_name=events.NAMES["charge"]).update(sent_at=NOW)
        expected = Counter((events.format_time(hops.window_start(r.created_at, hops.HOUR)), r.event_name) for r in EventOutbox.objects.filter(sent_at__isnull=True))
        self.assertEqual(events.unsent_counts(size=hops.HOUR), dict(expected))
        self.assertNotIn(events.NAMES["charge"], {name for _, name in events.unsent_counts()})


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

    def test_several_windows_agree_and_only_the_range_is_read(self):
        """창 여러 개(--since 앞의 창 포함): 세 구간이 창마다 같고, 읽은 이벤트 수는 범위 안의 것뿐이다. 실행 결과에 한 번에 든 최대 이벤트 수와 최대 메모리를 적는다."""
        w = World()
        for at in (NOW - 2 * DAY, datetime(2026, 10, 8, tzinfo=UTC)):  # 10-05(--since 앞), 10-08 의 시작(창 경계)
            records.decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT, now=at, rng=Random(3))
        relay_batch()
        ok, text = self.export("--since", "2026-10-07", "--as-of", "2026-10-10T00:05:00Z")
        self.assertTrue(ok, text)
        hop_lines = {h: self.lines(h) for h in ("hop_source", "hop_outbox", "hop_mongo")}
        self.assertEqual([l["window_start"][:10] for l in hop_lines["hop_source"][0]], ["2026-10-07"] * 4 + ["2026-10-08"])
        for hop, (lines, manifest) in hop_lines.items():
            self.assertEqual([(l["count"], l["ids_sha256"], l["content_sha256"]) for l in lines], [(l["count"], l["ids_sha256"], l["content_sha256"]) for l in hop_lines["hop_source"][0]], hop)
            self.assertEqual(manifest["checkpoint"]["scanned_events"], 5, hop)  # 10-05 의 결정은 읽지 않는다
        self.assertRegex(text, r"hop_source: rows=5 events=5 open_windows=0 largest_window=\d+ ")
        self.assertRegex(text, r"peak_rss=\d+(\.\d)?MiB")

    def test_a_charge_that_cannot_be_placed_in_a_window_fails_the_export_and_the_check(self):
        """외부 검토(e781f20) P2 재현: 반응이 없는 과금 원장 줄(잔액·원장은 서로 맞음, 이벤트 없음)이 원본 구간에서 조용히 빠져 내보내기·대조가 '일치'로 끝났다.
        생성 시각을 정할 수 없으니 추정하지 않고 미해결로 남긴다 — 내보내기는 게시한 뒤 실패로 끝나고 verify_hops 도 실패한다. 정상 이벤트의 대조는 그대로 한다."""
        relay_batch()
        w = World()
        ref = f"{w.slot.media_id}:{uuid.uuid4()}"
        billing.charge_for_reaction(w.adv.pk, w.campaign.campaign_id, "IMPRESSION", "IMPRESSION", 30, ref, now=NOW)
        (orphan,) = billing.charge_entries_for([ref])
        self.assertEqual(billing.check_ledger(), [])  # 원장 자체는 맞다 — 이 점검만으로는 보이지 않는다
        ok, text = self.export()
        self.assertFalse(ok, text)
        self.assertIn("창에 놓을 수 없는 과금 원장 줄 1건", text)
        checkpoint = self.lines("hop_source")[1]["checkpoint"]
        self.assertEqual((checkpoint["unresolved_charges"], checkpoint["unresolved_charge_examples"]), (1, [str(orphan.entry_id)]))
        ok, text = self.verify()
        self.assertFalse(ok, text)
        self.assertIn(f"FAIL hop_source: 창에 놓을 수 없는 과금 원장 줄 1건(반응이 없거나 판정 전, 예: {orphan.entry_id})", text)
        self.assertIn("결과: {'match': 12}", text)  # 정상 이벤트 네 건의 대조는 그대로

    def test_a_charge_key_that_only_looks_like_a_judged_reactions_key_is_unresolved(self):
        """재검토(5e8fa8c) P2 재현: 판정한 반응의 키를 다른 UUID 표기(대문자·하이픈 없음·중괄호)로 바꾼 과금 세 건이 원본 구간의 문자열 조회에도,
        UUID 로 해석하는 미해결 검사에도 걸리지 않아 '일치'로 끝났다. 키는 반응에서 만든 표준 문자열과 정확히 같아야 그 반응의 과금이다."""
        relay_batch()
        r = Reaction.objects.get()
        decision = Decision.objects.get(pk=r.decision_id)
        for ref in (f"{str(r.media_id).upper()}:{r.reaction_id}", f"{r.media_id.hex}:{r.reaction_id}", f"{{{r.media_id}}}:{r.reaction_id}"):
            billing.charge_for_reaction(decision.owner_id, decision.campaign_id, "IMPRESSION", "IMPRESSION", 30, ref, now=NOW)
        self.assertEqual(billing.check_ledger(), [])
        ok, text = self.export()
        self.assertFalse(ok, text)
        self.assertIn("창에 놓을 수 없는 과금 원장 줄 3건", text)
        ok, text = self.verify()
        self.assertFalse(ok, text)
        self.assertIn("결과: {'match': 12}", text)  # 정상 이벤트 네 건의 대조는 그대로

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

    def verify(self, directory="out", *flags):
        stdout = io.StringIO()
        try:
            call_command("verify_hops", "--dir", str(self.dir / directory), *flags, stdout=stdout)
            return True, stdout.getvalue()
        except CommandError as error:
            return False, stdout.getvalue() + str(error)

    def test_a_normal_retention_purge_is_not_mistaken_for_corruption(self):
        """검토 P2-2 재현: 보존 기간이 지나 outbox 행이 모두 지워진 창은 '대조 제외'로 남아야 한다 — 행이 사라졌다고 제외 정보까지 사라져 확정 불일치가 되면 안 된다."""
        relay_batch()
        with override_settings(EVENTS_OUTBOX_RETENTION_DAYS=1):
            self.export(out="before")
            self.assertTrue(self.verify("before", "--no-anchor")[0])
            call_command("purge_sent_events", "--days", "0", stdout=io.StringIO())  # 실제 보존 정리
            self.assertEqual(EventOutbox.objects.count(), 0)
            self.export(out="after")
        checkpoint = self.lines("hop_outbox", out="after")[1]["checkpoint"]
        self.assertEqual(checkpoint["not_comparable_windows"], ["2026-10-07T00:00:00Z"])  # 줄이 하나도 없어도 제외 정보는 남는다
        ok, text = self.verify("after", "--no-anchor")
        self.assertTrue(ok, text)
        self.assertNotIn("FAIL", text)
        self.assertIn("not_comparable", text)
        self.assertEqual(self.lines("hop_source", out="after")[0], self.lines("hop_mongo", out="after")[0])  # 원본과 MongoDB 는 그대로 대조된다

    def test_the_retention_cutoff_inside_a_window_makes_the_whole_window_not_comparable(self):
        """보존 기준 시각이 창의 한가운데에 걸리면, 그 창의 앞부분 행은 이미 지워졌을 수 있다 — 창 전체를 대조에서 뺀다."""
        relay_batch()
        with override_settings(EVENTS_OUTBOX_RETENTION_DAYS=3):
            self.export("--as-of", "2026-10-10T12:00:00Z", out="mid")  # 기준 시각 = 2026-10-07 12:00:00, 창 2026-10-07 의 한가운데
        self.assertEqual(self.lines("hop_outbox", out="mid")[1]["checkpoint"]["not_comparable_windows"], ["2026-10-07T00:00:00Z"])
        self.assertEqual(self.lines("hop_outbox", out="mid")[0], [])
        with override_settings(EVENTS_OUTBOX_RETENTION_DAYS=4):  # 기준 시각이 창 시작보다 앞: 대조한다
            self.export("--as-of", "2026-10-10T12:00:00Z", out="clear")
        self.assertEqual(self.lines("hop_outbox", out="clear")[1]["checkpoint"]["not_comparable_windows"], [])
        self.assertEqual(len(self.lines("hop_outbox", out="clear")[0]), 4)

    def test_hour_windows_use_the_exact_cutoff_too(self):
        relay_batch()
        with override_settings(EVENTS_OUTBOX_RETENTION_DAYS=3):
            self.export("--window", "hour", "--as-of", "2026-10-10T12:30:00Z", out="hour")  # 기준 시각 12:30 — 이벤트가 있는 창(12:00~13:00)의 한가운데
        self.assertEqual(self.lines("hop_outbox", out="hour")[1]["checkpoint"]["not_comparable_windows"], ["2026-10-07T12:00:00Z"])

    def test_windows_older_than_the_outbox_retention_are_not_compared_with_the_outbox(self):
        with override_settings(EVENTS_OUTBOX_RETENTION_DAYS=1):  # 2026-10-07 창은 이미 보존 정리 범위 밖
            self.export()
        self.assertEqual(self.lines("hop_outbox")[0], [])
        checkpoint = self.lines("hop_outbox")[1]["checkpoint"]
        self.assertEqual(checkpoint["not_comparable_windows"], ["2026-10-07T00:00:00Z"])
        self.assertTrue(self.lines("hop_source")[0] and self.lines("hop_source")[0] != [])  # 원본 구간에는 그대로 있다

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

    def test_the_audit_anchor_is_the_manifest_this_run_published_even_if_another_run_replaced_the_pointer(self):
        """검토 P2-4: 쓴 직후 다른 실행이 포인터를 바꿔도 감사 로그의 고정점은 이 실행이 게시한 manifest 의 해시다."""
        from events import api as events_api

        real, published = events_api.write_ndjson, {}

        def write_then_get_replaced(directory, name, rows, kind, version, **kw):
            manifest = real(directory, name, rows, kind, version, **kw)
            published[name] = manifest
            other = real(directory, name, rows, kind, version, **{**kw, "checkpoint": {**kw["checkpoint"], "intruder": True}})  # 다른 실행의 게시(이 실행 직후)
            return manifest

        with mock.patch("records.management.commands.export_hop_manifests.events.write_ndjson", write_then_get_replaced):
            self.export()
        anchors = AuditLog.objects.get(action="events.hop_manifests_exported").detail["anchors"]
        for hop, manifest in published.items():
            self.assertEqual(anchors[hop], ndjson.manifest_digest(manifest), hop)
            self.assertNotEqual(anchors[hop], ndjson.manifest_sha256(ndjson.manifest_path(self.dir / "out", hop)))  # 포인터는 이미 다른 실행의 것이다

    def test_two_overlapping_exports_leave_the_latest_audit_anchor_equal_to_the_published_pointer(self):
        """재검토 P2: 세 manifest 게시부터 감사 로그 커밋까지가 한 실행 단위여야 한다 — 겹쳐 실행해도 정상 폴더가 고정점 불일치로 거부되면 안 된다."""
        import threading

        from django.db import connections
        from records.management.commands import export_hop_manifests

        real_audit, release, a_at_audit = export_hop_manifests.record_audit, threading.Event(), threading.Event()

        def audit(*args, **kwargs):
            if threading.current_thread().name == "export-A":
                a_at_audit.set()  # A 는 세 manifest 를 게시한 뒤 감사 로그 기록 직전에서 멈춘다
                release.wait(10)
            return real_audit(*args, **kwargs)

        results = {}

        def run(label):
            try:
                results[label] = self.export()[0]
            finally:
                connections.close_all()

        with mock.patch("records.management.commands.export_hop_manifests.record_audit", audit):
            a = threading.Thread(target=run, args=("A",), name="export-A")
            b = threading.Thread(target=run, args=("B",), name="export-B")
            a.start()
            self.assertTrue(a_at_audit.wait(10))
            b.start()
            b.join(1.5)  # 직렬화되어 있으면 B 는 A 가 끝날 때까지 기다린다
            release.set()
            a.join(30)
            b.join(30)
        self.assertEqual(results, {"A": True, "B": True})
        call_command("verify_hops", "--dir", str(self.dir / "out"), stdout=io.StringIO())  # 기본값(고정점 대조 포함) — CommandError 가 나면 실패
        for hop in ("hop_source", "hop_outbox", "hop_mongo"):
            self.assertEqual(ndjson.verify_chain(ndjson.manifest_path(self.dir / "out", hop)), [])
        self.assertEqual(AuditLog.objects.filter(action="events.hop_manifests_exported").count(), 2)

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

    def test_each_window_option_round_trips_from_the_exporter_to_the_checker(self):
        """계획 4-4d: 창 옵션마다 내보낸 선언(줄 버전, checkpoint.window, 창 경계, 열린 창·보존 기준 시각)을 대조 쪽이 그대로 읽는다."""
        from events import hopcheck

        relay_batch()
        for option, size in hops.WINDOWS.items():
            self.assertTrue(self.export("--window", option, out=option)[0], option)
            call_command("verify_hops", "--dir", str(self.dir / option), stdout=io.StringIO())  # 바로 뒤라 최신 감사 고정점이 이 폴더다
            for hop in ("hop_source", "hop_outbox", "hop_mongo"):
                loaded = hopcheck.load_hop(ndjson.manifest_path(self.dir / option, hop), expected_kind=hop)
                self.assertEqual(hops.WINDOW_SIZES[loaded.window], size, (option, hop))
                self.assertTrue(loaded.lines, (option, hop))
                for start, _ in loaded.lines:
                    self.assertEqual(hops.parse_time(start), hops.window_start(hops.parse_time(start), size))
            cutoff = self.lines("hop_outbox", out=option)[1]["checkpoint"]["retention_cutoff"]
            self.assertIsInstance(hops.parse_time(cutoff), datetime)

    def test_window_option_and_as_of(self):
        relay_batch()
        self.assertTrue(self.export("--window", "hour", out="h")[0])
        line = self.lines("hop_source", out="h")[0][0]
        self.assertEqual((line["window_start"], line["window_end"]), ("2026-10-07T12:00:00Z", "2026-10-07T13:00:00Z"))
        self.assertEqual(self.lines("hop_source", out="h")[1]["checkpoint"]["window"], "utc-hour")
        # 재현용 기준 시각: 과거로 잡으면 어떤 창도 아직 닫히지 않았다
        self.export("--as-of", "2026-10-07T12:30:00Z", out="early")
        self.assertEqual(self.lines("hop_source", out="early")[0], [])
        self.assertEqual(len(self.lines("hop_source", out="early")[1]["checkpoint"]["open_windows"]), 1)
        self.assertFalse(self.export("--as-of", "내일", out="bad")[0])

    def test_since_option(self):
        ok, _ = self.export("--since", "2026-10-08")
        self.assertTrue(ok)
        self.assertEqual(self.lines("hop_source")[0], [])  # 2026-10-07 창은 제외
        self.assertFalse(self.export("--since", "어제")[0])
