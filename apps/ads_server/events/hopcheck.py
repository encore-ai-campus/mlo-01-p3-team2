"""구간별 정합 manifest 대조(계획 4-3c). `export_hop_manifests` 가 낸 manifest(또는 파이프라인 쪽이 같은 규칙으로 낸 것) 두 개를 (창, 이벤트 이름)별로 맞춰 본다.

판정 분류(설계 §6.3a, DRD §5.6):
- `match`: 건수·`ids_sha256`·`content_sha256` 이 모두 같다.
- `mismatch`: **확정 불일치**. 어느 필드가 다른지 `fields` 에 적는다.
- `relay_lag_candidate`: 중계 지연 후보 — MongoDB(또는 파이프라인) 쪽이 outbox 보다 적고 outbox 에 미전송이 남아 있다. 다시 낸 manifest 로 다시 확인한다(실패가 아니다).
- `open_window`: 한쪽에서 아직 열려 있는 창이라 비교하지 않는다.
- `not_comparable`: outbox 가 보존 정리로 비교할 수 없는 창.
"""
import json
from pathlib import Path

from . import ndjson

MATCH, MISMATCH, LAG, OPEN, NOT_COMPARABLE = "match", "mismatch", "relay_lag_candidate", "open_window", "not_comparable"
FIELDS = ("count", "ids_sha256", "content_sha256")


class HopInputError(Exception):
    pass


class Hop:
    def __init__(self, name, manifest, lines):
        self.name, self.manifest, self.lines = name, manifest, lines
        checkpoint = manifest.get("checkpoint") or {}
        self.open_windows = set(checkpoint.get("open_windows", []))
        self.not_comparable = set(checkpoint.get("not_comparable_windows", []))

    def line(self, key):
        return self.lines.get(key)


def load_hop(manifest_path, name=None):
    """manifest 와 데이터 파일을 검증하고(SHA-256·행 수·형식) 줄을 읽는다. 검증에 실패하면 `HopInputError`."""
    manifest_path = Path(manifest_path)
    try:
        problems = ndjson.verify(manifest_path)
        manifest = ndjson.read_manifest(manifest_path)
    except ndjson.NdjsonError as error:
        raise HopInputError(str(error))
    if problems:
        raise HopInputError(f"{manifest_path.name} 검증 실패: " + "; ".join(problems))
    lines = {}
    for text in (manifest_path.parent / manifest["file"]).read_text(encoding="utf-8").splitlines():
        line = json.loads(text)
        lines[(line["window_start"], line["event_name"])] = line
    return Hop(name or manifest.get("source_kind", manifest_path.name), manifest, lines)


def compare(a, b, unsent_from=None):
    """두 구간을 대조한다. `a` 가 상류, `b` 가 하류다. `unsent_from`: 미전송 건수(`unsent`)를 가진 outbox 구간 — `b` 가 MongoDB·파이프라인일 때 지연 후보를 가리는 데 쓴다.
    반환: 줄(dict) 목록 — `{"pair", "window_start", "event_name", "status", "fields", "a", "b"}`."""
    out = []
    pair = f"{a.name}->{b.name}"
    for key in sorted(a.lines.keys() | b.lines.keys()):
        window, name = key
        la, lb = a.line(key), b.line(key)
        status, fields = _classify(a, b, key, la, lb, unsent_from)
        out.append({"pair": pair, "window_start": window, "event_name": name, "status": status, "fields": fields,
                    "a": _summary(la), "b": _summary(lb)})
    # 줄이 하나도 없는 열린 창·비교 불가 창도 기록으로 남긴다(조용히 사라지지 않게)
    for window in sorted((a.open_windows | b.open_windows) - {k[0] for k in a.lines.keys() | b.lines.keys()}):
        out.append({"pair": pair, "window_start": window, "event_name": None, "status": OPEN, "fields": [], "a": None, "b": None})
    return out


def _summary(line):
    return None if line is None else {f: line[f] for f in FIELDS} | ({"unsent": line["unsent"]} if "unsent" in line else {})


def _classify(a, b, key, la, lb, unsent_from):
    window = key[0]
    if window in a.open_windows or window in b.open_windows:
        return OPEN, []
    if window in a.not_comparable or window in b.not_comparable:
        return NOT_COMPARABLE, []
    if la is not None and lb is not None and all(la[f] == lb[f] for f in FIELDS):
        return MATCH, []
    fields = [f for f in FIELDS if (la or {}).get(f) != (lb or {}).get(f)] if la and lb else ["line_missing_in_" + ("b" if lb is None else "a")]
    if _is_lag(a, b, key, la, lb, unsent_from):
        return LAG, fields
    return MISMATCH, fields


def _is_lag(a, b, key, la, lb, unsent_from):
    """하류가 상류보다 적고, 그 (창, 이름)에 미전송이 남아 있으면 중계 지연 후보다. 내용이 다른데 건수는 같거나 하류가 더 많으면 지연이 아니다."""
    upstream_count, downstream_count = (la or {}).get("count", 0), (lb or {}).get("count", 0)
    if downstream_count >= upstream_count:
        return False
    holder = a if "hop_outbox" in a.name else unsent_from
    if holder is None:
        return False
    line = holder.line(key)
    return bool(line and line.get("unsent", 0) > 0)
