"""이벤트 백필(계획 4-3a, 설계 §6.3a): 이벤트가 없는 원본 행에 이벤트를 채운다.

- 입력은 `verify_ndjson` 을 통과한 `event_gaps` manifest 다. 목록은 *어떤 원본 행*인지만 알려 주고, **이벤트 내용은 원본 MySQL 행에서 다시 만든다**.
  목록에 적힌 값(이벤트 ID 포함)은 믿지 않고, 원본 행에서 다시 계산한 이벤트 ID 와 대조한다.
- 라이브 경로와 **같은 코드**로 만든다(`services._record_*_event`, `processing.judged_event`·`charge_event`) · 생성 시각도 같은 원본 시각 → 백필한 이벤트는 라이브 이벤트와 같다.
- 이벤트 ID 가 결정적이고 outbox 쓰기가 "이미 있으면 바꾸지 않음"이라 라이브 처리와 동시에 돌거나 두 번 돌아도 같은 이벤트가 둘 생기지 않는다.
- 추측하지 않는다: 원본 행이 없거나 과금의 반응을 못 찾으면 `unresolved` 로 남기고 쓰지 않는다.
"""
import json
import uuid
from dataclasses import dataclass, field
from itertools import batched
from pathlib import Path

from django.db import transaction

from billing import api as billing
from events import api as events
from foundation.api import record_audit

from . import processing, services
from .models import Decision, Reaction

CHUNK = 500
SOURCE_KINDS = {"ad.decision": "decision", "ad.reaction_received": "reaction", "ad.reaction": "reaction", "ad.charge": "ledger_charge"}
# 결과의 한 줄이 가질 수 있는 판정
WRITTEN, WOULD_WRITE, ALREADY, UNRESOLVED, NOT_JUDGED = "written", "would_write", "already_present", "unresolved", "skipped_not_judged"


class InvalidInput(Exception):
    """입력 목록이 쓸 수 없다(검증 실패·형식 오류). 아무것도 쓰지 않는다."""


@dataclass
class Item:
    event_name: str
    source_kind: str
    source_id: uuid.UUID
    event_id: uuid.UUID


@dataclass
class Outcome:
    item: Item
    outcome: str
    reason: str = ""
    legacy_basis: bool = False

    def as_record(self):
        return {
            "event_id": str(self.item.event_id), "event_name": self.item.event_name, "source_kind": self.item.source_kind, "source_id": str(self.item.source_id),
            "outcome": self.outcome, "reason": self.reason, "legacy_basis": self.legacy_basis,
        }


@dataclass
class Result:
    outcomes: list = field(default_factory=list)
    input_sha256: str = ""
    applied: bool = False

    def counts(self):
        counts = {WRITTEN: 0, WOULD_WRITE: 0, ALREADY: 0, UNRESOLVED: 0, NOT_JUDGED: 0, "legacy_basis": 0}
        for o in self.outcomes:
            counts[o.outcome] += 1
            counts["legacy_basis"] += o.legacy_basis
        return counts


def read_items(manifest_path):
    """검증을 통과한 `event_gaps` manifest 에서 항목을 읽는다. 형식이 맞지 않으면 `InvalidInput`."""
    manifest_path = Path(manifest_path)
    try:
        problems = events.verify_ndjson(manifest_path)
    except events.NdjsonError as error:
        raise InvalidInput(str(error))
    if problems:
        raise InvalidInput("입력 manifest 검증 실패: " + "; ".join(problems))
    manifest = events.read_manifest(manifest_path)
    if manifest["source_kind"] != "event_gaps":
        raise InvalidInput(f"event_gaps manifest 가 아니다(source_kind={manifest['source_kind']})")
    items = []
    for number, line in enumerate((manifest_path.parent / manifest["file"]).read_text(encoding="utf-8").splitlines(), 1):
        record = json.loads(line)
        try:
            name, kind = record["event_name"], record["source_kind"]
            source_id, event_id = uuid.UUID(record["source_id"]), uuid.UUID(record["event_id"])
        except (KeyError, ValueError, TypeError):
            raise InvalidInput(f"{number}번째 줄의 형식이 올바르지 않다")
        if SOURCE_KINDS.get(name) != kind:
            raise InvalidInput(f"{number}번째 줄: 이벤트 {name!r} 에 원천 종류 {kind!r} 는 맞지 않는다")
        if events.event_id_for(name, source_id) != event_id:
            raise InvalidInput(f"{number}번째 줄: event_id 가 원천 ID 에서 다시 계산한 값과 다르다(조작되었거나 깨진 목록)")
        items.append(Item(name, kind, source_id, event_id))
    return items, manifest["sha256"]


def _parse_ref(ref):
    try:
        media_id, reaction_id = ref.split(":")
        return uuid.UUID(media_id), uuid.UUID(reaction_id)
    except (ValueError, AttributeError):
        return None


def _writer(item, decisions, reactions, charges):
    """항목 하나에 대해 `(쓰는 함수 또는 None, 이유, 옛 형식 근거 여부)`. 쓸 수 없으면 쓰는 함수가 `None` 이고 이유가 사정이다."""
    name = item.event_name
    if name == events.NAMES["decision"]:
        d = decisions.get(item.source_id)
        return ((lambda: services._record_decision_event(d, d.decided_at)) if d else None), "원본 결정이 없다", False
    if name == events.NAMES["reaction_received"]:
        r = reactions.get(item.source_id)
        return ((lambda: services._record_received_event(r)) if r else None), "원본 반응이 없다", False
    if name == events.NAMES["reaction"]:
        r = reactions.get(item.source_id)
        if r is None:
            return None, "원본 반응이 없다", False
        if r.status == "RECEIVED":
            return None, NOT_JUDGED, False  # 아직 판정 전: 판정이 라이브로 만든다
        legacy = (r.basis or {}).get("v") == 0  # 2-13 이전 판정: 사람·슬롯 성격이 없는 옛 형식 근거 — 이벤트는 만들되 따로 센다
        return (lambda: processing.judged_event(r, r.status, r.reason_code, r.applied_rule, r.basis, r.processed_at)), "", legacy
    entry = charges.get(item.source_id)
    if entry is None:
        return None, "원본 원장 항목이 없다", False
    ref = _parse_ref(entry.reaction_ref)
    reaction = Reaction.objects.filter(media_id=ref[0], reaction_id=ref[1]).first() if ref else None
    if reaction is None or reaction.processed_at is None:
        return None, "과금을 일으킨 반응을 찾을 수 없다(결정을 추측하지 않는다)", False
    return (lambda: processing.charge_event(
        entry_id=entry.entry_id, campaign_id=entry.campaign_id, charge_policy=entry.charge_policy, created_at=entry.created_at, reaction_ref=entry.reaction_ref,
        decision_id=reaction.decision_id, charged=entry.charged, shortfall=entry.shortfall, now=reaction.processed_at)), "", False


def backfill(manifest_path, apply=False, chunk=CHUNK):
    """입력 목록의 원본 행에 이벤트를 채운다. `apply=False` 면 아무것도 쓰지 않고 무엇을 쓸지만 센다. 반환: `Result`."""
    items, input_sha256 = read_items(manifest_path)
    result = Result(input_sha256=input_sha256, applied=apply)
    for index, part in enumerate(batched(items, chunk)):
        with transaction.atomic():  # 청크의 이벤트와 감사 로그는 함께 커밋되거나 함께 되돌려진다
            missing = set(events.missing_event_ids([i.event_id for i in part]))  # outbox 에도 MongoDB 에도 없는 것만 쓴다(라이브가 먼저 만들었을 수 있다)
            wanted = [i for i in part if i.event_id in missing]
            decisions = {d.decision_id: d for d in Decision.objects.filter(pk__in=[i.source_id for i in wanted if i.source_kind == "decision"])}
            reactions = {r.inbox_id: r for r in Reaction.objects.filter(pk__in=[i.source_id for i in wanted if i.source_kind == "reaction"])}
            charges = {e.entry_id: e for e in billing.charge_entries([i.source_id for i in wanted if i.source_kind == "ledger_charge"])}
            written = 0
            for item in part:
                if item.event_id not in missing:
                    result.outcomes.append(Outcome(item, ALREADY))
                    continue
                write, reason, legacy = _writer(item, decisions, reactions, charges)
                if write is None:
                    result.outcomes.append(Outcome(item, NOT_JUDGED if reason == NOT_JUDGED else UNRESOLVED, "" if reason == NOT_JUDGED else reason))
                    continue
                if apply:
                    write()
                    written += 1
                result.outcomes.append(Outcome(item, WRITTEN if apply else WOULD_WRITE, legacy_basis=legacy))
            if apply and written:
                record_audit(None, "events.backfilled", detail={"input_sha256": input_sha256, "written": written, "chunk": index})
    return result
